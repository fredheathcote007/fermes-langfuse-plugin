"""Subprocess-only real-SDK probe of trace shape for delegated subagents; NEVER uses live credentials.

Drives a parent turn, a subagent_start, the subagent's own turn and the stops through the plugin hooks
against the real Langfuse SDK with an in-memory exporter, then prints the exported span tree as JSON.
Python-level network access is denied for the whole run.
"""
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class Capture(SpanExporter):
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def deny_network(*args, **kwargs):
    raise AssertionError('unexpected network operation from trace-shape probe')


for _method in ('connect', 'connect_ex', 'send', 'sendall', 'sendto', 'sendmsg'):
    setattr(socket.socket, _method, deny_network)
socket.create_connection = deny_network
socket.getaddrinfo = deny_network

plugin_file = Path(sys.argv[1]).resolve()
home = Path(sys.argv[2]).resolve()
home.mkdir(parents=True, exist_ok=True)
os.environ['HERMES_HOME'] = str(home)
spec = importlib.util.spec_from_file_location('langfuse_plugin', plugin_file,
                                              submodule_search_locations=[str(plugin_file.parent)])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class Ctx:
    plugin_id = 'langfuse'
    profile_name = 'custom'

    def get_config(self, name, default=False):
        return False

    def current_cron_execution(self):
        return None


mod._PLUGIN_CTX = Ctx()
capture = Capture()
sdk = Langfuse(public_key='pk-lf-synthetic-traceshape', secret_key='sk-lf-synthetic-traceshape',
               base_url='http://127.0.0.1:9', span_exporter=capture, tracer_provider=TracerProvider(),
               flush_at=256, flush_interval=60)
mod._get_langfuse = lambda: sdk


def start_llm(session, turn):
    mod.on_pre_llm_request(task_id=session, session_id=session, platform='cli', model='synthetic-model',
                           provider='synthetic', api_mode='chat', api_call_count=1,
                           request_messages=[{'role': 'user', 'content': 'synthetic'}],
                           turn_id=turn, api_request_id=f'{turn}:api:1')


def end_llm(session, turn):
    # The turn-level post_llm_call ends the turn's trace, as Hermes does when the turn completes.
    mod.on_post_llm_call(task_id=session, session_id=session, api_call_count=1, turn_id=turn,
                         api_request_id=f'{turn}:api:1', model='synthetic-model', assistant_response='ok')


try:
    # Delegation happens mid-turn (from a tool call), while the parent turn's trace is still open.
    start_llm('parent-sess', 'parent-sess:t1')
    mod.on_subagent_start(parent_turn_id='parent-sess:t1', child_session_id='child-sess',
                          child_role='leaf', child_goal='synthetic goal')
    start_llm('child-sess', 'child-sess:t1')
    end_llm('child-sess', 'child-sess:t1')
    mod.on_subagent_stop(parent_turn_id='parent-sess:t1', child_session_id='child-sess', child_role='leaf',
                         child_summary='synthetic summary')
    end_llm('parent-sess', 'parent-sess:t1')
    leftover = len(mod._SUBAGENT_PARENT_BY_CHILD)
    sdk.flush()
finally:
    sdk.shutdown()


def fmt(value, width):
    return format(value, f'0{width}x') if value is not None else None


spans = []
for span in capture.spans:
    attrs = dict(span.attributes or {})
    spans.append({
        'name': span.name,
        'trace_id': fmt(span.context.trace_id, 32),
        'span_id': fmt(span.context.span_id, 16),
        'parent_span_id': fmt(span.parent.span_id, 16) if span.parent is not None else None,
        'as_root': bool(attrs.get('langfuse.internal.as_root')),
        'session_id': attrs.get('session.id'),
        'trace_name': attrs.get('langfuse.trace.name'),
        'has_trace_input': 'langfuse.trace.input' in attrs,
        'has_trace_output': 'langfuse.trace.output' in attrs,
        'metadata': {k: v for k, v in attrs.items() if k.startswith('langfuse.observation.metadata')},
    })
print(json.dumps({'spans': spans, 'leftover_child_links': leftover}))

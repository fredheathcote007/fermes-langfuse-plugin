"""Subprocess-only synthetic SDK-backed privacy probe; NEVER uses live credentials."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

class Capture(SpanExporter):
    def __init__(self): self.spans=[]
    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS
    def shutdown(self): pass

plugin_file=Path(sys.argv[1]).resolve()
home=Path(sys.argv[2]).resolve()
home.mkdir(parents=True, exist_ok=True)
os.environ['HERMES_HOME']=str(home)
spec=importlib.util.spec_from_file_location('langfuse_plugin', plugin_file, submodule_search_locations=[str(plugin_file.parent)])
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)
class Config:
    plugin_id='langfuse'
    profile_name='synthetic-profile'
    def get_config(self, name, default=False):
        assert name=='end_user_attribution'
        return bool(int(os.getenv('SYNTHETIC_OPTIN', '0')))
    def current_cron_execution(self): return None
mod._PLUGIN_CTX=Config()
assert mod._sdk_identity_queue_discard_verified() is False
capture=Capture()
sdk=Langfuse(public_key='pk-lf-synthetic-obs002',secret_key='sk-lf-synthetic-obs002',base_url='http://127.0.0.1:9',span_exporter=capture,tracer_provider=TracerProvider(),flush_at=256,flush_interval=60)
mod._get_langfuse=lambda: sdk
try:
    mod.on_pre_llm_call(turn_id='turn', sender_id='SYNTHETIC_USER_NEVER_REAL')
    mod.on_pre_llm_request(session_id='synthetic-session',turn_id='turn',api_request_id='request',provider='provider',model='synthetic-model',messages=[])
    state_key=mod._trace_key('', 'synthetic-session',turn_id='turn')
    assert 'user_id' not in mod._TRACE_STATE[state_key].propagated
    mod._finish_trace(state_key)
    sdk.flush()
    recorded=[(span.name,dict(span.attributes or {})) for span in capture.spans]
    assert recorded, 'No span export, so the test is inconclusive'
    assert 'SYNTHETIC_USER_NEVER_REAL' not in repr(recorded)
    assert 'user.id' not in repr(recorded).lower()
    print(json.dumps({'status':'PASS','exported_spans':len(recorded),'optional_identity_absent':True,'network':'in-process exporter only'}))
finally:
    sdk.shutdown()

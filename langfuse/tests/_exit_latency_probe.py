"""Subprocess-only probe: how long does process exit take when the Langfuse endpoint never answers?

argv: plugin __init__.py, HERMES_HOME dir, blackhole port, mode ("finalize" = session_finalize(shutdown)
then exit; "atexit" = plain exit with a turn still open). Synthetic keys only; the endpoint is a local
socket that accepts connections and never replies. Prints one JSON line with the measured timings;
the parent measures total wall time to process exit.
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

plugin_file = Path(sys.argv[1]).resolve()
home = Path(sys.argv[2]).resolve()
port = int(sys.argv[3])
mode = sys.argv[4]
home.mkdir(parents=True, exist_ok=True)
os.environ['HERMES_HOME'] = str(home)
os.environ['HERMES_LANGFUSE_PUBLIC_KEY'] = 'pk-lf-synthetic-exitprobe'
os.environ['HERMES_LANGFUSE_SECRET_KEY'] = 'sk-lf-synthetic-exitprobe'
os.environ['HERMES_LANGFUSE_BASE_URL'] = f'http://127.0.0.1:{port}'

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
client = mod._get_langfuse()
assert client is not None, 'plugin did not build an SDK client'

turn_start = time.monotonic()
mod.on_pre_llm_request(task_id='s', session_id='s', platform='cli', model='m', provider='p', api_mode='chat',
                       api_call_count=1, request_messages=[{'role': 'user', 'content': 'synthetic'}],
                       turn_id='s:t1', api_request_id='s:t1:api:1')
if mode == 'finalize':
    mod.on_post_llm_call(task_id='s', session_id='s', api_call_count=1, turn_id='s:t1',
                         api_request_id='s:t1:api:1', model='m', assistant_response='ok')
turn_seconds = time.monotonic() - turn_start

finalize_seconds = None
if mode == 'finalize':
    start = time.monotonic()
    mod.on_session_finalize(session_id='s', reason='shutdown')
    finalize_seconds = time.monotonic() - start
print(json.dumps({'turn_seconds': round(turn_seconds, 3),
                  'finalize_seconds': None if finalize_seconds is None else round(finalize_seconds, 3)}),
      flush=True)

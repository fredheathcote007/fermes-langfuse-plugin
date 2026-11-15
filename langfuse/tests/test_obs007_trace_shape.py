"""OBS-007 trace shape: delegated subagent turns join their parent's trace; profile_ref tells profiles apart.

The real-SDK case runs in a subprocess with a capture-only exporter, synthetic keys and no network
(same pattern as test_obs002_sdk_egress_failclosed). The rest drive the hooks against recorders.
"""
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _real_sdk_spans(tmp_path):
    plugin_file = Path(__file__).resolve().parents[1] / '__init__.py'
    helper = Path(__file__).with_name('_trace_shape_probe.py')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LANGFUSE_', 'HERMES_LANGFUSE_'))}
    blocked = {str(plugin_file.parent.resolve()), str(plugin_file.parent.parent.resolve()),
               str(Path(__file__).parent.resolve())}
    env['PYTHONPATH'] = os.pathsep.join(p for p in env.get('PYTHONPATH', '').split(os.pathsep)
                                        if p and str(Path(p).resolve()) not in blocked)
    result = subprocess.run([sys.executable, str(helper), str(plugin_file), str(tmp_path / 'home')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-1500:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_real_sdk_subagent_turn_is_a_child_of_the_parent_subagent_span(tmp_path):
    receipt = _real_sdk_spans(tmp_path)
    spans = receipt['spans']
    by_name = {}
    for span in spans:
        by_name.setdefault(span['name'], []).append(span)
    root, = by_name['Hermes turn']
    subagent, = by_name['Subagent: leaf']
    child_turn, = by_name['Subagent turn']
    llm_calls = by_name['LLM call 1']

    # One trace for the whole delegation, with exactly one Langfuse root.
    assert {s['trace_id'] for s in spans} == {root['trace_id']}
    assert [s['name'] for s in spans if s['as_root']] == ['Hermes turn']
    # Parent turn -> "Subagent" span -> the subagent's own turn -> its LLM call.
    assert subagent['parent_span_id'] == root['span_id']
    assert child_turn['parent_span_id'] == subagent['span_id']
    assert sorted(c['parent_span_id'] for c in llm_calls) == sorted([root['span_id'], child_turn['span_id']])
    # Trace-level attributes stay the parent's: the child must not relabel the parent trace.
    assert {s['session_id'] for s in spans} == {'parent-sess'}
    assert {s['trace_name'] for s in spans} == {'Hermes turn'}
    assert not child_turn['has_trace_input'] and not child_turn['has_trace_output']
    assert root['has_trace_input'] and root['has_trace_output']
    assert any(v == 'child-sess' for v in child_turn['metadata'].values())
    # The link is released at subagent_stop.
    assert receipt['leftover_child_links'] == 0


class _Span:
    def __init__(self, sink, kw, span_id=None):
        self.sink, self.kw, self.id = sink, kw, span_id
        self.ended = False

    def start_observation(self, **kw):
        child = _Span(self.sink, {**kw, '_parent': self}, span_id=f'{len(self.sink) + 1:016x}')
        self.sink.append(child)
        return child

    def update(self, **kw):
        pass

    def set_trace_io(self, **kw):
        self.kw.setdefault('_trace_io', []).append(kw)

    def end(self, **kw):
        self.ended = True


class _Client:
    """Recorder with SDK-shaped ids (32-hex trace ids, 16-hex span ids)."""

    def __init__(self):
        self.roots = []
        self.spans = []

    def create_trace_id(self, seed=None):
        return format(abs(hash(seed)) % (1 << 128), '032x')

    def start_observation(self, **kw):
        root = _Span(self.spans, kw, span_id=f'{len(self.spans) + 1:016x}')
        self.spans.append(root)
        self.roots.append(root)
        return root

    def flush(self):
        pass


def _plugin(monkeypatch, client):
    sys.modules.pop('langfuse_plugin', None)
    mod = importlib.import_module('langfuse_plugin')
    monkeypatch.setattr(mod, '_get_langfuse', lambda: client)
    monkeypatch.setattr(mod, 'propagate_attributes', None)
    for mapping in (mod._TRACE_STATE, mod._SUBAGENT_PARENT_BY_CHILD):
        mapping.clear()
    return mod


def _start_turn(mod, session):
    mod.on_pre_llm_request(task_id=session, session_id=session, platform='cli', model='m', provider='p',
                           api_mode='chat', api_call_count=1, request_messages=[{'role': 'user', 'content': 'x'}],
                           turn_id=f'{session}:t1', api_request_id=f'{session}:t1:api:1')


def test_child_link_is_scoped_to_the_profile_that_spawned_it(monkeypatch, tmp_path):
    """A same-named child session served for ANOTHER profile must not join profile A's trace."""
    client = _Client()
    mod = _plugin(monkeypatch, client)
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home_a, home_b = tmp_path / 'a', tmp_path / 'b'
    home_a.mkdir(), home_b.mkdir()
    token = set_hermes_home_override(str(home_a))
    try:
        _start_turn(mod, 'parent')
        mod.on_subagent_start(parent_turn_id='parent:t1', child_session_id='shared-child', child_role='leaf')
    finally:
        reset_hermes_home_override(token)
    token = set_hermes_home_override(str(home_b))
    try:
        _start_turn(mod, 'shared-child')
    finally:
        reset_hermes_home_override(token)
    # Profile B's turn opened its own root through the client, not under A's subagent span.
    assert [r.kw['name'] for r in client.roots] == ['Hermes turn', 'Hermes turn']


def test_stop_without_a_child_turn_releases_the_link(monkeypatch):
    client = _Client()
    mod = _plugin(monkeypatch, client)
    _start_turn(mod, 'parent')
    mod.on_subagent_start(parent_turn_id='parent:t1', child_session_id='c1', child_role='leaf')
    assert len(mod._SUBAGENT_PARENT_BY_CHILD) == 1
    mod.on_subagent_stop(parent_turn_id='parent:t1', child_session_id='c1', child_role='leaf')
    assert len(mod._SUBAGENT_PARENT_BY_CHILD) == 0


def test_non_sdk_subagent_observation_keeps_the_separate_trace(monkeypatch):
    """Without real SDK ids the child keeps its own trace (the previous, still-valid behaviour)."""
    client = _Client()
    mod = _plugin(monkeypatch, client)
    _start_turn(mod, 'parent')
    state = next(iter(mod._TRACE_STATE.values()))
    state.trace_id = 'not-a-langfuse-trace-id'
    mod.on_subagent_start(parent_turn_id='parent:t1', child_session_id='c2', child_role='leaf')
    _start_turn(mod, 'c2')
    assert len(mod._SUBAGENT_PARENT_BY_CHILD) == 0
    assert [r.kw['name'] for r in client.roots] == ['Hermes turn', 'Hermes turn']


def test_profile_ref_distinguishes_homes_without_exporting_the_path(monkeypatch, tmp_path):
    client = _Client()
    mod = _plugin(monkeypatch, client)
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    refs = []
    for name in ('profile-one', 'profile-two'):
        home = tmp_path / name
        home.mkdir()
        token = set_hermes_home_override(str(home))
        try:
            _start_turn(mod, f'sess-{name}')
        finally:
            reset_hermes_home_override(token)
        metadata = client.roots[-1].kw['metadata']
        refs.append(metadata['profile_ref'])
        assert re.fullmatch(r'[0-9a-f]{12}', metadata['profile_ref'])
        assert str(tmp_path) not in json.dumps(metadata) and name not in metadata['profile_ref']
    assert refs[0] != refs[1]


def test_profile_ref_is_empty_when_the_home_key_is_unusable(monkeypatch):
    """No constant digest of "None" or "": an unresolvable home exports no profile_ref."""
    sys.modules.pop('langfuse_plugin', None)
    mod = importlib.import_module('langfuse_plugin')
    import hermes_constants
    for bad in (None, ''):
        monkeypatch.setattr(hermes_constants, 'hermes_home_key', lambda bad=bad: bad)
        assert mod._profile_ref() == ''

"""OBS-007: bounded exit-time export work, export timeout, queue size and visible queue-full drops.

The latency cases run the real SDK in a subprocess (``_exit_latency_probe.py``) against a loopback
socket: one that accepts and never replies (Langfuse unreachable), and one that answers every OTLP
POST with 200 (Langfuse healthy). Synthetic keys only; nothing leaves the machine.
"""
import http.server
import importlib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[1] / '__init__.py'
_PROBE = Path(__file__).with_name('_exit_latency_probe.py')


def _env():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('LANGFUSE_', 'HERMES_LANGFUSE_', 'OTEL_BSP_'))}
    blocked = {str(_PLUGIN.parent.resolve()), str(_PLUGIN.parent.parent.resolve()), str(_PROBE.parent.resolve())}
    env['PYTHONPATH'] = os.pathsep.join(p for p in env.get('PYTHONPATH', '').split(os.pathsep)
                                        if p and str(Path(p).resolve()) not in blocked)
    return env


def _run_probe(tmp_path, port, mode):
    start = time.monotonic()
    result = subprocess.run([sys.executable, str(_PROBE), str(_PLUGIN), str(tmp_path / f'home-{mode}'), str(port), mode],
                            cwd=tmp_path, env=_env(), capture_output=True, text=True, timeout=60, check=False)
    wall = time.monotonic() - start
    assert result.returncode == 0, result.stderr[-1500:]
    return wall, json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def blackhole():
    """Accepts connections and never replies: an unreachable Langfuse."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(64)
    held = []

    def accept():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            held.append(conn)

    threading.Thread(target=accept, daemon=True).start()
    yield server.getsockname()[1]
    server.close()
    for conn in held:
        conn.close()


@pytest.fixture
def healthy():
    """Answers every OTLP POST with 200 and counts them: a reachable Langfuse."""
    posts = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            posts.append(self.path)
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], posts
    server.shutdown()


@pytest.mark.parametrize('mode', ['finalize', 'atexit'])
def test_exit_is_bounded_when_langfuse_is_unreachable(tmp_path, blackhole, mode):
    """Previously ~5.2 s inside finalize and 5.7–7.0 s to process exit; now bounded by the 2 s defaults."""
    wall, receipt = _run_probe(tmp_path, blackhole, mode)
    assert receipt['turn_seconds'] < 1.0  # turns never waited on export
    if mode == 'finalize':
        assert receipt['finalize_seconds'] < 3.0
    assert wall < 4.5, wall


@pytest.mark.parametrize('mode', ['finalize', 'atexit'])
def test_healthy_endpoint_still_receives_spans_and_exits_quickly(tmp_path, healthy, mode):
    port, posts = healthy
    wall, receipt = _run_probe(tmp_path, port, mode)
    assert posts and all(p.endswith('/api/public/otel/v1/traces') for p in posts)
    if mode == 'finalize':
        assert receipt['finalize_seconds'] < 1.0
    assert wall < 4.0, wall


def _plugin():
    sys.modules.pop('langfuse_plugin', None)
    mod = importlib.import_module('langfuse_plugin')
    mod._resolve_flush_timeout.cache_clear()
    return mod


@pytest.mark.parametrize('raw, expected', [('', 2.0), ('0.5', 0.5), ('0', 0.0), ('abc', 2.0), ('-1', 2.0), ('nan', 2.0)])
def test_flush_timeout_setting(monkeypatch, caplog, raw, expected):
    mod = _plugin()
    monkeypatch.setenv('HERMES_LANGFUSE_FLUSH_TIMEOUT', raw)
    with caplog.at_level(logging.WARNING):
        assert mod._flush_timeout() == expected
    assert ('HERMES_LANGFUSE_FLUSH_TIMEOUT' in caplog.text) == (raw in ('abc', '-1', 'nan'))


def test_bounded_returns_promptly_and_never_raises(monkeypatch):
    mod = _plugin()
    monkeypatch.setenv('HERMES_LANGFUSE_FLUSH_TIMEOUT', '0.2')
    release = threading.Event()
    start = time.monotonic()
    assert mod._bounded('slow', lambda: release.wait(5)) is False
    assert time.monotonic() - start < 1.0
    release.set()
    assert mod._bounded('boom', lambda: 1 / 0) is True  # an exception is swallowed, not raised


def test_bounded_falls_back_to_a_direct_call_when_no_thread_can_start(monkeypatch):
    mod = _plugin()

    def refuse(self):
        raise RuntimeError("can't create new thread at interpreter shutdown")

    monkeypatch.setattr(threading.Thread, 'start', refuse)
    calls = []
    assert mod._bounded('exit flush', lambda: calls.append('ran')) is True
    assert calls == ['ran']
    assert mod._bounded('exit flush', lambda: 1 / 0) is True  # still never raises


class _RecordingLangfuse:
    seen = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _RecordingLangfuse.seen.append((kwargs, os.environ.get('OTEL_BSP_MAX_QUEUE_SIZE')))


def _build(mod, monkeypatch, **env):
    for key in ('HERMES_LANGFUSE_TIMEOUT', 'LANGFUSE_TIMEOUT', 'HERMES_LANGFUSE_MAX_QUEUE_SIZE',
                'OTEL_BSP_MAX_QUEUE_SIZE'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('HERMES_LANGFUSE_PUBLIC_KEY', 'pk-lf-synthetic-build')
    monkeypatch.setenv('HERMES_LANGFUSE_SECRET_KEY', 'sk-lf-synthetic-build')
    monkeypatch.setenv('HERMES_LANGFUSE_BASE_URL', 'http://127.0.0.1:9')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _RecordingLangfuse.seen.clear()
    monkeypatch.setattr(mod, 'Langfuse', _RecordingLangfuse)
    for mapping in (mod._LANGFUSE_PROJECT_OWNER_BY_KEY, mod._LANGFUSE_SECRET_OWNER_BY_KEY):
        mapping.clear()
    assert mod._build_client() is not None
    kwargs, queue_during_build = _RecordingLangfuse.seen[-1]
    return kwargs, queue_during_build


def test_export_timeout_defaults_to_two_seconds_and_respects_operators(monkeypatch):
    mod = _plugin()
    assert _build(mod, monkeypatch)[0]['timeout'] == 2
    assert _build(mod, monkeypatch, HERMES_LANGFUSE_TIMEOUT='7')[0]['timeout'] == 7
    assert 'timeout' not in _build(mod, monkeypatch, LANGFUSE_TIMEOUT='9')[0]  # the SDK reads its own variable
    assert _build(mod, monkeypatch, HERMES_LANGFUSE_TIMEOUT='zero')[0]['timeout'] == 2


def test_queue_size_is_set_only_for_construction_and_never_over_an_operator_value(monkeypatch):
    mod = _plugin()
    assert _build(mod, monkeypatch)[1] is None  # unset: SDK default 2048
    _, during = _build(mod, monkeypatch, HERMES_LANGFUSE_MAX_QUEUE_SIZE='8192')
    assert during == '8192' and 'OTEL_BSP_MAX_QUEUE_SIZE' not in os.environ
    _, during = _build(mod, monkeypatch, HERMES_LANGFUSE_MAX_QUEUE_SIZE='8192', OTEL_BSP_MAX_QUEUE_SIZE='100')
    assert during == '100' and os.environ['OTEL_BSP_MAX_QUEUE_SIZE'] == '100'
    assert _build(mod, monkeypatch, HERMES_LANGFUSE_MAX_QUEUE_SIZE='-5')[1] is None


def test_queue_full_drops_are_reported_at_most_once_per_interval(monkeypatch, caplog):
    _plugin()
    mod = _plugin()  # a reload must replace the previous reporter, not add a second one
    otel = logging.getLogger('opentelemetry.sdk._shared_internal')
    assert sum(h.get_name() == 'hermes-langfuse-plugin-queue-full' for h in otel.handlers) == 1
    reporter = mod._QUEUE_FULL_REPORTER
    monkeypatch.setattr(reporter, '_last_report', float('-inf'))

    def record(msg):
        return logging.LogRecord('opentelemetry.sdk._shared_internal', logging.WARNING, __file__, 1,
                                 msg, ('span',), None)

    def reports():
        return [r for r in caplog.records if r.name == mod.logger.name and 'export queue is full' in r.getMessage()]

    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        for _ in range(5):
            reporter.handle(record('Queue full, dropping %s.'))
        reporter.handle(record('Unrelated %s warning'))
    assert len(reports()) == 1  # first drop reported; the rest of the interval is quiet
    assert 'HERMES_LANGFUSE_MAX_QUEUE_SIZE' in reports()[0].getMessage()
    monkeypatch.setattr(reporter, '_last_report', float('-inf'))  # the interval has passed
    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        reporter.handle(record('Queue full, dropping %s.'))
    assert len(reports()) == 2


def test_real_otel_queue_overflow_reaches_the_reporter(monkeypatch, caplog):
    """End to end through OpenTelemetry's own batch queue: a tiny queue that overflows is reported."""
    mod = _plugin()
    monkeypatch.setattr(mod._QUEUE_FULL_REPORTER, '_last_report', float('-inf'))
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

    class _Stuck(SpanExporter):
        def export(self, spans):
            return SpanExportResult.SUCCESS

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(_Stuck(), max_queue_size=2, max_export_batch_size=2,
                                                   schedule_delay_millis=60_000))
    tracer = provider.get_tracer('obs007-test')
    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        for _ in range(20):
            tracer.start_span('burst').end()
    provider.shutdown()
    assert any(r.name == mod.logger.name and 'export queue is full' in r.getMessage() for r in caplog.records)

"""Synthetic D02 project-client routing across Hermes multiplex profiles.

Uses real plugin client-construction and secret-scope paths, but substitutes a
non-network SDK constructor. No project, API call, credential or live plugin use.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib
import time
import sys
from threading import Barrier, Lock
from uuid import uuid4

import pytest

from agent import secret_scope
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


class _SyntheticClient:
    def __init__(self, kwargs):
        self._kwargs = dict(kwargs)
        self.flushes = 0
        self.shutdowns = 0

    def flush(self):
        self.flushes += 1

    def shutdown(self):
        self.shutdowns += 1


@pytest.fixture
def boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(secret_scope, '_MULTIPLEX_ACTIVE', True)
    sys.modules.pop('langfuse_plugin', None)
    mod = importlib.import_module('langfuse_plugin')
    monkeypatch.setattr(mod.atexit, 'register', lambda fn: None)
    created = []
    guard = Lock()

    def construct(**kwargs):
        client = _SyntheticClient(kwargs)
        with guard:
            created.append(client)
        return client

    monkeypatch.setattr(mod, 'Langfuse', construct)
    # These process values must never be consumed by a routed profile.
    monkeypatch.setenv('HERMES_LANGFUSE_PUBLIC_KEY', 'pk-lf-ambientshadow123456')
    monkeypatch.setenv('HERMES_LANGFUSE_SECRET_KEY', 'sk-lf-ambientshadow123456')
    monkeypatch.setenv('HERMES_LANGFUSE_BASE_URL', 'https://ambient.invalid')
    homes = (tmp_path / 'profile-a', tmp_path / 'profile-b', tmp_path / 'profile-c')
    for home in homes:
        home.mkdir()
    return mod, homes, created


def _values(label, *, legacy=False, base_url=None):
    # Generate unique synthetic values, never real credentials or identifiers.
    ident = uuid4().hex
    prefix = 'LANGFUSE_' if legacy else 'HERMES_LANGFUSE_'
    return {
        f'{prefix}PUBLIC_KEY': f'pk-lf-{ident}',
        f'{prefix}SECRET_KEY': f'sk-lf-{ident}',
        f'{prefix}BASE_URL': base_url or f'https://{label}.invalid',
    }


@contextmanager
def _serve(home, secrets):
    home_token = set_hermes_home_override(home)
    scope_token = secret_scope.set_secret_scope(secrets, profile_home=str(home))
    try:
        yield
    finally:
        secret_scope.reset_secret_scope(scope_token)
        reset_hermes_home_override(home_token)


def _require(condition, message):
    # Assertion message must not include synthetic key values in CI failure logs.
    if not condition:
        pytest.fail(message, pytrace=False)


def test_two_profiles_build_distinct_project_clients_and_reuse_by_home(boundary):
    mod, homes, created = boundary
    a, b = _values('profile-a'), _values('profile-b')
    with _serve(homes[0], a):
        client_a = mod._get_langfuse()
        _require(client_a is mod._get_langfuse(), 'profile A client was rebuilt')
    with _serve(homes[1], b):
        client_b = mod._get_langfuse()
        _require(client_b is mod._get_langfuse(), 'profile B client was rebuilt')
    _require(len(created) == 2 and client_a is not client_b, 'two profiles shared one SDK client')
    _require(client_a._kwargs['public_key'] == a['HERMES_LANGFUSE_PUBLIC_KEY'], 'wrong project key for A')
    _require(client_a._kwargs['secret_key'] == a['HERMES_LANGFUSE_SECRET_KEY'], 'wrong secret key for A')
    _require(client_a._kwargs['base_url'] == a['HERMES_LANGFUSE_BASE_URL'], 'wrong project URL for A')
    _require(client_b._kwargs['public_key'] == b['HERMES_LANGFUSE_PUBLIC_KEY'], 'wrong project key for B')
    _require(client_b._kwargs['secret_key'] == b['HERMES_LANGFUSE_SECRET_KEY'], 'wrong secret key for B')
    _require(client_b._kwargs['base_url'] == b['HERMES_LANGFUSE_BASE_URL'], 'wrong project URL for B')


def test_missing_multiplex_scope_never_uses_ambient_keys_or_constructs(boundary):
    mod, homes, created = boundary
    with _serve(homes[0], None):
        with pytest.raises(secret_scope.UnscopedSecretError):
            mod._get_langfuse()
    _require(not created, 'unscoped multiplex request constructed an SDK client')


def test_empty_scoped_keys_do_not_fall_back_to_ambient_process(boundary):
    mod, homes, created = boundary
    with _serve(homes[0], {}):
        _require(mod._get_langfuse() is None, 'profile with no scoped keys constructed a client')
    _require(not created, 'missing scoped credentials borrowed process credentials')


def test_legacy_keys_only_fallback_within_active_profile(boundary):
    mod, homes, created = boundary
    scoped = _values('legacy-only', legacy=True)
    with _serve(homes[0], scoped):
        client = mod._get_langfuse()
    _require(len(created) == 1 and client is created[0], 'legacy scoped fallback did not build one client')
    _require(client._kwargs['public_key'] == scoped['LANGFUSE_PUBLIC_KEY'], 'legacy project fallback escaped profile scope')
    _require(client._kwargs['base_url'] == scoped['LANGFUSE_BASE_URL'], 'legacy endpoint fallback escaped profile scope')


def test_present_placeholder_does_not_borrow_valid_legacy_or_ambient_key(boundary):
    mod, homes, created = boundary
    scoped = _values('legacy-valid', legacy=True)
    scoped.update({'HERMES_LANGFUSE_PUBLIC_KEY': 'pk-lf-placeholder-1234',
                   'HERMES_LANGFUSE_SECRET_KEY': 'sk-lf-placeholder-1234'})
    with _serve(homes[0], scoped):
        _require(mod._get_langfuse() is None, 'placeholder keys were allowed to construct a client')
    _require(not created, 'invalid scoped Hermes keys borrowed legacy or ambient credentials')


def test_custom_compatible_endpoint_allows_nonstandard_prefix_without_either_scope_leak(boundary):
    mod, homes, created = boundary
    scoped = {'HERMES_LANGFUSE_PUBLIC_KEY': 'synthetic-public-custom',
              'HERMES_LANGFUSE_SECRET_KEY': 'synthetic-secret-custom',
              'HERMES_LANGFUSE_BASE_URL': 'https://custom-langfuse.invalid'}
    with _serve(homes[0], scoped):
        client = mod._get_langfuse()
    _require(len(created) == 1 and client is created[0], 'custom endpoint unexpectedly refused its test credentials')
    _require(client._kwargs['public_key'] == scoped['HERMES_LANGFUSE_PUBLIC_KEY'], 'custom endpoint public key not scoped')
    _require(client._kwargs['secret_key'] == scoped['HERMES_LANGFUSE_SECRET_KEY'], 'custom endpoint secret not scoped')
    _require(client._kwargs['base_url'] == scoped['HERMES_LANGFUSE_BASE_URL'], 'custom endpoint base URL not scoped')


def test_client_cache_does_not_hot_rotate_credentials_or_cross_homes(boundary):
    mod, homes, created = boundary
    first, rotated, other = _values('initial'), _values('rotated'), _values('other')
    with _serve(homes[0], first):
        a = mod._get_langfuse()
    with _serve(homes[0], rotated):
        _require(mod._get_langfuse() is a, 'existing client silently rotated without restart')
    with _serve(homes[1], other):
        b = mod._get_langfuse()
    _require(len(created) == 2 and b is not a, 'profile cache reused another home client')
    _require(a._kwargs['secret_key'] == first['HERMES_LANGFUSE_SECRET_KEY'], 'cached client changed credentials')


def test_concurrent_profile_calls_keep_distinct_cached_project_clients(boundary):
    mod, homes, created = boundary
    a_keys, b_keys = _values('a'), _values('b')
    with _serve(homes[0], a_keys):
        a = mod._get_langfuse()
    with _serve(homes[1], b_keys):
        b = mod._get_langfuse()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(64):
            barrier = Barrier(2)
            def run(home, keys):
                with _serve(home, keys):
                    barrier.wait(timeout=4)
                    return mod._get_langfuse()
            x = pool.submit(run, homes[0], a_keys)
            y = pool.submit(run, homes[1], b_keys)
            _require(x.result(timeout=8) is a and y.result(timeout=8) is b,
                     'concurrent request crossed a project-client boundary')
    _require(len(created) == 2, 'concurrency created a duplicate or cross-profile client')


def test_cloud_endpoint_rejects_nonstandard_key_prefix(boundary):
    mod, homes, created = boundary
    scoped = {'HERMES_LANGFUSE_PUBLIC_KEY': 'custom-public-synthetic',
              'HERMES_LANGFUSE_SECRET_KEY': 'custom-secret-synthetic',
              'HERMES_LANGFUSE_BASE_URL': 'https://cloud.langfuse.com'}
    with _serve(homes[0], scoped):
        _require(mod._get_langfuse() is None, 'Cloud credentials without Langfuse prefixes were accepted')
    _require(not created, 'Cloud endpoint constructed client with invalid key prefixes')


def test_cloud_endpoint_accepts_valid_scoped_key_prefixes(boundary):
    mod, homes, created = boundary
    scoped = _values('cloud-valid', base_url='https://cloud.langfuse.com')
    with _serve(homes[0], scoped):
        client = mod._get_langfuse()
    _require(len(created) == 1 and client is created[0], 'valid Cloud scope was rejected')
    _require(client._kwargs['public_key'] == scoped['HERMES_LANGFUSE_PUBLIC_KEY'], 'Cloud project key not scoped')
    _require(client._kwargs['base_url'] == scoped['HERMES_LANGFUSE_BASE_URL'], 'Cloud base URL not scoped')


def test_cold_client_construction_race_is_serialised_for_distinct_profiles(boundary, monkeypatch):
    mod, homes, created = boundary
    a_keys, b_keys = _values('a'), _values('b')
    constructor = mod.Langfuse
    def slow_constructor(**kwargs):
        # Widen the first-build race without delaying an actual network operation.
        time.sleep(0.002)
        return constructor(**kwargs)
    monkeypatch.setattr(mod, 'Langfuse', slow_constructor)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for round_number in range(50):
            # A new isolated cold cache in each round; clients are fake objects.
            mod._LANGFUSE_CLIENT_BY_HOME.clear()
            barrier = Barrier(8)
            def start(home, credentials):
                with _serve(home, credentials):
                    barrier.wait(timeout=5)
                    return mod._get_langfuse()
            jobs = [pool.submit(start, homes[side], a_keys if side == 0 else b_keys)
                    for side in (0,1,0,1,0,1,0,1)]
            selected = [job.result(timeout=12) for job in jobs]
            _require(len(created) == 2 * (round_number + 1), 'concurrent cold start constructed duplicate SDK clients')
            _require(all(selected[side] is selected[0] for side in (0,2,4,6)), 'profile A cold starts differed')
            _require(all(selected[side] is selected[1] for side in (1,3,5,7)), 'profile B cold starts differed')
            _require(selected[0] is not selected[1], 'cold-start races shared a client across profiles')
            _require(selected[0]._kwargs['secret_key'] == a_keys['HERMES_LANGFUSE_SECRET_KEY'], 'cold A credential scope lost')
            _require(selected[1]._kwargs['secret_key'] == b_keys['HERMES_LANGFUSE_SECRET_KEY'], 'cold B credential scope lost')


def test_distinct_profile_homes_must_reject_same_project_credential_pair(boundary):
    """D02/T08: two profile homes may not share a project or credential pair."""
    mod, homes, created = boundary
    shared = _values('shared-project')
    with _serve(homes[0], shared):
        client_a = mod._get_langfuse()
    _require(client_a is not None, 'initial synthetic profile client missing')
    with _serve(homes[1], shared):
        client_b = mod._get_langfuse()
    _require(client_b is None, 'different profile reused an already-owned project credential pair')
    _require(len(created) == 1, 'a second SDK exporter was constructed for a shared project')


def test_distinct_profile_homes_reject_same_project_key_even_after_secret_rotation(boundary):
    """D02: a second API secret must not let another home claim the same project."""
    mod, homes, created = boundary
    original = _values('project-original')
    rotated = _values('project-rotated')
    rotated['HERMES_LANGFUSE_PUBLIC_KEY'] = original['HERMES_LANGFUSE_PUBLIC_KEY']
    with _serve(homes[0], original):
        _require(mod._get_langfuse() is not None, 'initial project client was not built')
    with _serve(homes[1], rotated):
        _require(mod._get_langfuse() is None, 'same project key bypassed collision using another secret')
    _require(len(created) == 1, 'second SDK client was constructed for duplicate project')


def test_concurrent_cold_homes_cannot_both_claim_shared_project_key(boundary):
    """D02: serialised first-build reservation must reject one racing profile."""
    mod, homes, created = boundary
    shared = _values('concurrent-shared')
    with ThreadPoolExecutor(max_workers=2) as pool:
        for round_number in range(32):
            mod._LANGFUSE_CLIENT_BY_HOME.clear()
            mod._LANGFUSE_PROJECT_OWNER_BY_KEY.clear()
            mod._LANGFUSE_SECRET_OWNER_BY_KEY.clear()
            barrier = Barrier(2)

            def start(home):
                with _serve(home, shared):
                    barrier.wait(timeout=4)
                    return mod._get_langfuse()

            left = pool.submit(start, homes[0]); right = pool.submit(start, homes[1])
            a, b = left.result(timeout=8), right.result(timeout=8)
            _require((a is None) != (b is None), 'two profiles both accepted or both rejected shared project')
            _require(len(created) == round_number + 1, 'duplicate exporter constructed during project-key race')


def test_distinct_profile_homes_reject_same_secret_with_different_public_key(boundary):
    """D02/T08: Langfuse API routing by secret cannot bypass profile ownership."""
    mod, homes, created = boundary
    original = _values('original-secret-owner')
    mismatched = _values('other-public-same-secret')
    mismatched['HERMES_LANGFUSE_SECRET_KEY'] = original['HERMES_LANGFUSE_SECRET_KEY']
    with _serve(homes[0], original):
        _require(mod._get_langfuse() is not None, 'original profile client missing')
    with _serve(homes[1], mismatched):
        _require(mod._get_langfuse() is None, 'reused secret bypassed project ownership guard')
    _require(len(created) == 1, 'second SDK exporter constructed for shared secret')


def test_real_gateway_profile_runtime_scope_rejects_cross_profile_project_secrets(boundary):
    """D02/T08: bind the real gateway scope, not a synthetic substitute."""
    from gateway.run import _profile_runtime_scope
    from hermes_constants import get_hermes_home_override

    mod, homes, created = boundary
    a = _values('gateway-a')
    b = _values('gateway-b')
    with _profile_runtime_scope(homes[0], a):
        client_a = mod._get_langfuse()
        _require(client_a is not None, 'gateway A failed to build its scoped client')
        _require(client_a is mod._get_langfuse(), 'gateway A did not retain its client')
    _require(get_hermes_home_override() is None, 'gateway A leaked home override')
    _require(secret_scope.current_secret_scope() is None, 'gateway A leaked credential scope')

    with _profile_runtime_scope(homes[1], b):
        client_b = mod._get_langfuse()
        _require(client_b is not None and client_b is not client_a, 'gateway B reused A SDK client')
    _require(get_hermes_home_override() is None, 'gateway B leaked home override')
    _require(secret_scope.current_secret_scope() is None, 'gateway B leaked credential scope')

    cross = dict(b)
    cross['HERMES_LANGFUSE_SECRET_KEY'] = a['HERMES_LANGFUSE_SECRET_KEY']
    with _profile_runtime_scope(homes[2], cross):
        _require(mod._get_langfuse() is None, 'gateway C accepted A secret with B public key')
    _require(len(created) == 2, 'negative gateway scope constructed an SDK client')
    _require(get_hermes_home_override() is None, 'gateway C leaked home override')
    _require(secret_scope.current_secret_scope() is None, 'gateway C leaked credential scope')

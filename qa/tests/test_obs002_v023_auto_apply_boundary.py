"""Offline v0.23 auto-update consent and held-ref control tests.

Invokes only the cadence decision path with injected update callbacks and fake
receipts. It never installs a plugin, fetches a commit, or modifies an install.
Requires the Hermes v0.23.0 checkout under PYTHONPATH; not run on older core.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from hermes_constants import set_hermes_home_override, reset_hermes_home_override

import pytest

from hermes_cli import plugins_cadence
from hermes_cli.plugins_cmd_catalog import RepinConsentRequired
from pm import receipt


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    home_token = set_hermes_home_override(tmp_path)
    markers = tmp_path / 'marker-only'
    markers.mkdir()
    calls = {'checked': 0, 'receipt': 0, 'applied': []}
    installs = {'langfuse': {'catalog': {'pin': 'a' * 40}, 'pinned': True}}

    def snapshot(_path):
        calls['checked'] += 1
        return installs

    monkeypatch.setattr(plugins_cadence, 'snapshot_installs', snapshot)
    monkeypatch.setattr(plugins_cadence, 'record_check_results', lambda *args: None)
    monkeypatch.setattr(plugins_cadence, '_markers_dir', lambda: markers)
    monkeypatch.setattr(receipt, 'begin', lambda *args: 'synthetic-receipt')
    monkeypatch.setattr(receipt, 'record_plugin_checks', lambda *args: None)
    def finished(*args, **kwargs):
        calls['receipt'] += 1
    monkeypatch.setattr(receipt, 'finalize', finished)

    def run(*, enabled=None, klass='catalog', install=None, callback=None):
        if install is not None:
            installs['langfuse'] = install
        update = SimpleNamespace(name='langfuse', klass=klass,
                                 update_available=True, needs_fixing=False)
        apply = callback or (lambda name: calls['applied'].append(name))
        def cfg(section, key):
            if (section,key) != ('plugins','auto_apply'):
                raise AssertionError('auto-update looked up the wrong config key')
            return enabled
        result = plugins_cadence._run_check_locked(
            run_checks_fn=lambda path: [update], plugins_dir=tmp_path,
            apply_updates_fn=apply, log=logging.getLogger('obs002.synthetic.updater'),
            config_get=cfg,
        )
        assert result == [update]
        return calls
    try:
        yield run, calls, markers
    finally:
        reset_hermes_home_override(home_token)


@pytest.mark.parametrize('unset_value',[None,False,0,''])
def test_default_off_never_calls_updater_despite_available_update(gate, unset_value):
    run, calls, markers = gate
    assert plugins_cadence.auto_apply_enabled(lambda section, key: unset_value) is False
    run(enabled=unset_value)
    assert calls['applied'] == []
    assert calls['checked'] == 1 and calls['receipt'] == 1
    assert (markers / 'last-run').exists()


def test_explicit_opt_in_only_applies_eligible_catalog_update(gate):
    run, calls, _ = gate
    run(enabled=True, klass='catalog')
    assert calls['applied'] == ['langfuse']
    assert calls['checked'] == 1 and calls['receipt'] == 1


def test_opt_in_ignores_noneligible_update_classes(gate):
    run, calls, _ = gate
    for klass in ('pip', 'manual', 'local', 'disabled'):
        run(enabled=True, klass=klass)
    assert calls['applied'] == []
    assert calls['checked'] == 4 and calls['receipt'] == 4


def test_held_with_ref_never_unattended_repins(gate):
    run, calls, _ = gate
    # Empty catalog pin plus pinned=true means deliberately installed --ref.
    held = {'catalog': {'pin': ''}, 'pinned': True}
    run(enabled=True, install=held)
    assert calls['applied'] == []
    assert calls['checked'] == 1 and calls['receipt'] == 1


def test_repin_needing_new_permission_does_not_publish(gate, caplog):
    run, calls, _ = gate
    def needs_consent(name):
        raise RepinConsentRequired(name, 'b' * 40, {'hooks': ['synthetic-hook']})
    with caplog.at_level(logging.INFO, logger='obs002.synthetic.updater'):
        run(enabled=True, callback=needs_consent)
    assert calls['applied'] == []
    assert calls['checked'] == 1 and calls['receipt'] == 1
    assert 'needs your review' in caplog.text
    assert 'synthetic-hook' not in caplog.text


def test_plugin_setting_must_be_looked_up_in_plugins_section(gate):
    run, calls, _ = gate
    def wrong_section_is_true(section, key):
        return True if section == 'unrelated' else False
    assert plugins_cadence.auto_apply_enabled(wrong_section_is_true) is False
    run(enabled=False)
    assert calls['applied'] == []


def test_refused_repin_does_not_block_other_independent_source_update(gate, caplog):
    run, calls, _ = gate
    updates = [SimpleNamespace(name='langfuse',klass='catalog',update_available=True),
               SimpleNamespace(name='other',klass='catalog',update_available=True)]
    installed = {'langfuse':{'pinned':True,'catalog':{'pin':'a'*40}},
                 'other':{'pinned':True,'catalog':{'pin':'b'*40}}}
    def callback(name):
        if name == 'langfuse':
            raise RepinConsentRequired(name, 'c'*40, {'hooks':['synthetic-hook']})
        calls['applied'].append(name)
    with caplog.at_level(logging.INFO, logger='obs002.synthetic.updater'):
        plugins_cadence._auto_apply(updates, installed, callback,
                                    logging.getLogger('obs002.synthetic.updater'))
    assert calls['applied'] == ['other']
    assert 'needs your review' in caplog.text

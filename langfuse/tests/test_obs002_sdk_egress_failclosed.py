"""Real SDK in subprocess, with capture-only exporter and synthetic test credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('optin', [False, True], ids=['default-off', 'explicit-unsafe-optin'])
def test_plugin_sdk_export_omits_optional_sender_identity(tmp_path, optin):
    plugin_file = Path(__file__).resolve().parents[1] / '__init__.py'
    helper = Path(__file__).with_name('_sdk_egress_probe.py')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('LANGFUSE_', 'HERMES_LANGFUSE_'))}
    blocked = {str(plugin_file.parent.resolve()), str(plugin_file.parent.parent.resolve()),
               str(Path(__file__).parent.resolve())}
    env['PYTHONPATH'] = os.pathsep.join(p for p in env.get('PYTHONPATH', '').split(os.pathsep)
                                           if p and str(Path(p).resolve()) not in blocked)
    env['SYNTHETIC_OPTIN'] = '1' if optin else '0'
    result = subprocess.run([sys.executable, str(helper), str(plugin_file), str(tmp_path / 'home')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
                            check=False)
    assert result.returncode == 0, result.stderr[-1000:]
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt['status'] == 'PASS'
    assert receipt['exported_spans'] >= 1
    assert receipt['optional_identity_absent'] is True
    assert receipt['network'] == 'in-process exporter only'

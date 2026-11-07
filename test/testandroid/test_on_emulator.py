# -*- coding: utf-8 -*-
"""
@File  : test_on_emulator.py
@Time  : 2026-11-07

Android on a real device (M5b, docs/design/decisions/14 §5): the `android`
fixture, the evidence and the verdicts of core/android.py, through a whole
run, against an emulator -- CI's `android` job boots one with KVM.

The app driven is the system's own Settings, on every image: no third-party
APK is downloaded. Its crash is real: `am crash` makes the system kill it
with a FATAL EXCEPTION, as a bug would.

Skipped unless IPANDORA_REQUIRE_EMULATOR (CI: fails without a device) or
IPANDORA_ANDROID_DEVICE (a device you attached) is set -- elsewhere it does
not even touch adb.
"""
import os
import re
import textwrap

import pytest

pytest.importorskip('uiautomator2', reason='the `android` extra is not installed')

SETTINGS = 'com.android.settings'
REQUIRED = bool(os.environ.get('IPANDORA_REQUIRE_EMULATOR'))

pytestmark = pytest.mark.skipif(not (REQUIRED or os.environ.get('IPANDORA_ANDROID_DEVICE')),
                                reason='no device: set IPANDORA_ANDROID_DEVICE=1 with one attached')

SUITE = '''
import time
import xml.etree.ElementTree as ET

SETTINGS = 'com.android.settings'


def _on_screen(android):
    assert android(packageName=SETTINGS).wait(timeout=30), 'Settings did not come up'
    return ET.fromstring(android.dump_hierarchy())


def test_settings_opens(android):
    _on_screen(android)
    assert android.app_current()['package'] == SETTINGS


def test_a_stale_selector(android):
    # a name on the screen, looked for through the wrong attribute: no widget matches, one has that name
    _root = _on_screen(android)
    _descs = {_n.get('content-desc') for _n in _root.iter('node')}
    _name = next(_n.get('text') for _n in _root.iter('node')
                 if _n.get('package') == SETTINGS and (_n.get('text') or '').strip() and _n.get('text') not in _descs)
    android(description=_name).click(timeout=3)


def test_a_widget_gone(android):
    _on_screen(android)
    android(text='ipandora-no-such-widget').click(timeout=3)


def test_an_assert_on_a_stale_selector(android):
    # CR19: the same mistake through `assert ... .exists` -- it was judged a plain assert, a product defect
    _root = _on_screen(android)
    _descs = {_n.get('content-desc') for _n in _root.iter('node')}
    _name = next(_n.get('text') for _n in _root.iter('node')
                 if _n.get('package') == SETTINGS and (_n.get('text') or '').strip() and _n.get('text') not in _descs)
    assert android(description=_name).exists


def test_the_app_crashed(android):
    _on_screen(android)
    android.shell(['am', 'crash', SETTINGS])
    time.sleep(3)
    assert android.app_current()['package'] == SETTINGS, 'Settings is gone'
'''


def _device():
    import uiautomator2
    try:
        _d = uiautomator2.connect(os.environ.get('ANDROID_SERIAL') or None)
        _d.info
        return _d
    except Exception as exc:  # noqa: BLE001 -- the reason goes into the skip or the failure
        if REQUIRED:
            pytest.fail('IPANDORA_REQUIRE_EMULATOR is set and no device answers: {}'.format(exc))
        pytest.skip('no device answers: {}'.format(exc))


def test_a_run_on_the_device(tmp_path, monkeypatch):
    from ipandora.core.runner import run
    from ipandora.core.schedule import config
    from ipandora.core.schedule.runtime import Runtime
    from ipandora.core.triage import triage
    _d = _device()
    # the log window opens to the millisecond (CR19): the device's `date` must print nanoseconds
    from ipandora.core import android
    assert re.fullmatch(r'\d+\.\d{9}', android._shell(_d, ['date', '+%s.%N']).strip())
    assert re.fullmatch(r'\d+\.\d{3}', android._device_time(_d))
    monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {'android': {
        'serial': getattr(_d, 'serial', '') or '', 'package': SETTINGS}}))
    monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
    _suite = tmp_path / 'suite'
    _suite.mkdir()
    (_suite / 'test_settings.py').write_text(textwrap.dedent(SUITE), encoding='utf-8')
    _result = run(str(_suite), persist=False, quiet=True, baseline='')
    _by = {_c.nodeid.split('::')[-1]: _c for _c in _result.cases}
    assert _by['test_settings_opens'].outcome == 'passed', _by['test_settings_opens'].message
    _verdicts = {_f.nodeid.split('::')[-1]: _f for _f in triage(_result).findings}
    assert set(_verdicts) == {'test_a_stale_selector', 'test_a_widget_gone', 'test_the_app_crashed',
                              'test_an_assert_on_a_stale_selector'}, {
        _k: _v.reason for _k, _v in _verdicts.items()}
    assert (_verdicts['test_a_stale_selector'].category, _verdicts['test_a_stale_selector'].confidence) == (
        'harness', 'medium'), _verdicts['test_a_stale_selector'].reason
    assert _verdicts['test_a_widget_gone'].category == 'unknown', _verdicts['test_a_widget_gone'].reason
    assert (_verdicts['test_an_assert_on_a_stale_selector'].category,
            _verdicts['test_an_assert_on_a_stale_selector'].confidence) == ('harness', 'medium'), \
        _verdicts['test_an_assert_on_a_stale_selector'].reason
    assert (_verdicts['test_the_app_crashed'].category, _verdicts['test_the_app_crashed'].confidence) == (
        'defect', 'high'), _verdicts['test_the_app_crashed'].reason
    assert _by['test_the_app_crashed'].app_events[0]['kind'] == 'crash'
    assert _by['test_the_app_crashed'].app_events[0]['package'] == SETTINGS
    for _name in ('test_a_widget_gone', 'test_the_app_crashed'):
        _kinds = {_a['kind']: _a for _a in _by[_name].artifacts}
        assert {'screenshot', 'hierarchy', 'device-log'} <= set(_kinds), (_name, list(_kinds))
        with open(_kinds['screenshot']['path'], 'rb') as _f:
            assert _f.read(8) == b'\x89PNG\r\n\x1a\n'
        with open(_kinds['hierarchy']['path'], encoding='utf-8') as _f:
            assert '<hierarchy' in _f.read()
    assert 'FATAL EXCEPTION' in {_a['kind']: _a for _a in _by['test_the_app_crashed'].artifacts}['device-log']['text']
    assert _by['test_settings_opens'].artifacts == []

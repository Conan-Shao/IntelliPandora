# -*- coding: utf-8 -*-
"""
@File  : test_android.py
@Time  : 2026-11-07

Android through uiautomator2 (docs/design/decisions/14 §5, M5a): the device
fixture's lifecycle and lock, the evidence of a failure, and the verdict --
a crash of the app is a product defect, a selector that finds nothing is
looked for by name in the widget tree. The device is a stand-in
(fake_device.py); uiautomator2's own selector code runs. A real emulator
runs the same cases in CI (M5b).
"""
import os
import textwrap

import pytest

pytest.importorskip('uiautomator2', reason='the `android` extra is not installed')

from ipandora.core import android  # noqa: E402
from ipandora.core.evidence import recorder  # noqa: E402
from ipandora.core.triage import classify  # noqa: E402

from test.testandroid.fake_device import APP_LOG, CRASH_LOG, HIERARCHY, PACKAGE, FakeDevice  # noqa: E402


class TestTheLog:

    def test_a_crash_of_the_app(self):
        assert android.app_events(CRASH_LOG, PACKAGE) == [
            {'kind': 'crash', 'package': PACKAGE, 'detail': 'java.lang.NullPointerException: cart was null'}]

    def test_another_apps_crash_is_not_this_cases(self):
        _other = CRASH_LOG.replace('Process: com.example.shop', 'Process: com.other.app')
        assert android.app_events(_other, PACKAGE) == [] and android.app_events(APP_LOG, PACKAGE) == []

    def test_a_crash_of_a_process_of_the_app(self):
        _sub = CRASH_LOG.replace('Process: com.example.shop,', 'Process: com.example.shop:sync,')
        assert [_e['kind'] for _e in android.app_events(_sub, PACKAGE)] == ['crash']

    def test_an_anr(self):
        _log = ('11-07 12:00:05.000  500  520 E ActivityManager: ANR in com.example.shop (com.example.shop/.Main)\n'
                '11-07 12:00:05.000  500  520 E ActivityManager: PID: 4242\n'
                '11-07 12:00:05.000  500  520 E ActivityManager: Reason: Input dispatching timed out\n')
        assert android.app_events(_log, PACKAGE) == [
            {'kind': 'anr', 'package': PACKAGE, 'detail': 'Input dispatching timed out'}]
        assert android.app_events(_log.replace('ANR in com.example.shop', 'ANR in com.other'), PACKAGE) == []

    def test_the_apps_own_lines_and_every_crash(self):
        _kept = android.relevant(CRASH_LOG, PACKAGE, ['4242'])
        assert 'OtherApp' not in _kept and 'onCreate' in _kept and 'FATAL EXCEPTION' in _kept
        _many = '\n'.join('11-07 12:00:01.100  4242  4242 I Shop: line {}'.format(_i) for _i in range(1000))
        assert android.relevant(_many, PACKAGE, ['4242']).splitlines()[-1].endswith('line 999')
        assert len(android.relevant(_many, PACKAGE, ['4242']).splitlines()) == android.LOG_LINES


class TestTheWidgetTree:

    @pytest.mark.parametrize('names, found', [
        (['Login'], [{'role': 'Button', 'name': 'Login', 'attribute': 'content-desc'}]),
        (['login'], [{'role': 'Button', 'name': 'Login', 'attribute': 'content-desc'}]),
        (['com.example.shop:id/title'], [{'role': 'TextView', 'name': 'com.example.shop:id/title',
                                          'attribute': 'resource-id'}]),
        (['sign_in'], [{'role': 'Button', 'name': 'sign_in', 'attribute': 'resource-id'}]),
        (['Checkout'], []),
        ([], []),
    ])
    def test_same_name(self, names, found):
        assert android.same_name(HIERARCHY, names) == found

    def test_a_tree_that_does_not_parse(self):
        assert android.same_name('<hierarchy><node', ['Login']) == []

    def test_what_a_selector_calls_the_widget(self):
        from uiautomator2._selector import Selector
        assert android._names(Selector(text='Login', className='android.widget.Button')) == ['Login']
        assert android._names(Selector(resourceId='com.example.shop:id/sign_in')) == [
            'com.example.shop:id/sign_in', 'sign_in']
        assert android._names(Selector(descriptionContains='Log', index=2)) == ['Log']
        assert android._xpath_names('//*[@text="登录"]/..//*[@resource-id=\'x:id/y\']') == ['登录', 'x:id/y']

    def test_the_verdict(self):
        assert android.diagnose("Selector [text='Login']", ['Login'], HIERARCHY) == {
            'selector': "Selector [text='Login']", 'platform': 'android', 'names': ['Login'],
            'verdict': 'stale_selector', 'identity': {'role': 'Button', 'name': 'Login'}, 'found': 1}
        assert android.diagnose('x', ['Checkout'], HIERARCHY)['verdict'] == 'unknown'


@pytest.fixture
def on_device(monkeypatch):
    """A case in progress on the stand-in device, with its evidence slot open."""
    assert android.install()
    _d = FakeDevice()
    recorder.begin('t::case')
    android.begin(_d, _d.serial, PACKAGE, 't::case')
    yield _d
    android.end()
    recorder.end('t::case')


class TestWhereASelectorFindsNothing:

    def test_it_is_diagnosed_and_still_raises(self, on_device):
        from uiautomator2.exceptions import UiObjectNotFoundError
        with pytest.raises(UiObjectNotFoundError):
            on_device(text='Login').click()
        _f = recorder.current().locator_failures
        assert [(_x['verdict'], _x['identity']) for _x in _f] == [('stale_selector', {'role': 'Button', 'name': 'Login'})]
        assert 'Login' in _f[0]['selector']

    def test_a_widget_that_is_there_is_not_a_failure(self, on_device):
        assert on_device(text='Welcome').exists and on_device(text='Welcome').wait()
        assert recorder.current().locator_failures == []

    def test_waiting_for_something_to_go_is_not_a_missing_widget(self, on_device):
        from uiautomator2.exceptions import UiObjectNotFoundError
        with pytest.raises(UiObjectNotFoundError):
            on_device(text='Welcome').must_wait(exists=False)       # it is still there: uiautomator2 raises
        assert recorder.current().locator_failures == []           # but nothing was missing

    def test_xpath(self, on_device, monkeypatch):
        from uiautomator2 import xpath
        from uiautomator2.exceptions import XPathElementNotFoundError
        _cls = getattr(xpath, 'DeviceXPathSelector', None) or xpath.XPathSelector
        _s = _cls.__new__(_cls)
        _s._base_xpath = '//*[@text="Checkout"]'
        monkeypatch.setattr(_cls, 'wait', lambda self, timeout=None: False)
        monkeypatch.setattr(_cls, '_global_timeout', 0.01, raising=False)
        with pytest.raises(XPathElementNotFoundError):
            _s.get(timeout=0.01)
        assert [(_x['verdict'], _x['names']) for _x in recorder.current().locator_failures] == [('unknown', ['Checkout'])]

    def test_outside_a_case_nothing_is_recorded(self):
        assert android.install()
        _d = FakeDevice()
        from uiautomator2.exceptions import UiObjectNotFoundError
        with pytest.raises(UiObjectNotFoundError):
            _d(text='Login').click()

    def test_uninstall_restores_uiautomator2(self):
        from uiautomator2 import _selector
        assert android.install()
        _patched = _selector.UiObject.must_wait
        android.uninstall()
        try:
            assert _selector.UiObject.must_wait is not _patched
            assert android._originals == []
        finally:
            android.install()


class TestTheEvidence:

    def test_screenshot_tree_and_the_apps_log(self, on_device, tmp_path, monkeypatch):
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        on_device.log = CRASH_LOG
        _out = android.keep_evidence('t::case')
        assert [_a['kind'] for _a in _out] == ['screenshot', 'hierarchy', 'device-log']
        assert all(os.path.isfile(_a['path']) and _a['path'].startswith(str(tmp_path)) for _a in _out)
        _log = _out[2]['text']
        assert 'OtherApp' not in _log and 'FATAL EXCEPTION' in _log and 'sk-live-should-not-leak' not in _log
        assert ('shell', ('logcat', '-d', '-v', 'threadtime', '-b', 'main,system,crash', '-T', '1762516800.000')) \
            in on_device.calls
        _evidence = recorder.current()
        assert _evidence.app_events == [{'kind': 'crash', 'package': PACKAGE,
                                         'detail': 'java.lang.NullPointerException: cart was null'}]
        assert [_a['kind'] for _a in _evidence.artifacts] == ['screenshot', 'hierarchy', 'device-log']

    def test_each_piece_on_its_own(self, on_device, tmp_path, monkeypatch):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        on_device.fail_screenshot = True
        assert [_a['kind'] for _a in android.keep_evidence('t::case')] == ['hierarchy', 'device-log']

    def test_no_case_on_a_device_no_evidence(self):
        assert android.keep_evidence('t::nothing') == []


class TestTheVerdict:

    def test_a_crash_is_a_product_defect_whatever_failed_after(self):
        _f = classify('t', 'failed', 'UiObjectNotFoundError: Selector [text=Pay]',
                      locator_failures=[{'selector': 'Selector [text=Pay]', 'platform': 'android', 'verdict': 'unknown'}],
                      app_events=[{'kind': 'crash', 'package': PACKAGE, 'detail': 'java.lang.NullPointerException'}])
        assert (_f.category, _f.confidence) == ('defect', 'high')
        assert _f.reason.startswith('App 崩溃：com.example.shop（java.lang.NullPointerException）')
        _anr = classify('t', 'failed', 'x', app_events=[{'kind': 'anr', 'package': PACKAGE, 'detail': ''}])
        assert _anr.reason.startswith('App 无响应（ANR）：com.example.shop。')

    def test_a_selector_with_a_widget_of_that_name_on_screen_is_the_tests(self):
        _f = classify('t', 'failed', "UiObjectNotFoundError: Selector [text='Login']", locator_failures=[
            {'selector': "Selector [text='Login']", 'platform': 'android', 'verdict': 'stale_selector',
             'identity': {'role': 'Button', 'name': 'Login'}}])
        assert (_f.category, _f.confidence) == ('harness', 'medium') and '同名控件 Button "Login"' in _f.reason

    def test_none_of_that_name_is_to_be_confirmed(self):
        _f = classify('t', 'failed', "UiObjectNotFoundError: Selector [text='Gone']", locator_failures=[
            {'selector': "Selector [text='Gone']", 'platform': 'android', 'verdict': 'unknown'}])
        assert (_f.category, _f.confidence) == ('unknown', 'low') and _f.reason.startswith('待确认') and '控件树' in _f.reason

    def test_a_skip_is_not_blamed_on_a_crash(self):
        assert classify('t', 'skipped', 'no device', app_events=[{'kind': 'crash', 'package': 'p'}]).category != 'defect'


SUITE = '''
import pytest


def test_the_app_is_there(android):
    assert android(text='Welcome').exists


def test_a_stale_selector(android):
    android(text='Login').click()


def test_a_widget_gone(android):
    android(text='Checkout').click()


def test_the_app_crashed(android):
    from test.testandroid.fake_device import CRASH_LOG
    android.log = CRASH_LOG
    android(text='Pay').click()
'''

CONFTEST = '''
import pytest
import uiautomator2

from test.testandroid.fake_device import FakeDevice

uiautomator2.connect = lambda serial=None: FakeDevice(serial or 'emulator-5554')
'''


class TestARun:

    @pytest.fixture
    def suite(self, tmp_path, monkeypatch):
        import uiautomator2
        from ipandora.core.schedule import config
        from ipandora.core.schedule.runtime import Runtime
        _app = tmp_path / 'shop.apk'
        _app.write_bytes(b'PK')
        monkeypatch.setattr(Runtime, 'settings', config.deep_merge(Runtime.settings, {'android': {
            'serial': 'emulator-5554', 'package': PACKAGE, 'app_path': str(_app), 'clear_data': True}}))
        monkeypatch.setenv('IPANDORA_LOCK_DIR', str(tmp_path / 'locks'))
        monkeypatch.setattr(uiautomator2, 'connect', uiautomator2.connect)      # restored after the run
        _s = tmp_path / 'suite'
        _s.mkdir()
        (_s / 'test_shop.py').write_text(textwrap.dedent(SUITE), encoding='utf-8')
        (_s / 'conftest.py').write_text(textwrap.dedent(CONFTEST), encoding='utf-8')
        return _s

    def test_the_lifecycle_the_evidence_and_the_verdicts(self, suite, tmp_path):
        from ipandora.core.runner import run
        from test.testandroid import fake_device
        del fake_device.DEVICES[:]
        from ipandora.core.runner.plugin import ResourceLock, lock_path
        from ipandora.core.triage import triage
        _result = run(str(suite), persist=False, quiet=True, baseline='')
        _by = {_c.nodeid.split('::')[-1]: _c for _c in _result.cases}
        assert _by['test_the_app_is_there'].outcome == 'passed', _by['test_the_app_is_there'].message
        _verdicts = {_f.nodeid.split('::')[-1]: (_f.category, _f.confidence) for _f in triage(_result).findings}
        assert _verdicts == {'test_a_stale_selector': ('harness', 'medium'), 'test_a_widget_gone': ('unknown', 'low'),
                             'test_the_app_crashed': ('defect', 'high')}
        assert {_a['kind'] for _a in _by['test_a_widget_gone'].artifacts} >= {'screenshot', 'hierarchy', 'device-log'}
        assert _by['test_the_app_crashed'].app_events[0]['detail'] == 'java.lang.NullPointerException: cart was null'
        assert _by['test_the_app_is_there'].artifacts == []           # no failure, no evidence taken
        # one connection for the session, the app installed once; cleared, started and stopped around every case
        assert len(fake_device.DEVICES) == 1
        _calls = [_c for _c in fake_device.DEVICES[0].calls if _c[0] != 'shell']
        assert _calls[0] == ('install', str(tmp_path / 'shop.apk'))
        assert _calls[1:] == [('clear', PACKAGE), ('start', PACKAGE, True), ('stop', PACKAGE)] * 4
        # the device was held for each case, and is free again
        _lock = ResourceLock(lock_path('device:emulator-5554'))
        assert _lock.acquire(0.1)
        _lock.release()


def test_the_fixtures_do_not_take_names_other_plugins_use():
    # pytest-playwright's session fixture `device` (browser emulation): taking the name broke every web case
    _names = {_n for _n in vars(android.Fixtures) if not _n.startswith('_')}
    assert _names == {'android', 'android_device'}
    try:
        import pytest_playwright.pytest_playwright as _pw
    except ImportError:
        return
    assert not _names & {_n for _n in vars(_pw) if not _n.startswith('_')}

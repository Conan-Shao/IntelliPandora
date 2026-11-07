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
import re
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

    def test_a_crash_is_kept_however_much_the_app_logs_after_it(self):
        # CI: after `am crash` the restarted app and the system's notes about it
        # filled the last 300 lines and the FATAL EXCEPTION was gone from the report
        _before = ['11-07 12:00:00.{:03d}  4242  4242 I Shop: before {}'.format(_i % 1000, _i) for _i in range(50)]
        _crash = [_l for _l in CRASH_LOG.splitlines() if 'AndroidRuntime' in _l]
        _after = ['11-07 12:00:03.000  5000  5000 W Shop: after {}'.format(_i) for _i in range(1000)]
        _kept = android.relevant('\n'.join(_before + _crash + _after), PACKAGE, ['4242', '5000']).splitlines()
        assert len(_kept) == android.LOG_LINES
        assert _kept[:len(_crash)] == _crash                         # in order: the crash before what followed
        assert _kept[-1].endswith('after 999') and _kept[len(_crash)].endswith(
            'after {}'.format(1000 - (android.LOG_LINES - len(_crash))))
        assert not any('before' in _l for _l in _kept)

    def test_crash_lines_beyond_the_limit_keep_the_first(self):
        _crashes = ['11-07 12:00:02.000  4242  4242 E AndroidRuntime: frame {}'.format(_i) for _i in range(400)]
        _kept = android.relevant('\n'.join(_crashes), PACKAGE, ['4242']).splitlines()
        assert _kept == _crashes[:android.LOG_LINES]


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


class TestWhatMutationTestingFound:
    """Pinned after mutation testing of core/android.py."""

    def test_the_config_is_checked(self, monkeypatch):
        from ipandora.core.schedule.runtime import Runtime
        for _bad, _error in (('emulator-5554', 'is a mapping'), ({'serail': 'x'}, r'unknown key\(s\) serail$'),
                             ({'serial': 'x', 'apk': 'a', 'bogus': 1}, r'unknown key\(s\) apk, bogus$')):
            monkeypatch.setattr(Runtime, 'settings', {'android': _bad})
            with pytest.raises(ValueError, match=_error):
                android.settings()
        _all = {'serial': 's', 'package': 'p', 'app_path': 'a', 'clear_data': True, 'keep_app': True}
        monkeypatch.setattr(Runtime, 'settings', {'android': _all})
        assert android.settings() == _all
        monkeypatch.setattr(Runtime, 'settings', {})
        assert android.settings() == {}

    def test_the_session_and_the_shell(self):
        _d = FakeDevice('dev-9')
        _s = android.begin(_d, 'dev-9', PACKAGE, 't::n')
        try:
            assert (_s.serial, _s.package, _s.nodeid, _s.since, _s.pids) == ('dev-9', PACKAGE, 't::n', '1762516800.000',
                                                                             ['4242'])
            assert ('shell', ('date', '+%s')) in _d.calls and ('shell', ('pidof', PACKAGE)) in _d.calls
            assert android.current() is _s
        finally:
            android.end()
        assert android.current() is None and not android.active()

        class _Plain:
            def shell(self, args, timeout=None):
                self.timeout = timeout
                return 'out'
        _p = _Plain()
        assert android._shell(_p, ['x']) == 'out' and _p.timeout == 30
        assert android._shell(_p, ['x'], timeout=5) == 'out' and _p.timeout == 5

    def test_a_device_without_a_clock_or_package(self):
        class _Silent(FakeDevice):
            def shell(self, args, timeout=60):
                raise RuntimeError('offline')
        assert android._device_time(_Silent()) == '' and android._pids(_Silent(), PACKAGE) == []
        assert android._pids(FakeDevice(), '') == []

    def test_the_artifacts_exactly(self, on_device, tmp_path, monkeypatch):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        _out = android.keep_evidence('tests/test_shop.py::test_pay[a b]')
        assert [(_a['kind'], _a['group']) for _a in _out] == [('screenshot', 'emulator-5554'),
                                                               ('hierarchy', 'emulator-5554'), ('device-log', PACKAGE)]
        _name = os.path.basename(_out[0]['path'])
        assert re.match(r'^tests_test_shop\.py_test_pay_a_b_-\d{13}\.png$', _name), _name
        assert open(_out[1]['path'], encoding='utf-8').read() == HIERARCHY
        _text = open(_out[2]['path'], encoding='utf-8').read()
        assert _text == _out[2]['text'] + '\n' and 'onCreate' in _text

    def test_without_a_package_the_log_belongs_to_the_device(self, tmp_path, monkeypatch):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        _d = FakeDevice()
        _d.log = CRASH_LOG
        recorder.begin('t::p')
        android.begin(_d, _d.serial, '', 't::p')
        try:
            _out = android.keep_evidence('t::p')
            assert _out[-1]['group'] == 'emulator-5554' and recorder.current().app_events == []
        finally:
            android.end()
            recorder.end('t::p')

    def test_no_device_time_reads_the_whole_log_and_a_restarted_app_is_followed(self, on_device, tmp_path, monkeypatch):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        android.current().since = ''
        android.current().pids = []                 # started before the app had a process
        on_device.log = APP_LOG + '11-07 12:00:09.000  4242  4242 I Shop: after restart\n'
        _out = android.keep_evidence('t::case')
        _logcat = [_c for _c in on_device.calls if _c[:2] == ('shell', ('logcat', '-d', '-v', 'threadtime', '-b',
                                                                        'main,system,crash'))]
        assert _logcat and '-T' not in _logcat[-1][1]
        assert 'after restart' in _out[-1]['text']          # the pid read again at the failure

    def test_the_default_directory(self, monkeypatch, tmp_path):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.delenv(ARTIFACTS_VAR, raising=False)
        monkeypatch.setattr(android.tempfile, 'gettempdir', lambda: str(tmp_path))
        assert android._artifacts_dir() == os.path.join(str(tmp_path), 'ipandora-android')
        assert os.path.isdir(os.path.join(str(tmp_path), 'ipandora-android'))
        assert android._slug('x' * 150 + '/y') == 'x' * 98 + '_y'

    def test_the_crash_window(self):
        _far = CRASH_LOG.replace(
            '11-07 12:00:02.000  4242  4242 E AndroidRuntime: Process: com.example.shop, PID: 4242\n',
            ''.join('11-07 12:00:02.000  4242  4242 E AndroidRuntime: filler {}\n'.format(_i) for _i in range(5))
            + '11-07 12:00:02.000  4242  4242 E AndroidRuntime: Process: com.example.shop, PID: 4242\n')
        assert android.app_events(_far, PACKAGE) == []          # a Process line 6 lines on belongs to another block
        _before = ('11-07 12:00:02.000  4242  4242 E AndroidRuntime: Process: com.example.shop, PID: 4242\n'
                   '11-07 12:00:02.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main\n')
        assert android.app_events(_before, PACKAGE) == []        # the Process line comes after FATAL, not before
        _bare = ('11-07 12:00:02.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main\n'
                 '11-07 12:00:02.000  4242  4242 E AndroidRuntime: Process: com.example.shop, PID: 4242\n')
        assert android.app_events(_bare, PACKAGE) == [{'kind': 'crash', 'package': PACKAGE, 'detail': ''}]

    def test_the_anr_reason(self):
        _head = '11-07 12:00:05.000  500  520 E ActivityManager: ANR in com.example.shop:remote\n'
        _r = '11-07 12:00:05.000  500  520 E ActivityManager: Reason: Input dispatching timed out (Reason: x)\n'
        _pid = '11-07 12:00:05.000  500  520 E ActivityManager: PID: 4242\n'
        assert android.app_events(_head + _r, PACKAGE)[0]['detail'] == 'Input dispatching timed out (Reason: x)'
        assert android.app_events(_head + _pid * 2 + _r, PACKAGE)[0]['detail'] == 'Input dispatching timed out (Reason: x)'
        assert android.app_events(_head + _pid * 3 + _r, PACKAGE)[0]['detail'] == ''       # too far to be its reason
        assert android.app_events(_r + _head, PACKAGE)[0]['detail'] == ''                 # a reason before it is not its
        assert android.app_events(_head, PACKAGE) == [{'kind': 'anr', 'package': PACKAGE, 'detail': ''}]

    def test_the_lines_kept(self):
        _log = ('11-07 12:00:01.100  4242  9999 I Shop: pid column\n'
                '11-07 12:00:01.100  9999  4242 I Shop: tid column only\n'
                '11-07 12:00:01.100  1 1 I Sys: mentions com.example.shop here\n'
                '11-07 12:00:01.100  1 1 I Sys: ANR in com.other\n'
                '11-07 12:00:01.100  1 1 I androidruntime: lower case is not the crash tag\n'
                'short line\n'
                '4242\n')
        _kept = android.relevant(_log, PACKAGE, ['4242'])
        assert _kept.splitlines() == ['11-07 12:00:01.100  4242  9999 I Shop: pid column',
                                      '11-07 12:00:01.100  1 1 I Sys: mentions com.example.shop here',
                                      '11-07 12:00:01.100  1 1 I Sys: ANR in com.other']
        assert android.relevant(_log, '', []) .splitlines() == ['11-07 12:00:01.100  1 1 I Sys: ANR in com.other']
        assert android._message('not a threadtime line') == 'not a threadtime line'

    def test_the_tree_in_detail(self):
        _xml = ('<hierarchy><node class="a.b.c.Button" text="" content-desc="" resource-id="p:id/x:id/y"/>'
                '<node class="Plain" text="Pay" content-desc="" resource-id=""/></hierarchy>')
        assert android.same_name(_xml, ['x:id/y']) == [{'role': 'Button', 'name': 'x:id/y', 'attribute': 'resource-id'}]
        assert android.same_name(_xml, ['pay']) == [{'role': 'Plain', 'name': 'Pay', 'attribute': 'text'}]
        assert android.same_name(_xml, []) == [] and android.same_name('', ['Pay']) == []
        assert android.same_name('<hierarchy><text>Pay</text></hierarchy>', ['Pay']) == []
        assert android._names({'resourceId': 'a:id/b:id/c'}) == ['a:id/b:id/c', 'b:id/c']
        assert android._names({'resourceId': 'plain_id', 'text': '  '}) == ['plain_id']
        assert android._names('not a selector') == []

    def test_a_case_without_evidence_slot_records_nothing(self):
        assert android.install()
        _d = FakeDevice()
        android.begin(_d, _d.serial, PACKAGE, 't::x')
        try:
            from uiautomator2.exceptions import UiObjectNotFoundError
            with pytest.raises(UiObjectNotFoundError):
                _d(text='Login').click()
            assert recorder.current() is None
        finally:
            android.end()

    def test_the_timeouts_reach_uiautomator2(self, on_device, monkeypatch):
        from uiautomator2 import _selector, xpath
        _seen = []
        monkeypatch.setattr(_selector.UiObject, 'wait', lambda self, exists=True, timeout=None: _seen.append(
            ('wait', exists, timeout)) or True)
        on_device(text='Welcome').must_wait(timeout=7)
        on_device(text='Welcome').must_wait(exists=False, timeout=3)
        assert _seen == [('wait', True, 7), ('wait', False, 3)]
        _cls = getattr(xpath, 'DeviceXPathSelector', None) or xpath.XPathSelector
        _s = _cls.__new__(_cls)
        monkeypatch.setattr(_cls, 'wait', lambda self, timeout=None: _seen.append(('xwait', timeout)) or True)
        monkeypatch.setattr(_cls, 'get_last_match', lambda self: 'el', raising=False)
        assert _s.get(timeout=4) == 'el' and _seen[-1] == ('xwait', 4)

    def test_an_xpath_without_its_text_is_named_by_itself(self, on_device, monkeypatch):
        from uiautomator2 import xpath
        from uiautomator2.exceptions import XPathElementNotFoundError
        _cls = getattr(xpath, 'DeviceXPathSelector', None) or xpath.XPathSelector
        _s = _cls.__new__(_cls)
        _s._base_xpath = ''
        monkeypatch.setattr(_cls, 'wait', lambda self, timeout=None: False)
        monkeypatch.setattr(_cls, '__str__', lambda self: '//*[@text="Pay"]', raising=False)
        with pytest.raises(XPathElementNotFoundError):
            _s.get(timeout=0.01)
        _f = recorder.current().locator_failures[-1]
        assert (_f['selector'], _f['names']) == ('//*[@text="Pay"]', ['Pay'])

    def test_another_apps_crash_before_ours_does_not_hide_it(self):
        _other = CRASH_LOG.replace('Process: com.example.shop', 'Process: com.other.app')
        assert [_e['detail'] for _e in android.app_events(_other + CRASH_LOG, PACKAGE)] == [
            'java.lang.NullPointerException: cart was null']

    def test_more_lines_kept(self):
        _log = ('a b 4242\n'
                '11-07 12:00:01.100  1 1 E AndroidRuntime: system_server crashed\n')
        assert android.relevant(_log, PACKAGE, ['4242']).splitlines() == _log.splitlines()

    def test_the_log_is_read_with_a_time_limit_and_names_the_app(self, on_device, tmp_path, monkeypatch):
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        monkeypatch.setenv(ARTIFACTS_VAR, str(tmp_path))
        on_device.log = '11-07 12:00:01.100  1 1 I Sys: Start proc com.example.shop\n'
        _out = android.keep_evidence('t::case')
        _i = next(_n for _n, _c in enumerate(on_device.calls) if _c[1][0] == 'logcat')
        assert on_device.timeouts[_i] == 60 and 'Start proc com.example.shop' in _out[-1]['text']

    def test_a_tree_that_cannot_be_read_is_unknown(self, on_device):
        from uiautomator2.exceptions import UiObjectNotFoundError

        def _broken(*args, **kwargs):
            raise RuntimeError('uiautomator died')
        on_device.dump_hierarchy = _broken
        with pytest.raises(UiObjectNotFoundError):
            on_device(text='Login').click()
        assert recorder.current().locator_failures[-1]['verdict'] == 'unknown'

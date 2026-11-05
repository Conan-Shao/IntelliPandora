# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_web.py
@Time  : 2026-11-05

Web automation: Playwright and pytest-playwright as they are, plus what a
verdict layer needs from them. Acceptance from docs/design/14 §3:

- a case written only with expect() is not unverified;
- a failure's screenshot is in the report and its trace opens;
- a stale selector (the element is still on the page) is the test's problem;
  an element that is really gone is "待确认", with the screenshot;
- serial and --workers 4 give the same answer.

Every suite here runs through run() against pages served by a local HTTP
server, so nothing depends on the network. The public-site example is in
examples/web/ and runs only when asked (see TestPublicSite).
"""
import json
import os
import textwrap
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ipandora.core import web
from ipandora.core.report import build
from ipandora.core.report.render import to_html
from ipandora.core.runner import inventory, run
from ipandora.core.triage import triage

pytest.importorskip('playwright', reason='web tests need the `web` extra')
pytest.importorskip('pytest_playwright', reason='web tests need the `web` extra')


def _browser_or_skip():
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as _p:
            _p.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        _why = 'no browser for the locked Playwright: python -m playwright install chromium ({})'.format(
            str(exc).splitlines()[0][:120])
        if os.environ.get('IPANDORA_REQUIRE_BROWSER'):
            pytest.fail(_why)           # CI: quietly skipping would test nothing
        pytest.skip(_why)


@pytest.fixture(scope='module', autouse=True)
def browser_available():
    _browser_or_skip()


class Site:
    """Pages under a temp dir, served over HTTP so base_url and goto('/x') work."""

    def __init__(self, root):
        self.root = root
        _handler = partial(_Quiet, directory=str(root))
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), _handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:{}'.format(self._server.server_address[1])

    def page(self, name, body):
        (self.root / name).write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head><body>{}</body></html>'.format(
                body), encoding='utf-8')

    def close(self):
        self._server.shutdown()
        self._server.server_close()


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def site(tmp_path):
    (tmp_path / 'www').mkdir()
    _site = Site(tmp_path / 'www')
    yield _site
    _site.close()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'home' / 'runs'))
    monkeypatch.setenv(web.MEMORY_VAR, str(tmp_path / 'home' / 'locators.json'))


def suite(tmp_path, body, name='test_web_suite.py'):
    _dir = tmp_path / 'suite'
    _dir.mkdir(exist_ok=True)
    _file = _dir / name
    _file.write_text(textwrap.dedent(body), encoding='utf-8')
    return str(_file)


def go(target, **kwargs):
    kwargs.setdefault('persist', False)
    kwargs.setdefault('quiet', True)
    kwargs.setdefault('baseline', '')
    return run(target, **kwargs)


CHECKOUT = '''
    import os
    from playwright.sync_api import expect

    URL = os.environ['SITE']

    def test_checkout(page):
        """pay and see the amount"""
        page.set_default_timeout(3000)
        page.goto(URL + '/checkout.html')
        page.locator('#pay').click()
        expect(page.locator('#amount')).to_have_text('100.50')
        expect(page).to_have_title('结算')
'''

CHECKOUT_PAGE = '<title>结算</title><button id="pay">付款</button><span id="amount">100.50</span>'


class TestExpectIsAJudgement:

    def test_a_case_written_only_with_expect_is_not_unverified(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE)
        _result = go(suite(tmp_path, CHECKOUT))
        _case = _result.cases[0]
        assert _case.outcome == 'passed', _case.message
        assert not _case.unverified
        assert [(_c['claim'], _c['ok']) for _c in _case.checks] == [
            ("expect locator('#amount') to_have_text '100.50'", True),
            ("expect page to_have_title '结算'", True)]

    def test_a_failed_expect_is_a_failed_judgement_with_playwrights_message(
            self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE.replace('100.50', '99.00'))
        _case = go(suite(tmp_path, CHECKOUT)).cases[0]
        assert _case.outcome == 'failed'
        _failed = [_c for _c in _case.checks if not _c['ok']]
        assert _failed[0]['claim'] == "expect locator('#amount') to_have_text '100.50'"
        assert '99.00' in _failed[0]['expr']
        # one failed judgement, not a second generic "assert (failed)" for it
        assert len(_failed) == 1

    def test_the_inventory_sees_a_changed_expectation(self, site, tmp_path, monkeypatch):
        # expect() claims are stable, so a weakened web test shows in the baseline diff
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE)
        _before = go(suite(tmp_path, CHECKOUT))
        _after = go(suite(tmp_path, CHECKOUT.replace("to_have_text('100.50')",
                                                     "to_contain_text('100')")))
        _changes = inventory.compare(inventory.build(_before), _after)
        assert any(_f.weakening for _f in _changes), _changes


class TestFailureEvidence:

    def test_the_screenshot_is_in_the_report_and_the_trace_opens(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE.replace('100.50', '0'))
        _result = go(suite(tmp_path, CHECKOUT))
        _case = _result.cases[0]
        _kinds = {_a['kind']: _a['path'] for _a in _case.artifacts}
        assert set(_kinds) >= {'screenshot', 'trace'}
        with open(_kinds['screenshot'], 'rb') as _f:
            assert _f.read(8) == b'\x89PNG\r\n\x1a\n'
        with zipfile.ZipFile(_kinds['trace']) as _z:       # what show-trace opens
            assert any(_n.endswith('.trace') for _n in _z.namelist())
        # each run has its own folder: pytest-playwright empties its output
        # folder per session, which would break the archived report's links
        assert _result.run_id in _kinds['trace']

        _html = to_html(build(_result))
        assert 'data:image/png;base64,' in _html
        assert 'playwright show-trace' in _html and _kinds['trace'] in _html

    def test_a_passing_case_leaves_nothing_behind(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE)
        assert go(suite(tmp_path, CHECKOUT)).cases[0].artifacts == []


class TestSelectorOrProduct:
    """Is a selector that finds nothing stale, or is the element really gone?"""

    def _remember(self, site, tmp_path):
        site.page('checkout.html', CHECKOUT_PAGE)
        _first = go(suite(tmp_path, CHECKOUT))
        assert _first.ok
        assert web.remembered(_first.cases[0].nodeid, '#pay') == {'role': 'button', 'name': '付款'}
        return _first

    def test_a_stale_selector_is_the_tests_problem(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        self._remember(site, tmp_path)
        # same button, new markup
        site.page('checkout.html', CHECKOUT_PAGE.replace('id="pay"', 'id="pay-button"'))
        _result = go(suite(tmp_path, CHECKOUT))
        _finding = triage(_result).findings[0]
        assert _result.cases[0].locator_failures[0]['verdict'] == web.STALE
        assert _finding.category == 'harness' and _finding.confidence == 'high'
        assert "'#pay' is stale" in _finding.reason and 'button "付款"' in _finding.reason

    def test_an_element_that_is_gone_is_to_be_confirmed_with_a_screenshot(
            self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        self._remember(site, tmp_path)
        # the button is gone: a regression, not a selector problem
        site.page('checkout.html', CHECKOUT_PAGE.replace('<button id="pay">付款</button>', ''))
        _result = go(suite(tmp_path, CHECKOUT))
        _case = _result.cases[0]
        _finding = triage(_result).findings[0]
        assert _case.locator_failures[0]['verdict'] == web.MISSING
        assert _finding.category == 'defect' and _finding.confidence == 'low'
        assert _finding.reason.startswith('待确认')
        assert _finding.blames_system_under_test           # never "not the product's problem"
        assert any(_a['kind'] == 'screenshot' for _a in _case.artifacts)

    def test_with_nothing_remembered_it_is_to_be_confirmed_not_blamed_on_the_test(
            self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE.replace('id="pay"', 'id="pay-button"'))
        _result = go(suite(tmp_path, CHECKOUT))
        _finding = triage(_result).findings[0]
        assert _result.cases[0].locator_failures[0]['verdict'] == web.UNKNOWN
        assert _finding.category == 'unknown' and _finding.reason.startswith('待确认')

    def test_an_element_present_but_in_the_wrong_state_is_not_a_locator_problem(
            self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE.replace('100.50', '1'))
        _result = go(suite(tmp_path, CHECKOUT))
        assert _result.cases[0].locator_failures == []
        assert triage(_result).findings[0].category == 'defect'

    def test_a_failing_case_does_not_overwrite_what_was_remembered(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        _first = self._remember(site, tmp_path)
        site.page('checkout.html', '<title>结算</title><button id="pay">取消</button>'
                                   '<span id="amount">0</span>')
        go(suite(tmp_path, CHECKOUT))
        assert web.remembered(_first.cases[0].nodeid, '#pay') == {'role': 'button', 'name': '付款'}


class TestSerialAndParallel:

    def test_four_workers_give_the_same_answer(self, site, tmp_path, monkeypatch):
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE)
        site.page('broken.html', '<title>x</title><span id="amount">0</span>')
        _target = suite(tmp_path, CHECKOUT + '''

    import pytest

    @pytest.mark.parametrize('n', range(4))
    def test_more(page, n):
        page.set_default_timeout(3000)
        page.goto(URL + '/checkout.html')
        expect(page.locator('#pay')).to_be_visible()

    def test_broken(page):
        page.set_default_timeout(1000)
        page.goto(URL + '/broken.html')
        expect(page.locator('#amount')).to_have_text('100.50')
''')
        _serial = go(_target)
        _parallel = go(_target, workers=4)
        assert [(_c.nodeid, _c.outcome) for _c in _parallel.cases] == \
            [(_c.nodeid, _c.outcome) for _c in _serial.cases]
        assert json.dumps(inventory.build(_parallel), sort_keys=True) == \
            json.dumps(inventory.build(_serial), sort_keys=True)
        # evidence comes back from the workers too
        _broken = [_c for _c in _parallel.cases if _c.name.startswith('test_broken')][0]
        assert {_a['kind'] for _a in _broken.artifacts} >= {'screenshot', 'trace'}


class TestConfig:

    def test_base_url_and_viewport_come_from_the_env_config(self, site, tmp_path, monkeypatch):
        _conf = tmp_path / 'conf'
        _conf.mkdir()
        (_conf / 'staging.yaml').write_text(
            'web:\n  base_url: {}\n  viewport: {{width: 800, height: 600}}\n'.format(site.url),
            encoding='utf-8')
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        site.page('orders.html', '<title>订单</title>')
        _target = suite(tmp_path, '''
            from playwright.sync_api import expect
            def test_orders(page):
                page.goto('/orders.html')                 # relative: base_url applied
                expect(page).to_have_title('订单')
                assert page.viewport_size == {'width': 800, 'height': 600}
        ''')
        for _workers in (None, 2):        # workers overlay the env config themselves
            _result = go(_target, env='staging', workers=_workers)
            assert _result.ok, [(_c.outcome, _c.message) for _c in _result.cases]

    def test_a_suites_own_conftest_still_wins(self, site, tmp_path, monkeypatch):
        _conf = tmp_path / 'conf'
        _conf.mkdir()
        (_conf / 'config.yaml').write_text('web:\n  viewport: {width: 800, height: 600}\n',
                                           encoding='utf-8')
        monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(_conf))
        suite(tmp_path, '''
            import pytest
            @pytest.fixture(scope='session')
            def browser_context_args(browser_context_args):
                return {**browser_context_args, 'viewport': {'width': 400, 'height': 300}}
        ''', name='conftest.py')
        _target = suite(tmp_path, '''
            def test_size(page):
                assert page.viewport_size == {'width': 400, 'height': 300}
        ''')
        _result = go(_target)
        assert _result.ok, [(_c.outcome, _c.message) for _c in _result.cases]

    def test_options_the_caller_passed_are_not_overridden(self):
        assert '--screenshot' not in web.pytest_args(['--screenshot', 'on'])[0::2]
        assert '--output' not in web.pytest_args(['--output', 'x'], 'y')[0::2]


class TestThePluginWeDependOn:
    """pytest-playwright is 0.x: the parts this framework relies on, pinned."""

    def test_the_fixtures_and_options_exist(self, tmp_path):
        _target = suite(tmp_path, '''
            def test_contract(pytestconfig, page, context, browser, browser_context_args, base_url):
                for _opt in ('--screenshot', '--tracing', '--output', '--base-url', '--browser'):
                    pytestconfig.getoption(_opt)
                assert isinstance(browser_context_args, dict)
                assert page.context is context
        ''')
        _result = go(_target)
        assert _result.ok, [(_c.outcome, _c.message) for _c in _result.cases]

    def test_artifacts_are_still_reported_on_the_teardown_report(self):
        # the channel the collector reads: playwright_<kind> user_properties
        import inspect
        import pytest_playwright.pytest_playwright as _pp
        assert 'f"playwright_{kind}"' in inspect.getsource(_pp._attach_artifacts_to_report)


class TestInsideAnotherSession:

    def test_run_works_from_inside_a_test_with_pytest_playwright_loaded(self, site, tmp_path,
                                                                       monkeypatch):
        # this test is itself running under pytest-playwright's soft-assertion
        # scope, which does not nest
        monkeypatch.setenv('SITE', site.url)
        site.page('checkout.html', CHECKOUT_PAGE)
        assert go(suite(tmp_path, CHECKOUT)).ok


@pytest.mark.skipif(not os.environ.get('IPANDORA_PUBLIC_SITE'),
                    reason='hits https://demo.playwright.dev; set IPANDORA_PUBLIC_SITE=1')
class TestPublicSite:

    EXAMPLE = os.path.join(os.path.dirname(__file__), '..', '..', 'examples', 'web')

    @pytest.mark.parametrize('workers', [None, 4])
    def test_the_example_suite_passes(self, workers):
        _result = go(os.path.abspath(self.EXAMPLE), workers=workers)
        assert _result.ok, [(_c.name, _c.outcome, _c.message) for _c in _result.cases]
        assert not _result.unverified

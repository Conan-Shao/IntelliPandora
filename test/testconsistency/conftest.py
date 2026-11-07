# -*- coding: utf-8 -*-
"""
The checker tests need Java 21 and elle-cli (ELLE_CLI_JAR); CI provides both
and sets IPANDORA_REQUIRE_CHECKER, which turns a skip into a failure.
"""
import os

import pytest

from ipandora.core import consistency


def checker_or_skip():
    try:
        return consistency.checker()
    except BaseException as exc:          # require() skips via pytest's own exception
        if os.environ.get('IPANDORA_REQUIRE_CHECKER'):
            pytest.fail('the consistency checker is required here: {}'.format(exc))
        pytest.skip('no consistency checker: {}'.format(exc))


@pytest.fixture
def needs_checker():
    return checker_or_skip()


def pytest_configure(config):
    config.addinivalue_line('markers', 'expects_skip: the test checks that a missing prerequisite skips')


@pytest.fixture(autouse=True)
def no_silent_skips(request, monkeypatch):
    """
    Where the checker is required (IPANDORA_REQUIRE_CHECKER, as on CI), a
    test that reaches checker() through History.check() must not be skipped
    by its require(): a broken checker() skipped those tests and the suite
    stayed green (mutation testing found it in core/stack.py's docker()).
    The fixture above only guarded tests that ask for it by name.
    """
    if not os.environ.get('IPANDORA_REQUIRE_CHECKER') or request.node.get_closest_marker('expects_skip'):
        return
    import ipandora.core.assertion as assertion
    _real = assertion.require

    def _strict(*checks):
        _missing = [_c for _c in checks if not getattr(_c, 'ok', False)]
        if _missing:
            pytest.fail('unexpected skip: {}'.format('; '.join(_c.expr for _c in _missing)))
        return _real(*checks)
    monkeypatch.setattr(assertion, 'require', _strict)

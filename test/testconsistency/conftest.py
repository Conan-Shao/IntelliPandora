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

# -*- coding: utf-8 -*-
"""
These tests start containers: they need Docker with Compose v2.20+. CI has
both and sets IPANDORA_REQUIRE_DOCKER, which turns a skip into a failure.
"""
import os

import pytest

from ipandora.core import stack

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'compose')


def docker_or_skip():
    try:
        return stack.docker()
    except BaseException as exc:          # require() skips via pytest's own exception
        if os.environ.get('IPANDORA_REQUIRE_DOCKER'):
            pytest.fail('Docker is required here: {}'.format(exc))
        pytest.skip('no Docker: {}'.format(exc))


@pytest.fixture
def needs_docker():
    return docker_or_skip()

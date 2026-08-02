# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : conftest.py
@Time  : 2026-08-01
"""
import json

import pytest


class FakeResponse:
    """Stands in for requests.Response. No network, no mock server."""

    def __init__(self, status_code=200, body=None, headers=None, raw=None):
        self.status_code = status_code
        self.headers = headers or {'Content-Type': 'application/json'}
        if raw is not None:
            self.content = raw if isinstance(raw, bytes) else raw.encode('utf-8')
        else:
            self.content = json.dumps(body).encode('utf-8')

    @property
    def text(self):
        return self.content.decode('utf-8', errors='replace')


@pytest.fixture
def make_response():
    return FakeResponse

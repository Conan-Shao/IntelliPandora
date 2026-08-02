# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : mockprovider.py
@Time  : 2026-08-01
"""
from typing import Dict, List

from ipandora.ai.providerabc import AIProviderABC


class MockProvider(AIProviderABC):
    """
    Offline provider used as the default so the framework works without any
    API key configured, and for unit tests that must not hit a real network.
    """

    def __init__(self, response: str = 'yes', **kwargs):
        self.response = response

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self.response

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : providerabc.py
@Time  : 2026-08-01
"""
from abc import ABC, abstractmethod
from typing import Dict, List


class AIProviderABC(ABC):
    """
    Pluggable AI backend interface. Any concrete provider (Anthropic, OpenAI,
    an internal LLM gateway...) only needs to implement `chat`; callers never
    depend on a specific vendor SDK.
    """

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Send a list of {"role": ..., "content": ...} messages and return the
        model's text reply.
        :param messages:
        :param kwargs: provider-specific overrides, e.g. model/max_tokens.
        :return:
        """
        pass

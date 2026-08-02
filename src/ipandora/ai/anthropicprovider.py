# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : anthropicprovider.py
@Time  : 2026-08-01
"""
from typing import Dict, List

from ipandora.ai.providerabc import AIProviderABC
from ipandora.utils.error import AIProviderError
from ipandora.utils.log import logger


class AnthropicProvider(AIProviderABC):
    def __init__(self, api_key=None, model=None, base_url=None, timeout=None, max_tokens=None):
        self.api_key = api_key
        self.model = model or 'claude-sonnet-5'
        self.base_url = base_url
        self.timeout = timeout or 30
        self.max_tokens = max_tokens or 1024
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise AIProviderError(
                    "The 'anthropic' package is required to use AnthropicProvider. "
                    "Install it with: pip install intellipandora[ai]", details=str(e))
            self._client = anthropic.Anthropic(
                api_key=self.api_key, base_url=self.base_url or None, timeout=self.timeout)
        return self._client

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        try:
            response = self.client.messages.create(
                model=kwargs.pop('model', self.model),
                max_tokens=kwargs.pop('max_tokens', self.max_tokens),
                messages=messages,
                **kwargs)
            return ''.join(
                block.text for block in response.content if hasattr(block, 'text'))
        except AIProviderError:
            raise
        except Exception as e:
            logger.error("AnthropicProvider chat failed: {}".format(e))
            raise AIProviderError("AnthropicProvider chat failed: {}".format(e))

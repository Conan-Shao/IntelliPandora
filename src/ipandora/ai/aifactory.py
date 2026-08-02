# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : aifactory.py
@Time  : 2026-08-01
"""
from ipandora.ai.anthropicprovider import AnthropicProvider
from ipandora.ai.mockprovider import MockProvider
from ipandora.ai.providerabc import AIProviderABC


class AIProviderFactory:
    """
    Factory class for creating AI providers, mirroring CryptoFactory's shape.
    Switching backend only requires changing `ai.provider` in config.yaml.
    """

    def __init__(self):
        self._default = None

    @property
    def default(self) -> AIProviderABC:
        if not self._default:
            from ipandora.core.schedule.runtime import Runtime
            self._default = AIProviderFactory.get_provider(
                Runtime.Ai.provider,
                api_key=Runtime.Ai.api_key,
                model=Runtime.Ai.model,
                base_url=Runtime.Ai.base_url,
                timeout=Runtime.Ai.timeout,
                max_tokens=Runtime.Ai.max_tokens)
        return self._default

    @staticmethod
    def get_provider(provider, **kwargs) -> AIProviderABC:
        if provider == 'anthropic':
            return AnthropicProvider(
                api_key=kwargs.get('api_key'), model=kwargs.get('model'),
                base_url=kwargs.get('base_url'), timeout=kwargs.get('timeout'),
                max_tokens=kwargs.get('max_tokens'))
        elif provider == 'mock':
            return MockProvider()
        else:
            raise ValueError("Unsupported AI provider: {}".format(provider))

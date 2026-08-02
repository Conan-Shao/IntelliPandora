# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_ai_provider.py
@Time  : 2026-08-01
"""
import unittest
from unittest.mock import MagicMock, patch

import pytest

# `ipandora.ai` is optional and deletable by design -- `rm -rf src/ipandora/ai
# && pytest` staying green is one of the five structural guarantees in
# docs/design/03-LLM接入边界.md. Tests *of* that package cannot run once it is
# gone, but they must not break collection either, or the guarantee is
# unverifiable. This belongs here rather than in a conftest: a conftest is
# imported earlier than any test module, and pulling ipandora in that early
# binds the console log handler to a different sys.stdout than the tests see.
pytest.importorskip('ipandora.ai', reason='optional ai/ package is absent')

from ipandora.ai.aifactory import AIProviderFactory  # noqa: E402
from ipandora.ai.anthropicprovider import AnthropicProvider  # noqa: E402
from ipandora.ai.mockprovider import MockProvider  # noqa: E402
from ipandora.utils.error import AIProviderError  # noqa: E402


class TestMockProvider(unittest.TestCase):
    def test_default_response(self):
        provider = MockProvider()
        self.assertEqual(provider.chat(messages=[{'role': 'user', 'content': 'hi'}]), 'yes')

    def test_custom_response(self):
        provider = MockProvider(response='no')
        self.assertEqual(provider.chat(messages=[]), 'no')


class TestAIProviderFactory(unittest.TestCase):
    def test_get_mock_provider(self):
        provider = AIProviderFactory.get_provider('mock')
        self.assertIsInstance(provider, MockProvider)

    def test_get_anthropic_provider(self):
        provider = AIProviderFactory.get_provider(
            'anthropic', api_key='sk-test', model='claude-sonnet-5')
        self.assertIsInstance(provider, AnthropicProvider)
        self.assertEqual(provider.model, 'claude-sonnet-5')

    def test_unsupported_provider_raises(self):
        with self.assertRaises(ValueError):
            AIProviderFactory.get_provider('unknown')


class TestAnthropicProvider(unittest.TestCase):
    @patch('anthropic.Anthropic')
    def test_chat_returns_text(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.text = 'hello from claude'
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        provider = AnthropicProvider(api_key='sk-test')
        result = provider.chat(messages=[{'role': 'user', 'content': 'hi'}])
        self.assertEqual(result, 'hello from claude')

    @patch('anthropic.Anthropic')
    def test_chat_wraps_errors(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError('boom')
        mock_anthropic_cls.return_value = mock_client

        provider = AnthropicProvider(api_key='sk-test')
        with self.assertRaises(AIProviderError):
            provider.chat(messages=[{'role': 'user', 'content': 'hi'}])


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_ai_provider.py
@Time  : 2026-08-01
"""
import unittest
from unittest.mock import MagicMock, patch

from ipandora.ai.aifactory import AIProviderFactory
from ipandora.ai.anthropicprovider import AnthropicProvider
from ipandora.ai.mockprovider import MockProvider
from ipandora.utils.error import AIProviderError


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

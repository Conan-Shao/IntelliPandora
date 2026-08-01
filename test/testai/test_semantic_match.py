# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_semantic_match.py
@Time  : 2026-08-01
"""
import unittest
from unittest.mock import PropertyMock, patch

from ipandora.core.engine.ai.aifactory import AIProviderFactory
from ipandora.utils.match import Compare, DictMatcher


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer

    def chat(self, messages, **kwargs):
        return self.answer


class TestSemanticCompare(unittest.TestCase):
    @patch.object(AIProviderFactory, 'default', new_callable=PropertyMock)
    def test_cmp_semantic_true(self, mock_default):
        mock_default.return_value = FakeProvider('Yes, it matches.')
        result = Compare(a='550e8400-e29b-41d4-a716-446655440000',
                         b='looks like a valid UUID').cmp_semantic()
        self.assertTrue(result)

    @patch.object(AIProviderFactory, 'default', new_callable=PropertyMock)
    def test_cmp_semantic_false(self, mock_default):
        mock_default.return_value = FakeProvider('No, it does not.')
        result = Compare(a='not-a-uuid', b='looks like a valid UUID').cmp_semantic()
        self.assertFalse(result)

    @patch.object(AIProviderFactory, 'default', new_callable=PropertyMock)
    def test_dict_matcher_dispatches_to_semantic(self, mock_default):
        mock_default.return_value = FakeProvider('yes')
        matcher = DictMatcher(superset={'id': '550e8400-e29b-41d4-a716-446655440000'})
        matcher.condition({'id': {'$semantic': 'looks like a valid UUID'}})
        self.assertTrue(matcher.match())


if __name__ == '__main__':
    unittest.main()

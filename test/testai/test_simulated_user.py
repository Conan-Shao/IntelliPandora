# -*- coding: utf-8 -*-
"""
@File  : test_simulated_user.py
@Time  : 2026-11-06

A model playing the user (docs/design/decisions/13, E2). The model is a fake:
what is tested is what the framework sends it and how it reads the answer.
"""
import pytest

pytest.importorskip('ipandora.ai', reason='optional ai/ package is absent')

from ipandora.ai.simulated_user import STOP, ModelUser  # noqa: E402
from ipandora.core.eval import dialogue  # noqa: E402


class Fake:
    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def chat(self, messages, **kwargs):
        self.seen.append((messages, kwargs))
        return self.answers.pop(0) if self.answers else STOP


def test_the_model_plays_the_user_until_it_stops():
    _model = Fake('订单号是 A1001', '确认')
    _user = ModelUser('我要退款', persona='老人', goal='A1001 全额退款', provider=_model, label='fake')
    _r = dialogue.converse(lambda m: '请问订单号？' if len(m) == 1 else '确认退款吗？', _user, max_turns=5)
    assert _r.output['ended'] == dialogue.ENDED_BY_USER and _r.output['turns'] == 3
    assert [_e['text'] for _e in _r.trajectory if _e['role'] == 'user'] == ['我要退款', '订单号是 A1001', '确认']
    assert _user.name == 'model-user v1 (fake)'


def test_the_prompt_is_one_message_with_the_whole_conversation():
    _model = Fake('ok')
    ModelUser('hi', persona='p', goal='g', provider=_model).reply(
        [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'hello'}])
    _messages, _kwargs = _model.seen[0]
    assert len(_messages) == 1 and _messages[0]['role'] == 'user'
    assert 'You: hi\nAgent: hello' in _messages[0]['content']
    assert 'p' in _kwargs['system'] and 'g' in _kwargs['system'] and STOP in _kwargs['system']


def test_what_the_agent_said_is_redacted_before_it_reaches_the_model():
    _model = Fake('ok')
    ModelUser('hi', persona='p', goal='g', provider=_model).reply(
        [{'role': 'assistant', 'content': 'your token=abcdef0123456789secret'}])  # pragma: allowlist secret
    assert 'abcdef0123456789secret' not in _model.seen[0][0][0]['content']


def test_the_call_budget_ends_the_conversation():
    _model = Fake(*['more'] * 10)
    _user = ModelUser('hi', persona='p', goal='g', provider=_model, max_calls=2)
    _r = dialogue.converse(lambda m: 'and?', _user, max_turns=10)
    assert len(_model.seen) == 2 and _r.output['turns'] == 3 and _r.output['ended'] == dialogue.ENDED_BY_USER


def test_an_empty_answer_ends_it_too():
    assert ModelUser('hi', persona='p', goal='g', provider=Fake('  ')).reply([]) is None

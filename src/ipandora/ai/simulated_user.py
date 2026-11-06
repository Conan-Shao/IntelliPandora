# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : simulated_user.py
@Time  : 2026-11-06

A model playing the user in a multi-turn evaluation (docs/design/decisions/13
§3, E2). Optional: the scripted user in core/eval/dialogue.py is the default,
because it makes a trial reproducible; a model user finds what a script did
not think of, at the price of noise and cost.

    from ipandora.ai.simulated_user import ModelUser

    user = ModelUser(opening='我要退订单 A1001 的款',
                     persona='一位不太懂网购流程的老人，说话简短',
                     goal='订单 A1001 全额退款；不接受优惠券补偿')
    dialogue.converse(bot.respond, user, max_turns=8, state=shop.snapshot)

Put `user.name` in the run's manifest as user_simulator: a different user,
model or prompt is a different measurement. The model only plays the user --
it never judges; the conversation is graded by code, as in core.

Each user has a call budget (`max_calls`); when it is spent, the user leaves.
What the agent said is redacted before it is sent to the model, as for every
other prompt the framework builds.
"""
from typing import Any, Dict, List, Optional

from ipandora.core.eval.dialogue import User
from ipandora.core.report.redact import redact_text

STOP = '###STOP###'
"""What the model says when the user is done (τ-bench's convention)."""

PROMPT_VERSION = '1'
"""Part of the user's name in the manifest: a changed prompt is a different user."""

SYSTEM = (
    'You are role-playing a customer talking to a customer-service agent. Stay in character.\n'
    'Who you are: {persona}\n'
    'What you want: {goal}\n'
    'Rules: write only your next message to the agent, in the language of the conversation, short '
    'and natural. Give information only when the agent asks for it. Never invent facts that '
    'contradict what you want. When what you want has been done, or clearly cannot be, reply with '
    'exactly {stop} and nothing else.')


class ModelUser(User):

    def __init__(self, opening: str, persona: str, goal: str, provider=None, max_calls: int = 20,
                 label: str = ''):
        if not opening:
            raise ValueError('a model user needs an opening line')
        self._opening, self.persona, self.goal = opening, persona, goal
        self._provider = provider
        self.max_calls, self.calls = max_calls, 0
        self.name = 'model-user v{}{}'.format(PROMPT_VERSION, ' ({})'.format(label) if label else '')

    @property
    def provider(self):
        if self._provider is None:
            from ipandora.ai.aifactory import AIProviderFactory
            self._provider = AIProviderFactory().default
        return self._provider

    def opening(self) -> str:
        return self._opening

    def prompt(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        The whole conversation in one message. Not one message per turn with
        the roles flipped: the first turn is the user's, which the model would
        receive as its own, and providers reject a conversation that does not
        start with the user.
        """
        _lines = []
        for _m in messages:
            _who = 'You' if _m.get('role') == 'user' else 'Agent'
            _lines.append('{}: {}'.format(_who, redact_text(str(_m.get('content') or ''))))
        return [{'role': 'user', 'content': 'The conversation so far:\n\n{}\n\nYour next message:'.format(
            '\n'.join(_lines))}]

    def reply(self, messages) -> Optional[str]:
        if self.calls >= self.max_calls:
            return None
        self.calls += 1
        _text = (self.provider.chat(self.prompt(messages), system=SYSTEM.format(
            persona=self.persona, goal=self.goal, stop=STOP)) or '').strip()
        if not _text or STOP in _text:
            return None
        return _text


__all__ = ['ModelUser', 'STOP', 'SYSTEM', 'PROMPT_VERSION']

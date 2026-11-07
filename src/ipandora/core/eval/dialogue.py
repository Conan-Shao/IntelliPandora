# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : dialogue.py
@Time  : 2026-11-06

Business agents over several turns (docs/design/decisions/13 §3, the pytest
path, E2): a simulated user talks to the agent, the agent calls tools against
the business system, and what is judged is where the system ends up -- not
the words, not the order of the steps.

    from ipandora.core.eval import dialogue

    def agent(task):                                  # the spec's agent, as for `eval run`
        shop = Shop.seeded()                          # a fresh world for every trial
        bot = RefundBot(shop)
        return dialogue.converse(bot.respond, dialogue.ScriptedUser.from_task(task),
                                 max_turns=8, state=shop.snapshot)

    def grade(task, result):
        return [dialogue.same_state(result.output['state'], task.expected['state']),
                dialogue.called(result, 'refund', order_id=task.expected['order']),
                dialogue.not_called(result, 'delete_account'),
                dialogue.never_says(result, r'\\b\\d{16}\\b', 'a card number'),
                dialogue.finished(result)]

The agent is a function of the conversation so far -- a list of
{'role', 'content'} messages -- that returns its reply: text, or a Reply with
the tool calls it made and what they cost. The agent runs its own tools; this
module records them.

The simulated user here is scripted, so a trial is reproducible: an opening
line, and replies keyed to what the agent says. A model playing the user is
`ipandora.ai.simulated_user.ModelUser` -- optional, outside core, and named in
the run's manifest (user_simulator) since it changes what is measured.

Judged by code, in the order of 13 §5: end state, then trajectory rules --
what must and must not be called, with what arguments, how often, no loops --
then output constraints. Rules say what must and must not happen, never in
what order: there is more than one right path.
"""
import copy
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ipandora.core.assertion.check import Check, brief
from ipandora.core.eval.trial import AgentResult

TRAJECTORY, STATE, OUTPUT = 'trajectory', 'state', 'output'
"""Check.src of the judgements this module makes."""

ENDED_BY_USER, ENDED_BY_AGENT, ENDED_AT_LIMIT = 'user', 'agent', 'max_turns'
REFERENCE = 'reference'
"""`ended` of a result made by replay(): the gold actions, no conversation."""


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str = ''


@dataclass
class Reply:
    """What the agent says in one turn, and what it did to get there."""
    text: str = ''
    tool_calls: List[ToolCall] = field(default_factory=list)
    cost: Dict[str, float] = field(default_factory=dict)
    done: bool = False
    """The agent ends the conversation: handed over to a person, or closed the ticket."""


def _reply(value) -> Reply:
    if isinstance(value, Reply):
        return value
    if isinstance(value, str) or value is None:
        return Reply(text=value or '')
    if isinstance(value, dict):
        _calls = [_c if isinstance(_c, ToolCall) else ToolCall(
            name=str(_c.get('name', '')), args=dict(_c.get('args') or {}), result=_c.get('result'),
            error=str(_c.get('error') or '')) for _c in value.get('tool_calls') or []]
        return Reply(text=str(value.get('text') or ''), tool_calls=_calls,
                     cost=dict(value.get('cost') or {}), done=bool(value.get('done')))
    raise TypeError('an agent returns its reply as text, a dict or a Reply, got {!r}'.format(
        type(value).__name__))


# -- simulated users -----------------------------------------------------------------------

class User:
    """Someone the agent talks to. `reply` returns None to end the conversation."""

    name = 'user'
    """Recorded in the manifest's user_simulator: a different user is a different measurement."""

    def opening(self) -> str:
        raise NotImplementedError

    def reply(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        raise NotImplementedError


class ScriptedUser(User):
    """
    A user who follows a script: an opening line, then replies keyed to what
    the agent last said.

        ScriptedUser('我要退订单 A1001 的款',
                     rules=[(r'订单号|哪个订单', 'A1001'),
                            (r'确认|是否', '确认'),
                            (r'原因', '尺码不合适')],
                     otherwise='还有别的需要我提供吗？')

    The first rule whose pattern the agent's last message matches gives the
    reply; each rule answers once, so an agent asking the same thing again
    gets `otherwise`, and when that is used up too, the user leaves. A
    conversation therefore always ends, and the same agent replies give the
    same conversation.
    """

    name = 'scripted'

    def __init__(self, opening: str, rules: Sequence[Tuple[str, str]] = (), otherwise: Optional[str] = None,
                 patience: int = 1):
        if not isinstance(opening, str) or not opening:
            raise ValueError('a scripted user needs an opening line')
        self._opening = opening
        self._rules = []
        for _rule in rules or ():
            if not isinstance(_rule, (list, tuple)) or len(_rule) != 2:
                raise ValueError('a rule is a [pattern, reply] pair, got {!r}'.format(_rule))
            self._rules.append((re.compile(str(_rule[0]), re.IGNORECASE), str(_rule[1])))
        self._otherwise = otherwise
        self._patience = patience
        self._used = set()
        self._fallbacks = 0

    @classmethod
    def from_task(cls, task) -> 'ScriptedUser':
        """
        The script in a task's input:

            input:
              opening: 我要退订单 A1001 的款
              rules: [[订单号, A1001], [确认, 确认]]
              otherwise: 好的
        """
        _input = getattr(task, 'input', task)
        if isinstance(_input, str):
            return cls(_input)
        if not isinstance(_input, dict):
            raise ValueError('task {}: the input is not a user script (opening, rules, otherwise)'.format(
                getattr(task, 'id', '?')))
        return cls(_input.get('opening', ''), rules=_input.get('rules') or (),
                   otherwise=_input.get('otherwise'), patience=int(_input.get('patience', 1)))

    def opening(self) -> str:
        # a new conversation: one user object reused across trials -- defined
        # once at module level -- answered nothing after the first, and the
        # agent was blamed for the user who had nothing left to say
        self._used = set()
        self._fallbacks = 0
        return self._opening

    def reply(self, messages):
        _last = next((str(_m.get('content') or '') for _m in reversed(messages)
                      if _m.get('role') == 'assistant'), '')
        for _i, (_pattern, _answer) in enumerate(self._rules):
            if _i not in self._used and _pattern.search(_last):
                self._used.add(_i)
                return _answer
        if self._otherwise is not None and self._fallbacks < self._patience:
            self._fallbacks += 1
            return self._otherwise
        return None


# -- the conversation ------------------------------------------------------------------------

def converse(agent: Callable[[List[Dict[str, Any]]], Any], user: User, max_turns: int = 10,
             state: Optional[Callable[[], Any]] = None) -> AgentResult:
    """
    Talk until the user leaves, the agent ends it, or `max_turns` agent turns.

    :param agent: messages -> reply (text, dict or Reply).
    :param state: called once at the end; its value is the world as the agent
                  left it, in `result.output['state']`. Deep-copied, so a later
                  change to the world cannot change what was judged.
    :returns:     an AgentResult whose output is {'reply': the agent's last
                  message, 'ended': 'user' | 'agent' | 'max_turns', 'turns',
                  'state'}; the trajectory has every message and tool call.
    """
    if max_turns < 1:
        raise ValueError('max_turns must be at least 1')
    _start = time.perf_counter()
    _messages = [{'role': 'user', 'content': user.opening()}]
    _trajectory = [{'t': 0.0, 'kind': 'message', 'role': 'user', 'name': getattr(user, 'name', 'user'),
                    'text': _messages[0]['content'], 'error': ''}]
    _cost: Dict[str, float] = {}
    _ended, _turns, _last = ENDED_AT_LIMIT, 0, ''

    def _now():
        return round(time.perf_counter() - _start, 3)

    for _turns in range(1, max_turns + 1):
        _r = _reply(agent([dict(_m) for _m in _messages]))
        for _call in _r.tool_calls:
            _trajectory.append({'t': _now(), 'kind': 'tool', 'role': 'tool', 'name': _call.name,
                                'args': _copy(_call.args), 'result': _call.result,
                                'text': '{}({})'.format(_call.name, _args_text(_call.args)),
                                'error': _call.error})
        for _key, _value in (_r.cost or {}).items():
            if isinstance(_value, (int, float)) and not isinstance(_value, bool):
                _cost[_key] = _cost.get(_key, 0) + _value
        _cost['tool_calls'] = _cost.get('tool_calls', 0) + len(_r.tool_calls)
        _last = _r.text
        _messages.append({'role': 'assistant', 'content': _r.text,
                          'tool_calls': [{'name': _c.name, 'args': _c.args} for _c in _r.tool_calls]})
        _trajectory.append({'t': _now(), 'kind': 'message', 'role': 'assistant', 'name': 'agent',
                            'text': _r.text, 'error': ''})
        if _r.done:
            _ended = ENDED_BY_AGENT
            break
        _next = user.reply([dict(_m) for _m in _messages])
        if _next is None:
            _ended = ENDED_BY_USER
            break
        _messages.append({'role': 'user', 'content': _next})
        _trajectory.append({'t': _now(), 'kind': 'message', 'role': 'user',
                            'name': getattr(user, 'name', 'user'), 'text': _next, 'error': ''})
    _cost['turns'] = _turns
    _trajectory.append({'t': _now(), 'kind': 'result', 'role': '', 'name': 'ended', 'text': _ended,
                        'error': ''})
    return AgentResult(output={'reply': _last, 'ended': _ended, 'turns': _turns,
                               'state': _copy(state()) if state is not None else None},
                       trajectory=_trajectory, cost=_cost)


def replay(calls: Sequence[Union[ToolCall, Sequence]], run: Callable[..., Any],
           state: Optional[Callable[[], Any]] = None) -> AgentResult:
    """
    A reference solution as τ-bench writes one: the gold actions, run against
    a fresh world, give the end state any correct conversation must reach.
    The same graders judge it, so `ipandora eval selfcheck` proves each task
    can be solved and each grader passes a right answer.

    :param calls: [ToolCall] or [[name, {args}], ...] -- straight from a dataset.
    :param run:   (name, **args) -> result: the business system's tools.
    """
    _trajectory = []
    for _i, _c in enumerate(calls or ()):
        _call = _c if isinstance(_c, ToolCall) else ToolCall(name=str(_c[0]), args=dict(_c[1] if len(_c) > 1 else {}))
        _call.result = run(_call.name, **_call.args)
        _trajectory.append({'t': float(_i), 'kind': 'tool', 'role': 'tool', 'name': _call.name,
                            'args': _copy(_call.args), 'result': _call.result,
                            'text': '{}({})'.format(_call.name, _args_text(_call.args)), 'error': ''})
    _trajectory.append({'t': float(len(_trajectory)), 'kind': 'result', 'role': '', 'name': 'ended',
                        'text': REFERENCE, 'error': ''})
    return AgentResult(output={'reply': '', 'ended': REFERENCE, 'turns': 0,
                               'state': _copy(state()) if state is not None else None},
                       trajectory=_trajectory, cost={'tool_calls': len(calls or ())})


def _copy(value):
    """
    A deep copy where one can be made. Arguments holding a lock, a client or a
    file cannot be copied, and a failed copy raised out of converse() -- where
    it read as the infrastructure failing, not as anything the agent did.
    """
    try:
        return copy.deepcopy(value)
    except Exception:  # noqa: BLE001 -- anything that cannot be copied is kept as it is
        return value


def _args_text(args: Dict[str, Any]) -> str:
    return ', '.join('{}={}'.format(_k, brief(_v, 60)) for _k, _v in sorted((args or {}).items()))


# -- what the agent did -------------------------------------------------------------------------

def tool_calls(result, name: Optional[str] = None) -> List[ToolCall]:
    """The tool calls of a conversation, in order; only `name`'s when given."""
    _trajectory = getattr(result, 'trajectory', result) or []
    return [ToolCall(name=_e.get('name', ''), args=dict(_e.get('args') or {}), result=_e.get('result'),
                     error=_e.get('error') or '')
            for _e in _trajectory
            if isinstance(_e, dict) and _e.get('kind') == 'tool' and (name is None or _e.get('name') == name)]


ArgSpec = Union[Any, Callable[[Any], bool]]


def _matches(call: ToolCall, expected: Dict[str, ArgSpec]) -> bool:
    for _key, _want in expected.items():
        if _key not in call.args:
            return False
        _got = call.args[_key]
        if callable(_want) and not isinstance(_want, type):
            try:
                if not _want(_got):
                    return False
            except Exception:  # noqa: BLE001 -- a predicate that cannot judge this value does not match it
                return False
        elif _got != _want:
            return False
    return True


def _spec_text(name: str, args: Dict[str, ArgSpec]) -> str:
    return '{}({})'.format(name, ', '.join(
        '{}={}'.format(_k, '<条件 {}>'.format(getattr(_v, '__name__', 'lambda'))
                       if callable(_v) and not isinstance(_v, type) else brief(_v, 60))
        for _k, _v in sorted(args.items())))


def _seen(calls: List[ToolCall]) -> str:
    if not calls:
        return '没有调用'
    _shown = ['{}({})'.format(_c.name, _args_text(_c.args)) for _c in calls[:5]]
    return '实际调用：' + '；'.join(_shown) + ('；……共 {} 次'.format(len(calls)) if len(calls) > 5 else '')


def called(result, name: str, **args: ArgSpec) -> Check:
    """The agent called `name`, at least once with these arguments. An argument may be a predicate."""
    _calls = tool_calls(result, name)
    _ok = any(_matches(_c, args) for _c in _calls)
    return Check(name='调用了 {}'.format(_spec_text(name, args)), ok=_ok, expr=_seen(_calls),
                 src=TRAJECTORY, claim='called {}'.format(_spec_text(name, args)))


def not_called(result, name: str, **args: ArgSpec) -> Check:
    """The agent never called `name` -- or never with these arguments."""
    _calls = [_c for _c in tool_calls(result, name) if _matches(_c, args)]
    return Check(name='没有调用 {}'.format(_spec_text(name, args)), ok=not _calls, expr=_seen(_calls),
                 src=TRAJECTORY, claim='never called {}'.format(_spec_text(name, args)))


def called_at_most(result, name: str, times: int) -> Check:
    _calls = tool_calls(result, name)
    return Check(name='{} 最多调用 {} 次'.format(name, times), ok=len(_calls) <= times,
                 expr='调用了 {} 次；{}'.format(len(_calls), _seen(_calls)), src=TRAJECTORY,
                 claim='{} called at most {} times'.format(name, times))


def no_loops(result, repeats: int = 3) -> Check:
    """No identical call -- same tool, same arguments -- `repeats` times in a row."""
    _calls = tool_calls(result)
    _run, _worst = 1, (1, None)
    for _prev, _cur in zip(_calls, _calls[1:]):
        _run = _run + 1 if (_cur.name, _key(_cur.args)) == (_prev.name, _key(_prev.args)) else 1
        if _run > _worst[0]:
            _worst = (_run, _cur)
    _ok = _worst[0] < repeats
    _expr = '最长的连续重复：{} 次{}'.format(_worst[0], '' if _worst[1] is None else '，{}({})'.format(
        _worst[1].name, _args_text(_worst[1].args)))
    return Check(name='没有原地打转（同一调用连续 {} 次）'.format(repeats), ok=_ok, expr=_expr, src=TRAJECTORY,
                 claim='no identical call {} times in a row'.format(repeats))


def _key(value) -> str:
    return repr(sorted(value.items())) if isinstance(value, dict) else repr(value)


def finished(result) -> Check:
    """The conversation came to an end -- the user left or the agent closed it -- before the turn limit."""
    _out = getattr(result, 'output', None)
    _ended = _out.get('ended') if isinstance(_out, dict) else None
    return Check(name='对话在轮数上限内结束', ok=_ended in (ENDED_BY_USER, ENDED_BY_AGENT, REFERENCE),
                 expr='结束方式：{}，{} 轮'.format(_ended, _out.get('turns') if isinstance(_out, dict) else '?'),
                 src=TRAJECTORY, claim='ended before max_turns')


# -- what the agent said ------------------------------------------------------------------------

def _agent_texts(result) -> List[str]:
    return [str(_e.get('text') or '') for _e in getattr(result, 'trajectory', None) or []
            if isinstance(_e, dict) and _e.get('kind') == 'message' and _e.get('role') == 'assistant']


def says(result, pattern: str, what: str = '') -> Check:
    """Some message of the agent matches `pattern` (a regular expression)."""
    _re = re.compile(pattern, re.IGNORECASE)
    _hit = next((_t for _t in _agent_texts(result) if _re.search(_t)), None)
    _label = what or pattern
    return Check(name='agent 说了 {}'.format(_label), ok=_hit is not None,
                 expr=brief(_hit) if _hit is not None else '没有一条消息匹配 {}'.format(pattern),
                 src=OUTPUT, claim='says /{}/'.format(pattern))


def never_says(result, pattern: str, what: str = '') -> Check:
    """No message of the agent matches `pattern`: a card number, an internal id, a promise it cannot keep."""
    _re = re.compile(pattern, re.IGNORECASE)
    _hits = [_t for _t in _agent_texts(result) if _re.search(_t)]
    _label = what or pattern
    # the evidence names where, not the matched text: it may be the secret itself
    return Check(name='agent 没有说出 {}'.format(_label), ok=not _hits,
                 expr='{} 条消息匹配'.format(len(_hits)) if _hits else '没有消息匹配',
                 src=OUTPUT, claim='never says /{}/'.format(pattern))


# -- where the world ended up ------------------------------------------------------------------

def _ignorer(patterns: Iterable[str]) -> Callable[[str], bool]:
    """
    Paths to leave out: exact (`orders.A1001.updated_at`), or with `*` for
    one whole segment (`orders.*.updated_at`) -- every record's timestamp.
    """
    _exact, _wild = set(), []
    for _p in patterns:
        if '*' in _p:
            _wild.append(re.compile(r'\.'.join(
                '[^.]+' if _s == '*' else re.escape(_s) for _s in _p.split('.')) + r'\Z'))
        else:
            _exact.add(_p)
    return lambda path: path in _exact or any(_r.match(path) for _r in _wild)


def _diff(actual, expected, path: str, ignore: Callable[[str], bool], out: List[str], limit: int) -> None:
    if len(out) >= limit or (path and ignore(path)):
        return
    if isinstance(actual, dict) and isinstance(expected, dict):
        for _k in sorted(set(actual) | set(expected), key=str):
            _p = '{}.{}'.format(path, _k) if path else str(_k)
            if ignore(_p):
                continue
            if _k not in actual:
                out.append('{}：缺少，应为 {}'.format(_p, brief(expected[_k], 80)))
            elif _k not in expected:
                out.append('{}：多出 {}'.format(_p, brief(actual[_k], 80)))
            else:
                _diff(actual[_k], expected[_k], _p, ignore, out, limit)
            if len(out) >= limit:
                return
        return
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            out.append('{}：{} 项，应为 {} 项'.format(path or '(根)', len(actual), len(expected)))
            return
        for _i, (_a, _e) in enumerate(zip(actual, expected)):
            _diff(_a, _e, '{}[{}]'.format(path, _i), ignore, out, limit)
        return
    # 1 and 1.0 are the same amount; True and 1, or '1' and 1, are not the same record
    _numbers = all(isinstance(_x, (int, float)) and not isinstance(_x, bool) for _x in (actual, expected))
    if actual != expected or (not _numbers and type(actual) is not type(expected)):
        out.append('{}：{}，应为 {}'.format(path or '(根)', brief(actual, 80), brief(expected, 80)))


def differences(actual, expected, ignore: Iterable[str] = (), limit: int = 20) -> List[str]:
    """Where `actual` differs from `expected`, as `path: actual, expected` lines (at most `limit`)."""
    _out: List[str] = []
    _diff(actual, expected, '', _ignorer(ignore), _out, limit)
    return _out


def same_state(actual, expected, ignore: Iterable[str] = (), name: str = '终态与预期一致') -> Check:
    """
    The world ended where it should have (τ-bench's end-state check): every
    record equal, nothing missing, nothing extra. `ignore` names paths that
    legitimately differ between runs -- `orders.A1001.updated_at`, or
    `orders.*.updated_at` for every order's.
    """
    _diffs = differences(actual, expected, ignore)
    return Check(name=name, ok=not _diffs, expr='；'.join(_diffs[:5]) + (
        '；……共 {} 处不同'.format(len(_diffs)) if len(_diffs) > 5 else '') if _diffs else '完全一致',
        src=STATE, claim='end state == expected' + (' ignoring {}'.format(', '.join(sorted(ignore)))
                                                       if ignore else ''))


__all__ = ['converse', 'replay', 'REFERENCE', 'Reply', 'ToolCall', 'User', 'ScriptedUser',
           'tool_calls', 'called', 'not_called', 'called_at_most', 'no_loops', 'finished',
           'says', 'never_says', 'same_state', 'differences',
           'ENDED_BY_USER', 'ENDED_BY_AGENT', 'ENDED_AT_LIMIT']

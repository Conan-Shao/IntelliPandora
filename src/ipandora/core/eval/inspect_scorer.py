# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : inspect_scorer.py
@Time  : 2026-11-06

A grader of this framework as an Inspect scorer (docs/design/decisions/13 §3,
E1): the same `grade(task, result)` judges a run of the pytest path and a
run in Inspect's sandbox.

    from inspect_ai import Task, task
    from ipandora.core.eval.inspect_scorer import scorer

    def grade(task, result):                       # the grader the pytest path uses
        return [that(result.output, 'answer').contains(task.expected)]

    @task
    def coding():
        return Task(dataset=..., solver=..., scorer=scorer(grade))

The score is CORRECT when every required deterministic check holds,
INCORRECT when one does not, and NOANSWER when nothing was judged -- the
zero-judgement case, which must not read as a pass. The checks themselves go
into the score's metadata, so inspect_log.read() reports each one by name,
not one opaque value. A model-judge check is recorded and decides nothing,
as everywhere else.

The grader may be `async def`: one that runs hidden tests in the sandbox
awaits `inspect_ai.util.sandbox().exec(...)`. A grader that raises is the
grader's problem, not the agent's: the score says so and the trial is
attributed to the grader.

Needs the `inspect` extra (Python 3.11+).
"""
import inspect as _pyinspect
import traceback
from typing import Any, Callable, Dict, List

from ipandora.core.eval.dataset import Task
from ipandora.core.eval.inspect_log import INSTALL_HINT, META_KEY, TEXT_LIMIT
from ipandora.core.eval.run import grade_one
from ipandora.core.eval.trial import AgentResult, Trial


def task_of(state, target) -> Task:
    """
    The framework's Task for an Inspect sample: id, input, expected, tags,
    polarity, split. Not budget: in Inspect, limits are Inspect's own
    (time_limit, token_limit, ...), and inspect_log.read() judges a sample
    that hit one -- a budget in the metadata would be read and judged by
    nobody.
    """
    _meta = dict(getattr(state, 'metadata', None) or {})
    _targets = list(getattr(target, 'target', None) or [])
    _expected = _targets[0] if len(_targets) == 1 else (_targets or None)
    _fields = {}
    for _key, _allowed in (('polarity', ('do', 'dont')), ('split', ('dev', 'test'))):
        if _meta.get(_key) in _allowed:
            _fields[_key] = _meta[_key]
    return Task(id=str(getattr(state, 'sample_id', '')), input=getattr(state, 'input_text', None),
                expected=_expected,
                tags=dict(_meta.get('tags') or {}) if isinstance(_meta.get('tags'), dict) else {},
                meta=_meta, **_fields)


def result_of(state) -> AgentResult:
    """What the agent handed back: the final completion, and the conversation as the trajectory."""
    _trajectory = []
    for _m in getattr(state, 'messages', None) or []:
        _text = getattr(_m, 'text', '') or ''
        _trajectory.append({'kind': 'tool' if getattr(_m, 'role', '') == 'tool' else 'message',
                            'role': getattr(_m, 'role', ''), 'name': getattr(_m, 'function', '') or '',
                            'text': _text[:TEXT_LIMIT], 'error': ''})
    _output = getattr(state, 'output', None)
    _usage = getattr(_output, 'usage', None)
    _cost = {}
    if _usage is not None:
        _cost = {'tokens_in': int(getattr(_usage, 'input_tokens', 0) or 0),
                 'tokens_out': int(getattr(_usage, 'output_tokens', 0) or 0)}
    return AgentResult(output=getattr(_output, 'completion', None), trajectory=_trajectory, cost=_cost)


def _explain(checks: List[Dict[str, Any]]) -> str:
    _failed = [_c for _c in checks if not _c.get('ok') and _c.get('required', True)]
    if not checks:
        return '没有任何判定'
    if not _failed:
        return '{} 条判定全部成立'.format(len(checks))
    return '；'.join('{}：{}'.format(_c.get('name', ''), _c.get('expr', '')) for _c in _failed[:5])


def scorer(grade: Callable, name: str = 'ipandora'):
    """An Inspect Scorer that runs `grade(task, result)` and keeps its checks."""
    try:
        from inspect_ai.scorer import (CORRECT, INCORRECT, NOANSWER, Score, accuracy, stderr)
        from inspect_ai.scorer import scorer as _register
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc

    async def _grade(task: Task, result: AgentResult):
        _out = grade(task, result)
        if _pyinspect.isawaitable(_out):
            _out = await _out
        return _out

    @_register(metrics=[accuracy(), stderr()], name=name)
    def _make():
        async def score(state, target):
            _task, _result = task_of(state, target), result_of(state)
            try:
                _value = await _grade(_task, _result)
                _checks = grade_one(_task, _result, lambda _t, _r: _value)
            except Exception as exc:  # noqa: BLE001 -- the grader is under test too
                _error = 'grader raised {}: {}\n{}'.format(type(exc).__name__, exc,
                                                          traceback.format_exc(limit=3))
                return Score(value=NOANSWER, answer=_result.output, explanation=_error[:TEXT_LIMIT],
                             metadata={META_KEY: {'grader_error': _error[:TEXT_LIMIT]}})
            _success = Trial(task_id=_task.id, index=0, checks=_checks).success
            return Score(value=NOANSWER if _success is None else (CORRECT if _success else INCORRECT),
                         answer=_result.output, explanation=_explain(_checks),
                         metadata={META_KEY: {'checks': _checks}})
        return score

    return _make()


__all__ = ['scorer', 'task_of', 'result_of']

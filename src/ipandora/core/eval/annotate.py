# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : annotate.py
@Time  : 2026-11-05

The human channel: export samples for people to label, read the labels back,
and measure how often a model judge agrees with them.

A model judge's verdicts take no part in success or in a gate until its
agreement with people is known and high enough (docs/design/decisions/13 §5).
This is where that number comes from. The same export, labelled by two
people, measures whether a task is ambiguous: two people who disagree about
the right answer mean the task, not the agent, needs work.

Rows are JSONL, one per (trial, judge check), so a spreadsheet or a labelling
tool can take them as they are:

    {"task_id": ..., "trial": 2, "check": "计划是否合理", "judge": true,
     "output": ..., "trajectory_steps": 9, "human": null}

People fill `human` with true, false or null (could not tell).
"""
import json
import random
from typing import Any, Dict, List, Optional

from ipandora.core.eval.run import EvalRun


def samples(run: EvalRun, limit: Optional[int] = None, seed: int = 0,
            include_deterministic: bool = False) -> List[Dict[str, Any]]:
    """
    Rows to label. By default the model-judge checks -- those are what is being
    calibrated. include_deterministic adds the code checks, for measuring
    whether two people agree on a task at all.
    """
    _rows = []
    for _t in run.trials:
        for _c in _t.checks:
            if _c.get('src') != 'llm_judge' and not include_deterministic:
                continue
            _rows.append({'task_id': _t.task_id, 'trial': _t.index, 'check': _c.get('name'),
                          'source': _c.get('src'),
                          'judge': None if _c.get('uncertain') else bool(_c.get('ok')),
                          'output': _masked(_t.output), 'trajectory_steps': len(_t.trajectory),
                          'human': None})
    if limit is not None and limit < len(_rows):
        # bandit B311: sampling rows for people to label, not secrecy
        _rows = random.Random(seed).sample(_rows, limit)  # nosec B311
        _rows.sort(key=lambda _r: (_r['task_id'], _r['trial'], str(_r['check'])))
    return _rows


def _masked(value: Any) -> Any:
    # rows go to people, and from there anywhere: masked like the report
    from ipandora.core.eval.report import _masked as masked
    return masked(value)


def export(rows: List[Dict[str, Any]], path: str) -> str:
    with open(path, 'w', encoding='utf-8') as fh:
        for _row in rows:
            fh.write(json.dumps(_row, ensure_ascii=False, default=str) + '\n')
    return path


def read(path: str) -> List[Dict[str, Any]]:
    _rows = []
    with open(path, 'r', encoding='utf-8') as fh:
        for _n, _line in enumerate(fh, 1):
            if _line.strip():
                try:
                    _rows.append(json.loads(_line))
                except ValueError as exc:
                    raise ValueError('{}:{}: {}'.format(path, _n, exc))
    return _rows


_YES = {'true', 'yes', 'y', '1', 't', '是', '成立', 'pass'}
_NO = {'false', 'no', 'n', '0', 'f', '否', '不成立', 'fail'}


def verdict_of(value) -> Optional[bool]:
    """
    A label as people write it. bool('false') is True: a labeller who typed
    "false" as text was counted as agreeing with every "yes". Anything not
    recognisable is undecided, not guessed.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    _text = str(value).strip().lower()
    if _text in _YES:
        return True
    if _text in _NO:
        return False
    return None


def agreement(rows: List[Dict[str, Any]], a: str = 'judge', b: str = 'human') -> Dict[str, Any]:
    """
    How often `a` and `b` agree, over the rows where both decided.

    Returns the count, the raw agreement rate, and Cohen's kappa -- agreement
    beyond what two raters who said "yes" at their own rates would reach by
    chance. A judge that says yes to everything on a set that is 90% yes has
    90% raw agreement and a kappa of 0; the kappa is the number to gate on.
    """
    _pairs = []
    for _r in rows:
        _x, _y = verdict_of(_r.get(a)), verdict_of(_r.get(b))
        if _x is not None and _y is not None:
            _pairs.append((_x, _y))
    _n = len(_pairs)
    _undecided = len(rows) - _n
    if not _n:
        return {'n': 0, 'undecided': _undecided, 'agreement': None, 'kappa': None}
    _agree = sum(1 for _x, _y in _pairs if _x == _y) / _n
    _pa = sum(1 for _x, _ in _pairs if _x) / _n
    _pb = sum(1 for _, _y in _pairs if _y) / _n
    _chance = _pa * _pb + (1 - _pa) * (1 - _pb)
    _kappa = 1.0 if _chance == 1 else (_agree - _chance) / (1 - _chance)
    return {'n': _n, 'undecided': _undecided, 'agreement': _agree, 'kappa': _kappa}

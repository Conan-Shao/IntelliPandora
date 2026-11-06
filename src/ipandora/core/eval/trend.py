# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : trend.py
@Time  : 2026-11-06

Saturation (docs/design/decisions/13 §6, E4): an evaluation every version
passes has stopped measuring anything. When a dataset's success rate has
stayed at the top for the last few runs, it is ready to graduate -- move it
into the regression set, where a drop is what matters -- and the capability
set needs harder tasks.

    from ipandora.core.eval import trend

    runs = trend.history(dataset='coding-tasks', split='test')      # from the report archive
    trend.saturation(runs + [run])
    # {'saturated': True, 'rates': [0.97, 0.98, 1.0], 'tasks': ['multi/rename-config-key', ...], ...}

Read from the report archive (`ipandora eval run` and `eval inspect` write
each run's report.json there), so nothing new has to be kept.
"""
import glob
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from ipandora.core.eval.run import EvalRun

THRESHOLD = 0.95
"""A success rate at or above this, run after run, is saturated."""

LAST = 3
"""How many of the most recent runs must all be at the top."""


def history(directory: Optional[str] = None, dataset: str = '', split: Optional[str] = None,
            limit: int = 50) -> List[EvalRun]:
    """
    Earlier evaluation runs of `dataset` (and `split`, when given), oldest
    first, from the report archive. Runs whose report cannot be read are
    skipped: an archive outlives format changes.
    """
    if directory is None:
        from ipandora.core.report.history import reports_dir
        directory = reports_dir()
    _runs = []
    for _path in glob.glob(os.path.join(directory, '*', 'report.json')):
        try:
            with open(_path, encoding='utf-8') as _f:
                _data = json.load(_f)
            if not isinstance(_data, dict) or _data.get('view') != 'eval':
                continue
            _run = EvalRun.from_dict(_data)
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if dataset and _run.manifest.dataset != dataset:
            continue
        if split is not None and (_run.manifest.split or '') != (split or ''):
            continue
        _runs.append(_run)
    _runs.sort(key=lambda _r: (_r.manifest.started or '', _r.run_id))
    return _runs[-limit:]


def saturation(runs: Sequence[EvalRun], threshold: float = THRESHOLD, last: int = LAST) -> Dict[str, Any]:
    """
    Whether the last `last` runs all reached `threshold`, and which tasks
    succeeded in every trial of every one of them.

    Only runs of the same dataset content count: a run on a changed dataset
    starts the count again (the tasks are not the ones that saturated).
    """
    _runs = list(runs)
    if _runs:
        _hash = _runs[-1].manifest.dataset_hash
        _same = []
        for _r in reversed(_runs):
            if _hash and _r.manifest.dataset_hash and _r.manifest.dataset_hash != _hash:
                break
            _same.append(_r)
        _runs = list(reversed(_same))
    _recent = _runs[-last:]
    _rates = [_r.summary()['success_rate'] for _r in _recent]
    _saturated = len(_recent) >= last and all(_x is not None and _x >= threshold for _x in _rates)
    _tasks = None
    for _r in _recent:
        _all = {_t for _t, _v in _r.outcomes().items() if _v and all(_v)}
        _tasks = _all if _tasks is None else _tasks & _all
    return {'saturated': _saturated, 'rates': _rates, 'runs': len(_recent), 'threshold': threshold,
            'last': last, 'tasks': sorted(_tasks or []) if len(_recent) >= last else [],
            'total_tasks': len(_recent[-1].tasks) if _recent else 0}


def sentence(result: Dict[str, Any]) -> str:
    """One line for the console and the report; '' when there is nothing to say."""
    if result.get('saturated'):
        return ('已饱和：最近 {} 次成功率都在 {:.0%} 以上，这个评测集可以毕业到回归集，能力评测需要补更难的题'.format(
            result['last'], result['threshold']))
    if result.get('tasks'):
        return '{} / {} 道题最近 {} 次全部成功，可以考虑移到回归集'.format(
            len(result['tasks']), result['total_tasks'], result['last'])
    return ''


__all__ = ['history', 'saturation', 'sentence', 'THRESHOLD', 'LAST']

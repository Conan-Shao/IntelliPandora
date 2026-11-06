# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baseline.py
@Time  : 2026-11-05

The evaluation baseline: per-task outcomes of the version being compared with.

Like conf/judgements.json it is a file meant to be committed -- by default
conf/eval_baseline.json -- so "better or worse than before" has the same
answer on every machine. It holds each task's trial outcomes and the manifest
of the run that produced them; a comparison with a baseline whose dataset
hash, split or resources differ says the scores are not comparable before it
says anything else.
"""
import json
import os
from typing import Any, Dict, List, Optional

from ipandora.core.eval import stats
from ipandora.core.eval.run import EvalRun
from ipandora.core.eval.trial import Manifest

VERSION = 1
DEFAULT_NAME = 'eval_baseline.json'


def default_path() -> str:
    from ipandora.core.schedule import config
    return os.path.join(config.project_conf_dir(), DEFAULT_NAME)


def build(run: EvalRun) -> Dict[str, Any]:
    return {'version': VERSION, 'run_id': run.run_id, 'manifest': run.manifest.to_dict(),
            'tasks': {_t['id']: {'tags': _t.get('tags', {}),
                                 'success': run.outcomes().get(_t['id'], []),
                                 'score': run.outcomes(partial=True).get(_t['id'], [])}
                      for _t in run.tasks}}


def save(path: str, run: EvalRun) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        # sorted, one task per block: reviewed as a diff
        json.dump(build(run), fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')
    return os.path.abspath(path)


def load(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as fh:
        _data = json.load(fh)
    if not isinstance(_data, dict) or not isinstance(_data.get('tasks'), dict):
        raise ValueError('{} is not an evaluation baseline'.format(path))
    return _data


def compare(run: EvalRun, baseline: Dict[str, Any], noise: float = 0.0,
            partial: bool = False) -> Dict[str, Any]:
    """
    The run against the baseline: overall and per tag value.

    Returns stats.compare()'s result for all tasks, `by_tag` with the same for
    each tag value, `not_comparable` reasons from the manifests, and the tasks
    that changed most.
    """
    _key = 'score' if partial else 'success'
    _base = {_id: list(_v.get(_key) or []) for _id, _v in baseline['tasks'].items()}
    _now = run.outcomes(partial=partial)
    _out = stats.compare(_base, _now, noise=noise)
    _out['not_comparable'] = run.manifest.comparable_with(Manifest.from_dict(baseline.get('manifest')))
    _out['baseline_run'] = baseline.get('run_id', '')
    _out['by_tag'] = []
    _groups = [(_tag, _value) for _tag, _values in sorted(run.tag_values().items()) for _value in _values]
    # one comparison per tag value: at 95% each, twenty of them call some group
    # worse by chance alone. Bonferroni keeps the chance of any false alarm at 5%.
    _level = 1 - (1 - 0.95) / max(len(_groups), 1)
    for _tag, _value in _groups:
        _ids = set(run.task_ids(**{_tag: _value}))
        _sub = stats.compare({_k: _v for _k, _v in _base.items() if _k in _ids},
                             {_k: _v for _k, _v in _now.items() if _k in _ids}, noise=noise, level=_level)
        _b = [_x for _k, _v in _base.items() if _k in _ids for _x in _v]
        _n = [_x for _k, _v in _now.items() if _k in _ids for _x in _v]
        _sub.update({'tag': _tag, 'value': _value,
                     'base_rate': (sum(_b) / len(_b)) if _b else None,
                     'now_rate': (sum(_n) / len(_n)) if _n else None})
        _out['by_tag'].append(_sub)
    _changes = []
    for _id in sorted(set(_base) & set(_now)):
        if _base[_id] and _now[_id]:
            _changes.append({'task_id': _id,
                             'base': [int(sum(_base[_id])), len(_base[_id])],
                             'now': [int(sum(_now[_id])), len(_now[_id])],
                             'difference': sum(_now[_id]) / len(_now[_id])
                             - sum(_base[_id]) / len(_base[_id])})
    _out['worst'] = sorted((_c for _c in _changes if _c['difference'] < 0),
                           key=lambda _c: (_c['difference'], _c['task_id']))
    _out['best'] = sorted((_c for _c in _changes if _c['difference'] > 0),
                          key=lambda _c: (-_c['difference'], _c['task_id']))
    # a task that always succeeded and now always fails, over at least two
    # trials each side: too few tasks to move the overall rate, and the
    # clearest regression there is
    _out['broken'] = [_c['task_id'] for _c in _out['worst']
                      if _c['base'][1] >= BROKEN_MIN_TRIALS and _c['now'][1] >= BROKEN_MIN_TRIALS
                      and _c['base'][0] == _c['base'][1] and _c['now'][0] == 0]
    return _out


BROKEN_MIN_TRIALS = 2

GATES = ('overall', 'tag', 'task')
"""What fails the gate, each including the ones before it: the overall verdict;
any tag value worse (Bonferroni-corrected); any task broken."""


def regressions(comparison: Dict[str, Any], gate: str = 'overall') -> List[str]:
    """Why the gate fails -- empty when it passes. `not comparable` always fails it."""
    if gate not in GATES:
        raise ValueError('unknown gate {!r}; one of {}'.format(gate, ', '.join(GATES)))
    if not comparison:
        return []
    _out = []
    if comparison.get('not_comparable'):
        _out.append('和基线不可比：{}'.format('；'.join(comparison['not_comparable'])))
    if comparison.get('verdict') == stats.WORSE:
        _out.append('整体变差（{:+.1f} 个百分点）'.format(100.0 * comparison.get('difference', 0.0)))
    if gate in ('tag', 'task'):
        for _t in comparison.get('by_tag') or []:
            if _t.get('verdict') == stats.WORSE:
                _out.append('{}={} 变差（{:+.1f} 个百分点）'.format(_t['tag'], _t['value'],
                                                               100.0 * _t.get('difference', 0.0)))
    if gate == 'task' and comparison.get('broken'):
        _out.append('以前全过、现在全挂的任务：{}'.format('、'.join(comparison['broken'][:10])))
    return _out

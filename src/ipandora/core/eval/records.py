# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : records.py
@Time  : 2026-11-07

One JSON line per run: what an evaluation's raw results are kept as, so every
number in a report can be regenerated from them by a script (E9).

    ipandora eval records report.json -o results/dsh-standard.jsonl --tasks tasks/

Each line: the task, the configuration (the manifest's harness), which
attempt, the verdict and every check, tokens (cache hits apart), cost, time,
turns, tool calls, how the run ended, how often its infrastructure failed and
was retried (infra_retries, infra_errors) -- and for test-generation tasks, the
reason a run failed and what was flagged (testgen.failure_reason / flags),
and the mutants its tests killed of those tried (mutation).
`over_budget` compares the cost with the task's budget.max_usd: a flag, never
a failure -- the run is judged as it ran.
"""
import re
from typing import Any, Dict, List, Optional

from ipandora.core.eval import testgen
from ipandora.core.eval.run import EvalRun

COST_KEYS = ('tokens_in', 'tokens_out', 'tokens_cache_read', 'tokens_cache_write', 'usd', 'turns', 'tool_calls')


def records(run: EvalRun, budgets: Optional[Dict[str, Dict[str, float]]] = None) -> List[Dict[str, Any]]:
    """
    :param budgets: task id -> {max_usd, max_minutes}, e.g. from testgen.load()
                    (each task's meta['budget']). A run over max_usd, or over
                    max_minutes of wall time, is flagged over_budget.
    """
    _out = []
    for _t in run.trials:
        _budget = (budgets or {}).get(_t.task_id) or {}
        _usd = (_t.cost or {}).get('usd')
        _over = bool((_budget.get('max_usd') is not None and isinstance(_usd, (int, float))
                      and _usd > _budget['max_usd'])
                     or (_budget.get('max_minutes') is not None and _t.seconds > 60 * _budget['max_minutes']))
        _testgen = any(_c.get('claim') == 'fail to pass' for _c in _t.checks)
        _row = {'task': _t.task_id, 'config': run.manifest.harness or run.run_id, 'model': run.manifest.model,
                'attempt': _t.index + 1, 'run_id': run.run_id, 'success': _t.success, 'status': _t.status,
                'category': _t.category, 'ended': _t.ended or ('error' if _t.status == 'infra' else 'completed'),
                'seconds': _t.seconds, 'over_budget': _over, 'error': _t.error,
                'infra_retries': len(_t.infra_errors), 'infra_errors': list(_t.infra_errors),
                'checks': [{'claim': _c.get('claim') or _c.get('name'), 'ok': _c.get('ok'),
                            'required': _c.get('required', True), 'expr': _c.get('expr', '')}
                           for _c in _t.checks]}
        _row.update({_k: (_t.cost or {}).get(_k) for _k in COST_KEYS})
        if _testgen:
            _row['reason'] = testgen.failure_reason(_t.checks, _t.status, _row['ended'], _over)
            _row['flags'] = testgen.flags(_t.checks, _over)
            _row['mutation'] = _mutation(_t.checks)
        _out.append(_row)
    return _out


_KILLED = re.compile(r'^(\d+)/(\d+) ')


def _mutation(checks) -> Optional[Dict[str, int]]:
    """{killed, tested} of the mutation check (testgen.Result.checks), or None when no mutant was run."""
    _c = next((_x for _x in checks if _x.get('claim') == 'kills mutants of the fixed functions'), None)
    _m = _KILLED.match(str((_c or {}).get('expr') or ''))
    return {'killed': int(_m.group(1)), 'tested': int(_m.group(2))} if _m else None


def budgets_of(dataset) -> Dict[str, Dict[str, float]]:
    """task id -> budget, for tasks read by testgen.load() (meta['budget'])."""
    return {_t.id: dict(_t.meta.get('budget') or {}) for _t in dataset.tasks if isinstance(_t.meta, dict)}


__all__ = ['records', 'budgets_of', 'COST_KEYS']

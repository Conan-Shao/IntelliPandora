# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : report.py
@Time  : 2026-11-05

The evaluation view of the report: same skeleton as the test report
(docs/design/decisions/16 §4), different contents -- a success rate with its
interval instead of pass/fail, "better / worse / indistinguishable" against
the baseline instead of "can ship", judge verdicts shown apart from the
deterministic ones, and the trajectory as the evidence.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from ipandora.core.eval.run import CATEGORY_LABEL, EvalRun
from ipandora.core.eval.stats import BETTER, INDISTINGUISHABLE, WORSE

TEMPLATE = 'conf/static/eval.html'

VERDICT_LABEL = {WORSE: '比基线变差', BETTER: '比基线变好', INDISTINGUISHABLE: '和基线无法区分',
                 'first': '没有基线', 'not_comparable': '和基线不可比'}


def _pct(value) -> str:
    return '—' if value is None else '{:.1f}%'.format(100.0 * value)


def verdict(run: EvalRun, comparison: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The first line. A fixed template over the numbers -- no model writes it."""
    _s = run.summary()
    _rate = _pct(_s['success_rate'])
    if not comparison:
        return {'status': 'first', 'label': VERDICT_LABEL['first'],
                'sentence': '成功率 {}（{} 次试验里 {} 次成功）；没有可对比的基线。'.format(
                    _rate, _s['decided'], _s['successes'])}
    if comparison.get('not_comparable'):
        return {'status': 'not_comparable', 'label': VERDICT_LABEL['not_comparable'],
                'sentence': '成功率 {}；和基线不可比：{}。'.format(
                    _rate, '；'.join(comparison['not_comparable']))}
    _status = comparison['verdict']
    _diff = '{:+.1f} 个百分点'.format(100.0 * comparison['difference'])
    _test = ('McNemar 精确检验 p = {:.3f}'.format(comparison['p'])
             if comparison['test'] == 'mcnemar' else
             '配对 bootstrap 95% 区间 {:+.1f} ~ {:+.1f}'.format(100.0 * comparison['low'],
                                                            100.0 * comparison['high']))
    _what = {WORSE: '判为变差', BETTER: '判为变好', INDISTINGUISHABLE: '无法区分'}[_status]
    return {'status': _status, 'label': VERDICT_LABEL[_status],
            'sentence': '成功率 {}，比基线 {}，{}（{}）。'.format(_rate, _diff, _what, _test)}


def _bar(row: Dict[str, Any], span: float) -> Dict[str, float]:
    """x positions on a 0..260 axis centred on zero, for one difference interval."""
    def _x(v):
        return round(130 + 120 * max(-1.0, min(1.0, v / span)), 1)
    return {'zero': 130, 'low': _x(row['low']), 'high': _x(row['high']), 'mid': _x(row['difference'])}


def context(run: EvalRun, comparison: Optional[Dict[str, Any]] = None,
            title: str = None) -> Dict[str, Any]:
    _s = run.summary()
    _rows = []
    if comparison:
        _span = max([0.1] + [abs(_r[_k]) for _r in comparison['by_tag'] for _k in ('low', 'high')])
        for _r in comparison['by_tag']:
            _rows.append(dict(_r, bar=_bar(_r, _span)))
    else:
        for _tag, _values in sorted(run.tag_values().items()):
            for _value in _values:
                _sub = run.summary(set(run.task_ids(**{_tag: _value})))
                _rows.append({'tag': _tag, 'value': _value, 'tasks': _sub['tasks'],
                              'now_rate': _sub['success_rate'], 'interval': _sub['interval']})
    _failed = [_t for _t in run.trials if _t.success is False or _t.status != 'graded']
    _by_cat = [{'key': _k, 'label': CATEGORY_LABEL.get(_k, _k), 'count': _n}
               for _k, _n in sorted(_s['by_category'].items(), key=lambda _i: -_i[1])]
    return {
        'title': title or '{} 评测报告'.format(run.manifest.dataset or ''),
        'run': run, 'run_id': run.run_id, 'manifest': run.manifest, 'summary': _s,
        'verdict': verdict(run, comparison), 'comparison': comparison or {},
        'tag_rows': _rows, 'by_category': _by_cat, 'failed_trials': _failed[:50],
        'failed_total': len(_failed), 'selfcheck': run.selfcheck,
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'pct': _pct,
        'category_label': CATEGORY_LABEL,
    }


def to_html(run: EvalRun, comparison: Optional[Dict[str, Any]] = None, title: str = None) -> str:
    from ipandora.core.report.render import environment
    return environment().get_template(TEMPLATE).render(**context(run, comparison, title))


def to_dict(run: EvalRun, comparison: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """report.json for an evaluation: the run, plus the verdict and the comparison."""
    _out = run.to_dict()
    _out.update({'view': 'eval', 'verdict': verdict(run, comparison),
                 'comparison': comparison or {}})
    return _out


def write(run: EvalRun, directory: str, comparison: Optional[Dict[str, Any]] = None,
          title: str = None) -> Dict[str, str]:
    os.makedirs(directory, exist_ok=True)
    _html = os.path.join(directory, 'report.html')
    with open(_html, 'w', encoding='utf-8') as fh:
        fh.write(to_html(run, comparison, title))
    _json = os.path.join(directory, 'report.json')
    with open(_json, 'w', encoding='utf-8') as fh:
        json.dump(to_dict(run, comparison), fh, ensure_ascii=False, indent=2, default=str)
    return {'html': _html, 'json': _json}

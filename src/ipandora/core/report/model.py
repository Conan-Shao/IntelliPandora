# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : model.py
@Time  : 2026-08-01
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ipandora.core.triage.category import BLAMES_SYSTEM_UNDER_TEST, LABEL, NEXT_STEP

GROUP_ORDER = ('defect', 'contract', 'unknown', 'environment', 'harness', 'data')
"""Failure groups, the system under test first: that is what blocks a release."""


class Status:
    """
    Case outcomes as a report needs them.

    PASS/FAIL/ERROR/SKIPPED come from the runner. The last two do not, and
    that is the point: a report that only shows what ran cannot show what is
    missing, and what is missing is usually the more interesting question.
    """

    # bandit B105: a status name, not a password
    PASS = 'PASS'  # nosec B105
    FAIL = 'FAIL'
    ERROR = 'ERROR'

    SKIPPED = 'SKIPPED'
    """Preconditions were unmet. An environment or data problem, not a defect."""

    BLOCKED = 'BLOCKED'
    """Written, but never reached because something upstream failed."""

    GAP = 'GAP'
    """
    A check that should exist and does not.

    Never inferred from a run -- a run cannot report an assertion nobody
    wrote. It has to be declared against a requirement. See
    docs/design/decisions/04-实施计划.md.
    """

    UNVERIFIED = 'UNVERIFIED'
    """
    pytest says passed, but the case made no judgement the runner could see:
    no Check, no plain `assert` that held, no pytest.raises. All it showed is
    that nothing raised. Counted as inconclusive, not as a pass.
    """


# Statuses that mean "this told us nothing about the product".
INCONCLUSIVE = frozenset({Status.SKIPPED, Status.BLOCKED, Status.GAP, Status.ERROR,
                          Status.UNVERIFIED})


VERDICT_LABEL = {
    # bandit B105: a verdict name, not a password
    'pass': '可以放行',  # nosec B105
    'review': '通过，但需要复核',
    'fail': '不能放行',
    'error': '没有跑起来',
}
"""
What the first line of a report says. `pass` and `review` both exit 0;
`review` is a pass with something a person should look at before trusting
it -- a weaker judgement, a case that judged nothing, nothing conclusive.
"""

_AXIS_META = ('id', 'title', 'note')


def _value(value) -> Dict[str, str]:
    if isinstance(value, dict):
        _key = str(value.get('key', value.get('label', '')))
        return {'key': _key, 'label': str(value.get('label', _key))}
    return {'key': str(value), 'label': str(value)}


def _axis(key: str, spec) -> Optional[Dict[str, Any]]:
    """One axis, in either the long form or as a plain list of values."""
    if isinstance(spec, dict) and isinstance(spec.get('values'), (list, tuple)):
        return {'key': str(spec.get('key', key)), 'label': str(spec.get('label', spec.get('key', key))),
                'values': [_value(_v) for _v in spec['values']]}
    if isinstance(spec, (list, tuple)):
        return {'key': key, 'label': key, 'values': [_value(_v) for _v in spec]}
    return None


def coverage_axes(group) -> Tuple[Optional[Dict], Optional[Dict], str]:
    """
    (y, x, problem) for one COVERAGE entry.

    Two spellings are accepted. The long one names each axis:

        {'id': 'g', 'title': 'role × channel',
         'y': {'key': 'role', 'label': '角色', 'values': [{'key': 'admin', 'label': '管理员'}, ...]},
         'x': {'key': 'channel', 'values': ['web', 'app']}}

    The short one is just the two dims and their values, rows first:

        {'role': ['admin', 'guest'], 'channel': ['web', 'app']}

    Anything else comes back with a problem instead of an empty grid: a
    declaration the report silently drew as "0 / 0" read as "nothing to
    cover", which is the opposite of what its author meant.
    """
    if not isinstance(group, dict):
        return None, None, 'COVERAGE 的每一项应是 dict，实际是 {}'.format(type(group).__name__)
    if 'x' in group or 'y' in group:
        _y, _x = _axis('y', group.get('y')), _axis('x', group.get('x'))
        if _y is None or _x is None:
            return None, None, "COVERAGE 的 'x' 和 'y' 都要有 values 列表"
        return _y, _x, ''
    _dims = [(_k, _v) for _k, _v in group.items() if _k not in _AXIS_META]
    if len(_dims) != 2:
        return None, None, ('COVERAGE 的简写要正好两个维度，例如 '
                            "{{'role': ['admin', 'guest'], 'channel': ['web', 'app']}}；"
                            '这里有 {} 个：{}'.format(len(_dims), ', '.join(_k for _k, _ in _dims) or '无'))
    _y, _x = _axis(_dims[0][0], _dims[0][1]), _axis(_dims[1][0], _dims[1][1])
    if _y is None or _x is None:
        return None, None, 'COVERAGE 简写里每个维度的值要是列表'
    return _y, _x, ''


def _dim(case, key: str) -> Optional[str]:
    _v = case.dims.get(key)
    return None if _v is None else str(_v)


def _cell_status(cases) -> str:
    """A matrix cell is as bad as its worst case, and empty when there is none."""
    if not cases:
        return 'none'
    _states = {_c.status for _c in cases}
    for _bad in (Status.ERROR, Status.FAIL):
        if _bad in _states:
            return 'fail'
    if _states <= INCONCLUSIVE:
        return 'skip'
    return 'pass'


@dataclass
class ReportCase:
    name: str
    nodeid: str = ''
    status: str = Status.PASS
    duration: float = 0.0
    message: str = ''
    category: str = ''
    """Triage classification, when available."""
    reason: str = ''
    next_step: str = ''
    confidence: str = ''
    """How sure triage is about `category`: high, medium or low."""
    suite: str = ''
    title: str = ''
    """What the case is for, in a sentence. From its docstring."""
    dims: Dict[str, str] = field(default_factory=dict)
    """Where the case sits in the coverage matrix."""
    flaky: str = ''
    """Why this case is known-unstable. Empty means it is not."""
    checks: List[Dict[str, Any]] = field(default_factory=list)
    """Every judgement, as the assertion layer made it -- not re-parsed text."""
    exchanges: List[Dict[str, Any]] = field(default_factory=list)
    """Every HTTP call, request and response."""
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    """
    What a failed web case left behind: {'kind', 'path', 'src', 'command'}.
    A screenshot carries `src`, the image itself, so the report still shows it
    after the run's files are gone; a trace carries the command that opens it.
    """

    @property
    def conclusive(self) -> bool:
        return self.status not in INCONCLUSIVE

    @property
    def judgements(self) -> List[Dict[str, Any]]:
        return [_c for _c in self.checks if _c.get('kind') != 'gap']

    @property
    def gaps(self) -> List[Dict[str, Any]]:
        return [_c for _c in self.checks if _c.get('kind') == 'gap']

    @property
    def checks_passed(self) -> int:
        return sum(1 for _c in self.judgements if _c.get('ok'))

    @property
    def checks_failed(self) -> int:
        return sum(1 for _c in self.judgements if not _c.get('ok'))

    @property
    def slowest_exchange(self) -> Dict[str, Any]:
        """The call worth looking at first when a case is slow."""
        return max(self.exchanges, key=lambda _e: _e.get('ms') or 0.0,
                   default={}) if self.exchanges else {}

    @property
    def exchange_ms(self) -> float:
        return sum((_e.get('ms') or 0.0) for _e in self.exchanges)

    def to_dict(self) -> Dict[str, Any]:
        _out = asdict(self)
        _out.update({
            'checks_passed': self.checks_passed,
            'checks_failed': self.checks_failed,
            'gaps': self.gaps,
        })
        return _out


@dataclass
class ReportData:
    """
    Everything a renderer needs, and nothing that depends on how it renders.

    Producing this and rendering it are separate steps on purpose: the same
    data backs the HTML report, a JSON artifact, and whatever comes next,
    and secrets are stripped once, here, rather than in each template.
    """
    title: str = 'IntelliPandora Test Report'
    run_id: str = ''
    selector: str = ''
    env: str = ''
    generated: str = ''
    duration: float = 0.0
    cases: List[ReportCase] = field(default_factory=list)
    triage: Dict[str, Any] = field(default_factory=dict)
    coverage: List[Dict[str, Any]] = field(default_factory=list)
    """Matrix axes declared by the suite. See `coverage_matrix`."""
    collect_error: str = ''
    baseline: str = ''
    """The judgement inventory the run was compared with, if any."""
    judgement_changes: List[Dict[str, Any]] = field(default_factory=list)
    """Changes in what the suite judges vs the baseline. See runner/inventory.py."""
    against_baseline: Dict[str, List[str]] = field(default_factory=dict)
    """Failures split by the committed baseline: see inventory.against."""
    against_run: Dict[str, Any] = field(default_factory=dict)
    """
    Failures compared with one earlier run, when there is one to compare with:
    a report.json passed in (--compare-with), or the previous run of the same
    selector and environment in the local report archive. See compare.py.
    The framework keeps no history of its own beyond that local archive.
    """
    gate_weakened: bool = False
    """Whether weaker judgements fail this run (--fail-on-weakened)."""
    view: str = 'tests'
    """Which view renders this report: 'tests'. Agent evaluation adds 'eval'."""
    shards: List[Dict[str, Any]] = field(default_factory=list)
    """For a merged report: the runs it was merged from. Empty for a single run. See merge.py."""
    merge_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    """Cases whose outcome differed between shards; the merged case took the most severe."""
    duplicates: int = 0
    """Copies of a case dropped by the merge because another shard had it too."""

    @property
    def weakened(self) -> List[Dict[str, Any]]:
        return [_c for _c in self.judgement_changes if _c.get('weakening')]

    def _count(self, status: str) -> int:
        return sum(1 for _c in self.cases if _c.status == status)

    @property
    def totals(self) -> Dict[str, int]:
        return {
            'total': len(self.cases),
            'passed': self._count(Status.PASS),
            'failed': self._count(Status.FAIL),
            'error': self._count(Status.ERROR),
            'skipped': self._count(Status.SKIPPED),
            'blocked': self._count(Status.BLOCKED),
            'gap': self._count(Status.GAP),
            'unverified': self._count(Status.UNVERIFIED),
        }

    @property
    def pass_rate(self) -> str:
        """
        Share of *conclusive* cases that passed.

        Skips and gaps are excluded rather than counted as passes: a suite
        that skips half its cases is not 100% healthy, and a rate that says so
        is worse than no rate at all.
        """
        _conclusive = [_c for _c in self.cases if _c.conclusive]
        if not _conclusive:
            return 'n/a'
        _passed = sum(1 for _c in _conclusive if _c.status == Status.PASS)
        return '{:.1f}%'.format(_passed * 100.0 / len(_conclusive))

    @property
    def pass_rate_basis(self) -> Dict[str, Any]:
        """The numbers behind `pass_rate`, so nobody has to guess the denominator."""
        _conclusive = [_c for _c in self.cases if _c.conclusive]
        _not_counted = {}
        for _case in self.cases:
            if not _case.conclusive:
                _key = _case.status.lower()
                _not_counted[_key] = _not_counted.get(_key, 0) + 1
        return {'passed': sum(1 for _c in _conclusive if _c.status == Status.PASS),
                'denominator': len(_conclusive),
                'not_counted': _not_counted}

    @property
    def verdict(self) -> Dict[str, Any]:
        """
        The report's first line: can this run be trusted, and why.

        Built from counts by a fixed template -- no model writes it. It agrees
        with the exit code: `releasable` is false exactly when `ipandora run`
        exits non-zero.
        """
        _bad = self.failures
        _blames = sum(1 for _c in _bad if _c.category in BLAMES_SYSTEM_UNDER_TEST)
        _unverified = self._count(Status.UNVERIFIED)
        _weak = len(self.weakened)
        _parts, _reasons = [], []

        if self.collect_error:
            _status = 'error'
            _parts.append('收集用例时出错，这次没有得到任何结论')
            _reasons.append({'kind': 'collect_error', 'count': 1})
        elif not self.cases:
            _status = 'error'
            _parts.append('没有用例运行')
            _reasons.append({'kind': 'no_cases', 'count': 0})
        else:
            if _bad:
                _text = '{} 条用例失败'.format(len(_bad))
                if _blames == len(_bad):
                    _text += '，都指向被测系统'
                elif _blames:
                    _text += '，其中 {} 条指向被测系统'.format(_blames)
                else:
                    _text += '，没有一条指向被测系统'
                _parts.append(_text)
                _reasons.append({'kind': 'failed', 'count': len(_bad),
                                 'blames_system_under_test': _blames})
            if _weak:
                _parts.append('{} 处判定比基线弱'.format(_weak))
                _reasons.append({'kind': 'weakened', 'count': _weak, 'gated': self.gate_weakened})
            if _unverified:
                _parts.append('{} 条用例通过了但什么都没判定'.format(_unverified))
                _reasons.append({'kind': 'unverified', 'count': _unverified})
            if self.merge_conflicts:
                _parts.append('{} 条用例在分片之间结论不一致'.format(len(self.merge_conflicts)))
                _reasons.append({'kind': 'conflict', 'count': len(self.merge_conflicts)})
            _passed = self._count(Status.PASS)
            if not _bad and not _passed:
                _parts.append('没有一条用例给出结论')
                _reasons.append({'kind': 'nothing_conclusive', 'count': 0})

            if _bad or (_weak and self.gate_weakened):
                _status = 'fail'
            elif _reasons:
                _status = 'review'
            else:
                _status = 'pass'
                _parts.append('{} 条用例全部通过{}'.format(
                    _passed, '，判定没有比基线弱' if self.baseline else ''))

        return {'status': _status, 'label': VERDICT_LABEL[_status],
                'releasable': _status in ('pass', 'review'),
                'sentence': '；'.join(_parts) + '。', 'reasons': _reasons}

    @property
    def ok(self) -> bool:
        return not self.collect_error and not self._count(Status.FAIL) \
            and not self._count(Status.ERROR)

    @property
    def failures(self) -> List[ReportCase]:
        return [_c for _c in self.cases
                if _c.status in (Status.FAIL, Status.ERROR)]

    @property
    def inconclusive(self) -> List[ReportCase]:
        """Cases that told us nothing -- the ones a summary tends to hide."""
        return [_c for _c in self.cases if _c.status in INCONCLUSIVE]

    @property
    def flaky(self) -> List[ReportCase]:
        """
        Cases declared known-unstable, whatever they did this time.

        Listed even when they pass: a case that is green today and red
        tomorrow is the thing being tracked, so one green run is not news.
        """
        return [_c for _c in self.cases if _c.flaky]

    @property
    def weakened_by_case(self) -> Dict[str, int]:
        _out = {}
        for _change in self.weakened:
            _out[_change.get('nodeid', '')] = _out.get(_change.get('nodeid', ''), 0) + 1
        return _out

    @property
    def attention(self) -> List[Dict[str, Any]]:
        """
        Cases someone should look at, grouped by what triage blamed.

        Failures and triaged skips go under their category. Passes that are
        not evidence -- judged nothing, known-unstable, or judging less than
        the baseline -- form one last group: they exit 0, so this is the only
        place they are said out loud.
        """
        _by = {}
        for _case in self.cases:
            if _case.status in (Status.FAIL, Status.ERROR) \
                    or (_case.status == Status.SKIPPED and _case.category):
                _by.setdefault(_case.category or 'unknown', []).append(_case)
        _groups = []
        for _key in list(GROUP_ORDER) + sorted(set(_by) - set(GROUP_ORDER)):
            if _key in _by:
                _groups.append({'key': _key, 'label': LABEL.get(_key, _key),
                                'next_step': NEXT_STEP.get(_key, ''),
                                'blames_system_under_test': _key in BLAMES_SYSTEM_UNDER_TEST,
                                'cases': _by[_key]})
        _weak = self.weakened_by_case
        _untrusted = [_c for _c in self.cases
                      if _c.status == Status.UNVERIFIED
                      or (_c.status == Status.PASS and (_c.flaky or _c.nodeid in _weak))]
        if _untrusted:
            _groups.append({'key': 'untrusted', 'label': '通过但不可信',
                            'next_step': '这些“通过”不该算进放行依据',
                            'blames_system_under_test': False, 'cases': _untrusted})
        return _groups

    @property
    def by_suite(self) -> Dict[str, List[ReportCase]]:
        _grouped = {}
        for _case in self.cases:
            _grouped.setdefault(_case.suite or 'default', []).append(_case)
        return _grouped

    @property
    def gaps(self) -> List[Dict[str, Any]]:
        """
        Declared gaps across the whole run, deduplicated with a count.

        Aggregated on purpose: one case saying "row not checked in the DB" is a
        note, twelve cases saying it is the next thing to go build.
        """
        _seen = {}
        for _case in self.cases:
            for _gap in _case.gaps:
                _key = (_gap.get('name', ''), _gap.get('src', ''))
                _entry = _seen.setdefault(_key, {
                    'name': _gap.get('name', ''),
                    'expr': _gap.get('expr', ''),
                    'src': _gap.get('src', ''),
                    'count': 0, 'cases': []})
                _entry['count'] += 1
                _entry['cases'].append(_case.name)
        return sorted(_seen.values(), key=lambda _g: -_g['count'])

    @property
    def check_totals(self) -> Dict[str, int]:
        """Judgements, not cases. A suite can pass every case and still barely
        check anything -- this is where that shows."""
        return {
            'passed': sum(_c.checks_passed for _c in self.cases),
            'failed': sum(_c.checks_failed for _c in self.cases),
            'gap': sum(len(_c.gaps) for _c in self.cases),
        }

    @property
    def by_source(self) -> Dict[str, Dict[str, int]]:
        """
        Judgements broken down by the dimension they came from.

        A suite that only ever produces `api` checks is testing that the
        endpoint answered, not that it was right. The breakdown makes that
        visible without reading a single case.
        """
        _out = {}
        for _case in self.cases:
            for _check in _case.judgements:
                _slot = _out.setdefault(_check.get('src') or 'derived',
                                        {'passed': 0, 'failed': 0})
                _slot['passed' if _check.get('ok') else 'failed'] += 1
            for _gap in _case.gaps:
                _slot = _out.setdefault(_gap.get('src') or 'derived',
                                        {'passed': 0, 'failed': 0})
                _slot['gap'] = _slot.get('gap', 0) + 1
        return _out

    @property
    def coverage_matrix(self) -> List[Dict[str, Any]]:
        """
        The declared axes filled in with what actually ran.

        An empty cell is the reason this exists: it is a combination nobody
        wrote a test for, and no list of passing cases can show it. The axes
        have to be declared separately from the tests for exactly that reason
        -- a run can only report the cells it has, never the ones it lacks.
        """
        _grids = []
        for _index, _group in enumerate(self.coverage or []):
            _y, _x, _problem = coverage_axes(_group)
            _meta = _group if isinstance(_group, dict) else {}
            if _problem:
                _grids.append({'id': str(_meta.get('id', _index)), 'title': str(_meta.get('title', '')),
                               'note': str(_meta.get('note', '')), 'y_label': '', 'x_labels': [],
                               'rows': [], 'filled': 0, 'total': 0, 'problem': _problem})
                continue
            _rows, _filled = [], 0
            for _yv in _y['values']:
                _cells = []
                for _xv in _x['values']:
                    _hit = [_c for _c in self.cases
                            if _dim(_c, _y['key']) == _yv['key']
                            and _dim(_c, _x['key']) == _xv['key']]
                    if _hit:
                        _filled += 1
                    _cells.append({
                        'label': _xv['label'],
                        'cases': [{'name': _c.name, 'nodeid': _c.nodeid,
                                   'status': _c.status} for _c in _hit],
                        'status': _cell_status(_hit),
                    })
                _rows.append({'label': _yv['label'], 'cells': _cells})
            _grids.append({
                'id': str(_meta.get('id', _index)),
                'title': str(_meta.get('title') or '{} × {}'.format(_y['label'], _x['label'])),
                'note': str(_meta.get('note', '')),
                'y_label': _y['label'],
                'x_labels': [_v['label'] for _v in _x['values']],
                'rows': _rows,
                'filled': _filled,
                'total': len(_y['values']) * len(_x['values']),
                'problem': '',
            })
        return _grids

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'run_id': self.run_id,
            'selector': self.selector,
            'env': self.env,
            'generated': self.generated,
            'duration': round(self.duration, 3),
            'ok': self.ok,
            'view': self.view,
            'verdict': self.verdict,
            'totals': self.totals,
            'pass_rate': self.pass_rate,
            'pass_rate_basis': self.pass_rate_basis,
            'collect_error': self.collect_error,
            'baseline': self.baseline,
            'judgement_changes': self.judgement_changes,
            'weakened': len(self.weakened),
            'against_baseline': self.against_baseline,
            'against_run': self.against_run,
            'triage': self.triage,
            'check_totals': self.check_totals,
            'by_source': self.by_source,
            'gaps': self.gaps,
            'coverage': self.coverage_matrix,
            # the declarations themselves, so a report rebuilt from this JSON
            # -- a merge of several -- can draw the matrix again
            'coverage_axes': self.coverage,
            'shards': self.shards,
            'merge_conflicts': self.merge_conflicts,
            'duplicates': self.duplicates,
            'flaky': [{'name': _c.name, 'nodeid': _c.nodeid,
                       'status': _c.status, 'reason': _c.flaky}
                      for _c in self.flaky],
            'cases': [_c.to_dict() for _c in self.cases],
        }

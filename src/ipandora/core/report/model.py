# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : model.py
@Time  : 2026-08-01
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


class Status:
    """
    Case outcomes as a report needs them.

    PASS/FAIL/ERROR/SKIPPED come from the runner. The last two do not, and
    that is the point: a report that only shows what ran cannot show what is
    missing, and what is missing is usually the more interesting question.
    """

    PASS = 'PASS'
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
    docs/design/04-实施计划.md.
    """


# Statuses that mean "this told us nothing about the product".
INCONCLUSIVE = frozenset({Status.SKIPPED, Status.BLOCKED, Status.GAP, Status.ERROR})


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
    suite: str = ''
    title: str = ''
    """What the case is for, in a sentence. From its docstring."""
    dims: Dict[str, str] = field(default_factory=dict)
    """Where the case sits in the coverage matrix."""
    checks: List[Dict[str, Any]] = field(default_factory=list)
    """Every judgement, as the assertion layer made it -- not re-parsed text."""
    exchanges: List[Dict[str, Any]] = field(default_factory=list)
    """Every HTTP call, request and response."""

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
    def by_suite(self) -> Dict[str, List[ReportCase]]:
        _grouped = {}
        for _case in self.cases:
            _grouped.setdefault(_case.suite or 'default', []).append(_case)
        return _grouped

    @property
    def gaps(self) -> List[Dict[str, Any]]:
        """
        Declared gaps across the whole run, deduplicated with a count.

        Aggregated on purpose: one case saying "balance not verified" is a
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
        for _group in self.coverage or []:
            _y, _x = _group.get('y', {}), _group.get('x', {})
            _rows, _filled = [], 0
            for _yv in _y.get('values', []):
                _cells = []
                for _xv in _x.get('values', []):
                    _hit = [_c for _c in self.cases
                            if _c.dims.get(_y.get('key')) == _yv.get('key')
                            and _c.dims.get(_x.get('key')) == _xv.get('key')]
                    if _hit:
                        _filled += 1
                    _cells.append({
                        'label': _xv.get('label', ''),
                        'cases': [{'name': _c.name, 'nodeid': _c.nodeid,
                                   'status': _c.status} for _c in _hit],
                        'status': _cell_status(_hit),
                    })
                _rows.append({'label': _yv.get('label', ''), 'cells': _cells})
            _total = max(len(_y.get('values', [])) * len(_x.get('values', [])), 0)
            _grids.append({
                'id': _group.get('id', ''),
                'title': _group.get('title', ''),
                'note': _group.get('note', ''),
                'y_label': _y.get('label', ''),
                'x_labels': [_v.get('label', '') for _v in _x.get('values', [])],
                'rows': _rows,
                'filled': _filled,
                'total': _total,
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
            'totals': self.totals,
            'pass_rate': self.pass_rate,
            'collect_error': self.collect_error,
            'triage': self.triage,
            'check_totals': self.check_totals,
            'by_source': self.by_source,
            'gaps': self.gaps,
            'coverage': self.coverage_matrix,
            'cases': [_c.to_dict() for _c in self.cases],
        }

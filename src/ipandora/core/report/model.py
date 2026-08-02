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

    @property
    def conclusive(self) -> bool:
        return self.status not in INCONCLUSIVE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
            'cases': [_c.to_dict() for _c in self.cases],
        }

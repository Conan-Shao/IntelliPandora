# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : result.py
@Time  : 2026-08-01
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

PASSED = 'passed'
FAILED = 'failed'
SKIPPED = 'skipped'
ERROR = 'error'

# How much of a failure message travels in the agent-facing summary. The full
# text is kept in the run store and fetched deliberately -- dumping thousands
# of lines of traceback into an agent's context is the classic mistake here.
SUMMARY_MESSAGE_CHARS = 400


@dataclass
class CaseResult:
    nodeid: str
    outcome: str
    duration: float = 0.0
    message: str = ''
    """Short, human-readable reason. Empty when the case passed."""
    detail: str = ''
    """Full traceback. Kept out of summaries on purpose."""

    @property
    def name(self) -> str:
        """The test name without its file path."""
        return self.nodeid.split('::')[-1] if '::' in self.nodeid else self.nodeid

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    run_id: str
    selector: str = ''
    env: str = ''
    duration: float = 0.0
    exit_code: int = 0
    cases: List[CaseResult] = field(default_factory=list)
    collect_error: str = ''
    """Set when pytest could not even collect the selector."""

    def _count(self, outcome: str) -> int:
        return sum(1 for _c in self.cases if _c.outcome == outcome)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return self._count(PASSED)

    @property
    def failed(self) -> int:
        return self._count(FAILED)

    @property
    def skipped(self) -> int:
        return self._count(SKIPPED)

    @property
    def errors(self) -> int:
        return self._count(ERROR)

    @property
    def ok(self) -> bool:
        return not self.collect_error and self.failed == 0 and self.errors == 0

    @property
    def failures(self) -> List[CaseResult]:
        return [_c for _c in self.cases if _c.outcome in (FAILED, ERROR)]

    def headline(self) -> str:
        _parts = []
        for _label, _count in (('passed', self.passed), ('failed', self.failed),
                               ('skipped', self.skipped), ('error', self.errors)):
            if _count:
                _parts.append('{} {}'.format(_count, _label))
        return ', '.join(_parts) or 'no tests ran'

    def summary(self) -> Dict[str, Any]:
        """
        The agent-facing view: enough to decide what to do next, not the whole
        run log. Full detail stays behind `explain_failure(run_id)`.
        """
        _out = {
            'run_id': self.run_id,
            'selector': self.selector,
            'env': self.env,
            'ok': self.ok,
            'summary': self.headline(),
            'duration': round(self.duration, 3),
            'totals': {'total': self.total, 'passed': self.passed,
                       'failed': self.failed, 'skipped': self.skipped,
                       'error': self.errors},
        }
        if self.collect_error:
            _out['collect_error'] = self.collect_error[:SUMMARY_MESSAGE_CHARS]
            return _out
        if self.failures:
            _out['failures'] = [
                {'case': _c.name,
                 'nodeid': _c.nodeid,
                 'outcome': _c.outcome,
                 'message': _c.message[:SUMMARY_MESSAGE_CHARS]}
                for _c in self.failures]
            _out['detail_hint'] = (
                'call explain_failure("{}") for the full context'.format(self.run_id))
        return _out

    def to_dict(self) -> Dict[str, Any]:
        """Everything, including full tracebacks. For the run store, not agents."""
        return {
            'run_id': self.run_id,
            'selector': self.selector,
            'env': self.env,
            'duration': self.duration,
            'exit_code': self.exit_code,
            'collect_error': self.collect_error,
            'totals': {'total': self.total, 'passed': self.passed,
                       'failed': self.failed, 'skipped': self.skipped,
                       'error': self.errors},
            'cases': [_c.to_dict() for _c in self.cases],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RunResult':
        return cls(
            run_id=data.get('run_id', ''),
            selector=data.get('selector', ''),
            env=data.get('env', ''),
            duration=data.get('duration', 0.0),
            exit_code=data.get('exit_code', 0),
            collect_error=data.get('collect_error', ''),
            cases=[CaseResult(**_c) for _c in data.get('cases', [])])

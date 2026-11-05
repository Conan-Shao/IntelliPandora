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

# How many nodeids a summary list carries before it stops; the run store has all.
SUMMARY_LIST_MAX = 20


@dataclass
class CaseResult:
    nodeid: str
    outcome: str
    duration: float = 0.0
    message: str = ''
    """Short, human-readable reason. Empty when the case passed."""
    detail: str = ''
    """Full traceback. Kept out of summaries on purpose."""
    checks: List[Dict[str, Any]] = field(default_factory=list)
    """Every judgement the case made, as the assertion layer produced it."""
    exchanges: List[Dict[str, Any]] = field(default_factory=list)
    """Every HTTP call the case made, request and response."""
    dims: Dict[str, str] = field(default_factory=dict)
    flaky: str = ''
    """Why this case is known-unstable. Empty means it is not."""
    """Coverage coordinates, from @pytest.mark.dims."""
    title: str = ''
    """Human-readable intent, from the test's docstring."""
    judgeable: bool = True
    """
    Whether the runner can see this case's judgements. False for unittest
    and doctest items, whose assertEqual / expected-output checks are not
    `assert` statements -- calling those unverified would be a false alarm.
    """

    @property
    def unverified(self) -> bool:
        """
        Passed without making a single judgement the runner could see.

        pytest counts `def test_x(): call_api()` as a pass. Nothing was
        checked except that no exception escaped, and the report should say
        so instead of adding it to the pass rate. A declared gap counts as a
        statement about the case, so a case with only gaps is not this.
        """
        return self.outcome == PASSED and self.judgeable and not self.checks

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
    coverage: List[Dict[str, Any]] = field(default_factory=list)
    """Coverage axes declared by the suite, for the matrix. See COVERAGE."""
    collect_error: str = ''
    deselected: List[str] = field(default_factory=list)
    """Cases a -m expression removed, e.g. --exclude-flaky."""
    baseline: str = ''
    """The judgement inventory this run was compared with. Empty: none."""
    judgement_changes: List[Dict[str, Any]] = field(default_factory=list)
    """What changed in what the suite judges, vs the baseline. See inventory.py."""

    @property
    def weakened(self) -> List[Dict[str, Any]]:
        """The changes that make this pass weaker than the baseline's."""
        return [_c for _c in self.judgement_changes if _c.get('weakening')]

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
    def unverified(self) -> List[CaseResult]:
        """Passed, but judged nothing. Still counted in `passed`; see CaseResult."""
        return [_c for _c in self.cases if _c.unverified]

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
        if self.unverified:
            # said next to "passed" because that is where it hides
            _parts.append('{} unverified'.format(len(self.unverified)))
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
                       'error': self.errors, 'unverified': len(self.unverified)},
        }
        if self.unverified:
            _out['unverified'] = [_c.nodeid for _c in self.unverified][:SUMMARY_LIST_MAX]
            _out['unverified_hint'] = (
                'these passed without making any judgement -- add assertions, '
                'or declare gap() if the omission is deliberate')
        if self.judgement_changes:
            _out['judgements_weakened'] = bool(self.weakened)
            _out['judgement_changes'] = [
                _c['line'] for _c in (self.weakened or self.judgement_changes)][:SUMMARY_LIST_MAX]
            if self.weakened:
                _out['judgement_hint'] = (
                    'judgements got weaker than the baseline ({}). If that is '
                    'intended, a person should review it and accept it with '
                    '`ipandora run --update-baseline`; otherwise restore '
                    'them.'.format(self.baseline))
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
            'deselected': list(self.deselected),
            'baseline': self.baseline,
            'judgement_changes': list(self.judgement_changes),
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
            deselected=list(data.get('deselected', []) or []),
            baseline=data.get('baseline', ''),
            judgement_changes=list(data.get('judgement_changes', []) or []),
            cases=[CaseResult(**_c) for _c in data.get('cases', [])])

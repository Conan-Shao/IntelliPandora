# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : trial.py
@Time  : 2026-11-05

One attempt at one task, and how it is scored.

Graders return Checks -- the same values every other judgement in the
framework is made of. A trial is *successful* when every required check
holds; its *score* is the weighted share of checks that hold. Both are
reported, because "all or nothing" and "how close" answer different
questions (docs/design/decisions/13 §5).

A model-judge check (src='llm_judge') is shown but takes no part in success
or score until it has been calibrated against people. A judge that answers
"uncertain" leaves the trial without a verdict on that point, like a case that
judged nothing -- it is not counted as a pass or a fail.

A trial that never got to the agent's answer -- the sandbox did not start, the
harness timed out -- is an infrastructure outcome. It is counted separately
and never as the agent failing.
"""
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ipandora.core.assertion.check import Check

LLM_JUDGE = 'llm_judge'

GRADED = 'graded'
"""The agent answered and graders judged the answer."""
INFRA = 'infra'
"""The trial did not produce an answer for reasons outside the agent: sandbox, timeout, network."""
NO_VERDICT = 'no_verdict'
"""The agent answered, but no grader made a deterministic judgement about it."""


@dataclass(frozen=True)
class Graded:
    """
    A Check with how much it counts.

    required: the trial fails when it does not hold.
    weight:   its share of the partial score.
    uncertain: a judge that would not decide. Counts for nothing either way.
    """
    check: Check
    weight: float = 1.0
    required: bool = True
    uncertain: bool = False


def _graded(item) -> Graded:
    if isinstance(item, Graded):
        return item
    if isinstance(item, Check):
        return Graded(item)
    raise TypeError('a grader returns Check or Graded objects, got {!r}'.format(type(item).__name__))


@dataclass
class AgentResult:
    """What an agent run hands back. Agents may also just return the output."""
    output: Any = None
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    """Events in order: {'t': seconds, 'kind': 'message'|'tool'|'result', 'role', 'name', 'text', 'error'}."""
    cost: Dict[str, float] = field(default_factory=dict)
    """usd, tokens_in, tokens_out, turns, tool_calls -- whatever the harness knows."""
    is_reference: bool = False
    """
    A task's reference solution, handed to the grader by selfcheck. A grader
    may replay one written as tool calls; an agent's output is never replayed.
    """
    setup: Any = None
    """
    What the harness planted for this trial (standard.prepare): handed to the
    grader, never recorded. Its mask() is applied to everything recorded of
    the trial, so a canary it planted reaches no report.
    """


class TaskError(ValueError):
    """
    The task, not the agent or the grader: an `expected` or `initial_state`
    that cannot be read. A trial that raises it is attributed to the task.
    """


def _plain(value: Any, _depth: int = 0) -> Any:
    """JSON-shaped data as is; anything else as its repr."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth > 50:
        return repr(value)
    if isinstance(value, dict):
        return {str(_k): _plain(_v, _depth + 1) for _k, _v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(_v, _depth + 1) for _v in value]
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 -- a repr that raises is still an output to record
        return '<{} object>'.format(type(value).__name__)


@dataclass
class Trial:
    task_id: str
    index: int
    status: str = GRADED
    checks: List[Dict[str, Any]] = field(default_factory=list)
    """Every judgement: Check fields plus weight, required, uncertain."""
    output: Any = None
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    cost: Dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0
    error: str = ''
    """Why an infrastructure trial ended, or why grading itself failed."""
    category: str = ''
    """Failure attribution: agent, infra, task, grader -- or '' when not decided by rule."""

    @staticmethod
    def check_dict(graded: Graded) -> Dict[str, Any]:
        _c = graded.check
        return {'name': _c.name, 'ok': _c.ok, 'expr': _c.expr, 'src': _c.src, 'kind': _c.kind,
                'claim': _c.claim, 'weight': graded.weight, 'required': graded.required,
                'uncertain': graded.uncertain}

    def _counted(self) -> List[Dict[str, Any]]:
        """The checks that decide success and score: deterministic, decided, not gaps."""
        return [_c for _c in self.checks
                if _c.get('src') != LLM_JUDGE and not _c.get('uncertain')
                and _c.get('kind') != 'gap']

    @property
    def success(self) -> Optional[bool]:
        """None when there is nothing to decide on: an infra trial, or no verdict."""
        if self.status != GRADED:
            return None
        _required = [_c for _c in self._counted() if _c.get('required', True)]
        if not _required:
            return None
        return all(_c.get('ok') for _c in _required)

    @property
    def score(self) -> Optional[float]:
        # A trial judged only by optional checks has no success verdict but
        # does have a score; it was dropped from mean_score. No score only
        # when nothing was judged: the harness failed, or the grader raised.
        if self.status == INFRA or self.category == 'grader':
            return None
        _counted = self._counted()
        _total = sum(float(_c.get('weight', 1.0)) for _c in _counted)
        if not _total:
            return None
        return sum(float(_c.get('weight', 1.0)) for _c in _counted if _c.get('ok')) / _total

    @property
    def judge_checks(self) -> List[Dict[str, Any]]:
        return [_c for _c in self.checks if _c.get('src') == LLM_JUDGE]

    def to_dict(self) -> Dict[str, Any]:
        """
        Plain data. Not asdict(): it deep-copies every field, and an agent's
        output is whatever the agent returned -- a client object, a generator,
        something holding a lock -- which raised on copy and lost the run.
        Anything that is not JSON data is kept as its repr.
        """
        return {'task_id': self.task_id, 'index': self.index, 'status': self.status,
                'checks': [dict(_c) for _c in self.checks], 'output': _plain(self.output),
                'trajectory': [_plain(_e) for _e in self.trajectory],
                'cost': _plain(self.cost), 'seconds': self.seconds, 'error': self.error,
                'category': self.category, 'success': self.success, 'score': self.score}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Trial':
        _fields = set(cls.__dataclass_fields__)
        return cls(**{_k: _v for _k, _v in data.items() if _k in _fields})


@dataclass
class Manifest:
    """
    Everything a score depends on, recorded with it.

    Without this a score cannot be reproduced or compared: on the same model
    and tasks, changing only the sandbox's resources moved Terminal-Bench 2.0
    success by 6 points (docs/design/decisions/13 §3).
    """
    dataset: str = ''
    dataset_version: str = ''
    dataset_hash: str = ''
    dataset_description: str = ''
    dataset_meta: Dict[str, Any] = field(default_factory=dict)
    """The dataset's own description and meta (source, licence...): what was measured, in its words."""
    split: str = ''
    """'dev', 'test', or '' for both."""
    harness: str = ''
    """What the agent runs in: 'claude-code 2.3', 'my-agent@abc123'."""
    model: str = ''
    config: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    """cpu, memory, per-trial timeout -- fixed and written down."""
    user_simulator: str = ''
    seed: Optional[int] = None
    trials: int = 1
    framework: str = ''
    python: str = field(default_factory=platform.python_version)
    started: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    def comparable_with(self, other: 'Manifest') -> List[str]:
        """What differs in a way that makes two runs' scores not comparable."""
        _out = []
        if self.dataset_hash and other.dataset_hash and self.dataset_hash != other.dataset_hash:
            _out.append('数据集内容不同（哈希 {} ≠ {}）'.format(self.dataset_hash[:12],
                                                          other.dataset_hash[:12]))
        if self.split != other.split:
            _out.append('数据集划分不同（{} ≠ {}）'.format(self.split or '全部', other.split or '全部'))
        if self.resources != other.resources:
            _out.append('沙箱资源不同')
        # the user is part of what is measured: an agent that does well with a
        # scripted user and badly with a model playing one has not regressed
        if self.user_simulator and other.user_simulator and self.user_simulator != other.user_simulator:
            _out.append('模拟用户不同（{} ≠ {}）'.format(self.user_simulator, other.user_simulator))
        return _out

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Manifest':
        _fields = set(cls.__dataclass_fields__)
        return cls(**{_k: _v for _k, _v in (data or {}).items() if _k in _fields})


def framework_version() -> str:
    try:
        from ipandora.version import get_latest_version
        import os
        return get_latest_version(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
    except Exception:  # noqa: BLE001 -- the manifest is still useful without it
        return ''

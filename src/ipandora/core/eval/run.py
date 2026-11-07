# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : run.py
@Time  : 2026-11-05

Running an evaluation: every task, k times, graded, with the numbers.

    from ipandora.core.eval import dataset, evaluate

    run = evaluate(dataset.load('evals/coding.yaml'), agent=my_agent, grade=my_grader,
                   trials=5, split='test', workers=4)
    run.summary()['success_rate']

`agent(task)` returns the answer -- an AgentResult with its trajectory and
cost, or just the output. `grade(task, result)` returns Checks (or Graded).
Agents and graders are plain Python; this is the pytest path of
docs/design/decisions/13 §3. Coding agents in a container sandbox take the
Inspect path, whose logs are read into the same EvalRun.

An exception raised by the agent is an infrastructure outcome: the harness
did not produce an answer. An agent that answers wrongly must say so in its
output, where the graders judge it. An exception raised by a grader is the
grader's problem and is attributed to it.
"""
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ipandora.core.eval import stats
from ipandora.core.eval.dataset import Dataset, Task
from ipandora.core.eval.trial import (GRADED, INFRA, NO_VERDICT, AgentResult, Manifest, TaskError, Trial,
                                      _graded, framework_version)

# failure attribution, decided by rule where a rule can decide (13 §6)
AGENT, INFRASTRUCTURE, TASK, GRADER = 'agent', 'infra', 'task', 'grader'
CATEGORY_LABEL = {AGENT: 'agent 的问题', INFRASTRUCTURE: '基础设施', TASK: '任务有问题',
                  GRADER: '评分器有问题', '': '待人工阅读'}


def _result(value) -> AgentResult:
    return value if isinstance(value, AgentResult) else AgentResult(output=value)


def grade_one(task: Task, result: AgentResult, grade: Callable) -> List[Dict[str, Any]]:
    """Run a grader and turn what it returns into check dicts. Raises what the grader raises."""
    _out = grade(task, result)
    if _out is None:
        return []
    if not isinstance(_out, (list, tuple)):
        _out = [_out]
    return [Trial.check_dict(_graded(_c)) for _c in _out]


def run_trial(task: Task, index: int, agent: Callable, grade: Callable,
              broken_tasks=frozenset()) -> Trial:
    _start = time.perf_counter()
    try:
        _result_value = _result(agent(task))
    except Exception as exc:  # noqa: BLE001 -- any harness failure is an outcome to report
        return Trial(task_id=task.id, index=index, status=INFRA, category=INFRASTRUCTURE,
                     seconds=round(time.perf_counter() - _start, 3),
                     error='{}: {}'.format(type(exc).__name__, exc))
    _seconds = round(time.perf_counter() - _start, 3)
    _trial = Trial(task_id=task.id, index=index, output=_result_value.output,
                   trajectory=list(_result_value.trajectory or []),
                   cost=dict(_result_value.cost or {}), seconds=_seconds)
    try:
        _trial.checks = grade_one(task, _result_value, grade) + _budget_checks(task, _trial)
    except Exception as exc:  # noqa: BLE001 -- the grader is under test too
        # a task the grader cannot read is the task's fault, not the grader's
        _trial.status, _trial.category = NO_VERDICT, TASK if isinstance(exc, TaskError) else GRADER
        _trial.error = 'grader raised {}: {}\n{}'.format(
            type(exc).__name__, exc, traceback.format_exc(limit=3))
        return _trial
    if _trial.success is None:
        _trial.status = NO_VERDICT
    elif not _trial.success:
        _trial.category = TASK if task.id in broken_tasks else AGENT
    return _trial


BUDGET = 'budget'
"""Check.src of the budget judgements this module adds."""


def _budget_checks(task: Task, trial: Trial) -> List[Dict[str, Any]]:
    """
    The task's budget as required judgements: time taken, and any cost the
    agent reported under the same key (`usd`, `tokens_in`, ...).

    The budget was written into datasets and documented, and nothing read
    it: an agent that took ten times as long, or spent ten times as much,
    succeeded all the same. A run cannot be stopped from here -- the agent is
    a function call -- so an overrun is judged afterwards: the answer may be
    right, but not within what the task allows.
    """
    _out = []
    for _key, _limit in sorted((task.budget or {}).items()):
        try:
            _limit = float(_limit)
        except (TypeError, ValueError):
            continue
        _used = trial.seconds if _key == 'seconds' else (trial.cost or {}).get(_key)
        if not isinstance(_used, (int, float)) or isinstance(_used, bool):
            continue                    # not reported: nothing to judge
        _out.append({'name': '预算内：{}'.format(_key), 'ok': _used <= _limit,
                     'expr': '{} = {:g}（上限 {:g}）'.format(_key, _used, _limit), 'src': BUDGET,
                     'kind': 'assert', 'claim': 'budget {} <= {:g}'.format(_key, _limit),
                     'weight': 1.0, 'required': True, 'uncertain': False})
    return _out


def selfcheck(dataset: Dataset, grade: Callable) -> List[Dict[str, Any]]:
    """
    Grade every task's reference solution. Each must pass every required
    check; one that does not means the task or the grader is wrong, and any
    agent failing that task is not the agent's fault.

    Returns one problem per task that fails: {'task_id', 'kind', 'problem',
    'checks'}. kind is 'fails' (the reference does not pass), 'grader' (the
    grader raised or judged nothing), 'task' (the grader could not read the
    task: TaskError), or 'missing' (no reference to check -- reported, but it
    proves nothing about the task).
    """
    _problems = []
    for _task in dataset.tasks:
        _reference = dataset.reference(_task)
        if _reference is None:
            _problems.append({'task_id': _task.id, 'kind': 'missing', 'problem': '没有参考解',
                              'checks': []})
            continue
        try:
            _checks = grade_one(_task, AgentResult(output=_reference, is_reference=True), grade)
        except TaskError as exc:
            _problems.append({'task_id': _task.id, 'kind': 'task', 'checks': [],
                              'problem': '任务写法有误：{}'.format(exc)})
            continue
        except Exception as exc:  # noqa: BLE001
            _problems.append({'task_id': _task.id, 'kind': 'grader', 'checks': [],
                              'problem': '评分器在参考解上报错：{}: {}'.format(type(exc).__name__, exc)})
            continue
        _probe = Trial(task_id=_task.id, index=0, checks=_checks)
        if _probe.success is None:
            _problems.append({'task_id': _task.id, 'kind': 'grader', 'checks': _checks,
                              'problem': '评分器对参考解没有给出任何确定性判定'})
        elif not _probe.success:
            _problems.append({'task_id': _task.id, 'kind': 'fails',
                              'checks': [_c for _c in _checks if not _c['ok']],
                              'problem': '参考解判不过'})
    return _problems


POLARITY_TAG = 'polarity'


def _value_of(task: Dict[str, Any], key: str):
    if key == POLARITY_TAG and key not in (task.get('tags') or {}):
        return task.get('polarity') or 'do'
    return (task.get('tags') or {}).get(key)


@dataclass
class EvalRun:
    run_id: str
    manifest: Manifest = field(default_factory=Manifest)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    """id, tags, polarity, split of each task -- enough to group without the dataset."""
    trials: List[Trial] = field(default_factory=list)
    selfcheck: List[Dict[str, Any]] = field(default_factory=list)
    duration: float = 0.0

    # -- per task -------------------------------------------------------------

    def outcomes(self, task_ids=None, partial: bool = False) -> Dict[str, List[float]]:
        """task id -> success (1/0) or score of each decided trial. Infra and no-verdict trials are left out."""
        _out = {}
        for _t in self.trials:
            if task_ids is not None and _t.task_id not in task_ids:
                continue
            _value = _t.score if partial else _t.success
            if _value is None:
                continue
            _out.setdefault(_t.task_id, []).append(float(_value))
        return _out

    def task_ids(self, **tags) -> List[str]:
        return [_t['id'] for _t in self.tasks
                if all(_value_of(_t, _k) == _v for _k, _v in tags.items())]

    # -- numbers --------------------------------------------------------------

    def summary(self, task_ids=None) -> Dict[str, Any]:
        _trials = [_t for _t in self.trials if task_ids is None or _t.task_id in task_ids]
        _decided = [_t for _t in _trials if _t.success is not None]
        _ok = sum(1 for _t in _decided if _t.success)
        _lo, _hi = stats.wilson(_ok, len(_decided))
        _by_task = self.outcomes(task_ids)
        _k = self.manifest.trials or 1
        _pass_at = [stats.pass_at_k(len(_v), int(sum(_v)), _k) for _v in _by_task.values()]
        _pass_hat = [stats.pass_hat_k(len(_v), int(sum(_v)), _k) for _v in _by_task.values()]
        # every graded trial that has a score, not only those with a success
        # verdict: a trial judged only by optional checks has a score and no
        # success, and was left out of the mean
        _scores = [_t.score for _t in _trials if _t.score is not None]

        def _mean(values):
            _v = [_x for _x in values if _x is not None]
            return (sum(_v) / len(_v)) if _v else None

        _cost = {}
        for _t in _trials:
            for _key, _value in (_t.cost or {}).items():
                if isinstance(_value, (int, float)):
                    _cost[_key] = _cost.get(_key, 0) + _value
        _judge = [_c for _t in _trials for _c in _t.judge_checks]
        return {
            'trials': len(_trials), 'decided': len(_decided), 'successes': _ok,
            'success_rate': (_ok / len(_decided)) if _decided else None,
            'interval': [_lo, _hi] if _decided else None,
            'k': _k,
            'pass_at_k': _mean(_pass_at), 'pass_hat_k': _mean(_pass_hat),
            'tasks_all_k': sum(1 for _v in _by_task.values() if len(_v) >= _k and all(_v)),
            'tasks': len(_by_task),
            'mean_score': _mean(_scores),
            'infra': sum(1 for _t in _trials if _t.status == INFRA),
            'no_verdict': sum(1 for _t in _trials if _t.status == NO_VERDICT),
            'deterministic_checks': sum(1 for _t in _trials for _c in _t.checks
                                        if _c.get('src') != 'llm_judge' and _c.get('kind') != 'gap'),
            'judge_checks': len(_judge),
            'judge_uncertain': sum(1 for _c in _judge if _c.get('uncertain')),
            'cost': _cost,
            'cost_per_trial': {_k2: _v / len(_trials) for _k2, _v in _cost.items()} if _trials else {},
            'by_category': self.by_category(task_ids),
        }

    def by_category(self, task_ids=None) -> Dict[str, int]:
        _out = {}
        for _t in self.trials:
            if task_ids is not None and _t.task_id not in task_ids:
                continue
            if _t.success is False or _t.status != GRADED:
                _out[_t.category] = _out.get(_t.category, 0) + 1
        return _out

    def tag_values(self) -> Dict[str, List[str]]:
        """
        Every tag and its values, and polarity when the run has `dont` tasks.

        Polarity is grouped like a tag so the report and the comparison show
        "should do" and "should refuse" apart, as the guide promises: an agent
        that refuses everything scores perfectly on the dont tasks, and a
        single rate over both hides that.
        """
        _out = {}
        _polarities = sorted({_t.get('polarity') or 'do' for _t in self.tasks})
        if len(_polarities) > 1 or _polarities == ['dont']:
            _out[POLARITY_TAG] = _polarities
        for _task in self.tasks:
            for _k, _v in (_task.get('tags') or {}).items():
                _out.setdefault(_k, [])
                if _v not in _out[_k]:
                    _out[_k].append(_v)
        return _out

    # -- storage --------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {'kind': 'ipandora.eval', 'version': 1, 'run_id': self.run_id,
                'manifest': self.manifest.to_dict(), 'tasks': self.tasks,
                'selfcheck': self.selfcheck, 'duration': self.duration,
                'summary': self.summary(),
                'trials': [_t.to_dict() for _t in self.trials]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EvalRun':
        if not isinstance(data, dict) or data.get('kind') != 'ipandora.eval':
            raise ValueError('not an IntelliPandora evaluation run')
        return cls(run_id=data.get('run_id', ''), manifest=Manifest.from_dict(data.get('manifest')),
                   tasks=list(data.get('tasks') or []), selfcheck=list(data.get('selfcheck') or []),
                   duration=float(data.get('duration') or 0.0),
                   trials=[Trial.from_dict(_t) for _t in data.get('trials') or []])

    def save(self, path: str) -> str:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2, default=str)
        return path

    @classmethod
    def load(cls, path: str) -> 'EvalRun':
        with open(path, 'r', encoding='utf-8') as fh:
            return cls.from_dict(json.load(fh))


def new_run_id() -> str:
    from datetime import datetime
    return 'eval-{}'.format(datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3])


def evaluate(dataset: Dataset, agent: Callable, grade: Callable, trials: int = 1,
             split: Optional[str] = None, workers: int = 1, manifest: Dict[str, Any] = None,
             check_references: bool = True) -> EvalRun:
    """
    Run every task of `dataset` (or one split of it) `trials` times.

    :param workers: trials run on this many threads at once. Agents that call
                    a model API spend most of their time waiting, so threads
                    are enough; isolation between trials is the agent's
                    environment's job (13 §9).
    :param manifest: harness, model, config, resources, user_simulator, seed --
                    recorded with the run. Dataset identity is filled in here.
    :param check_references: grade every reference solution first; a task whose
                    reference fails attributes its failures to the task.
    """
    if trials < 1:
        raise ValueError('trials must be at least 1')
    _data = dataset.split(split)
    if not _data.tasks:
        raise ValueError('no tasks to run{}'.format(' in split {!r}'.format(split) if split else ''))
    _manifest = Manifest.from_dict(dict(manifest or {}))
    _manifest.dataset, _manifest.dataset_version = dataset.name, dataset.version
    _manifest.dataset_hash = _data.fingerprint
    _manifest.split, _manifest.trials = split or '', trials
    _manifest.framework = _manifest.framework or framework_version()

    _problems = selfcheck(_data, grade) if check_references else []
    # only a reference that exists and fails proves the task wrong; a missing
    # one is reported but does not move blame away from the agent
    _broken = frozenset(_p['task_id'] for _p in _problems if _p.get('kind') == 'fails')
    _jobs = [(_task, _i) for _task in _data.tasks for _i in range(trials)]
    _start = time.perf_counter()
    if workers and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as _pool:
            _done = list(_pool.map(lambda _j: run_trial(_j[0], _j[1], agent, grade, _broken), _jobs))
    else:
        _done = [run_trial(_t, _i, agent, grade, _broken) for _t, _i in _jobs]
    return EvalRun(run_id=new_run_id(), manifest=_manifest,
                   tasks=[{'id': _t.id, 'tags': dict(_t.tags), 'polarity': _t.polarity,
                           'split': _t.split} for _t in _data.tasks],
                   trials=_done, selfcheck=_problems,
                   duration=round(time.perf_counter() - _start, 3))

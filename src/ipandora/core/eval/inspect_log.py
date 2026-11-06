# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : inspect_log.py
@Time  : 2026-11-06

Inspect logs read into an EvalRun (docs/design/decisions/13 §3, E1): the
Inspect path's runs get the same statistics, baseline, report and gate as
the pytest path's.

    from ipandora.core.eval import inspect_log

    run = inspect_log.read('logs/')          # a .eval / .json log, or a directory of them
    run.summary()['success_rate']

Inspect runs the agent -- sandbox, epochs, limits, the CLI agents of
inspect_swe; this module only reads what it wrote, with Inspect's own
reader. Needs the `inspect` extra (Python 3.11+).

How a sample becomes a trial:

- one trial per sample and epoch;
- every score is a check. A score passes when it reaches `threshold`
  (1.0 by default: CORRECT, True, 1); a dict or list score is one check per
  entry. A score written by `inspect_scorer.scorer` carries the framework's
  own checks, which are taken as they are;
- scores from model-graded scorers (`model_graded_qa`, `model_graded_fact`,
  and any named in `judges`) are model-judge checks: shown, and counted only
  once calibrated, as everywhere else;
- a sample that ended in an error, or on a time limit, is an infrastructure
  outcome -- the harness did not produce an answer (13 §9: a timeout is
  counted apart and never as the agent failing). Hitting any other limit
  (tokens, messages, cost, turns) is a failed budget check, as in the
  pytest path.
"""
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from ipandora.core.eval.dataset import POLARITIES, SPLITS
from ipandora.core.eval.run import (AGENT, BUDGET, GRADER, INFRASTRUCTURE, EvalRun, new_run_id)
from ipandora.core.eval.trial import INFRA, LLM_JUDGE, NO_VERDICT, Manifest, Trial, framework_version

SOURCE = 'inspect'
"""Check.src of a check made from an Inspect score."""

META_KEY = 'ipandora'
"""Score.metadata key under which inspect_scorer.scorer leaves the framework's checks."""

JUDGE_SCORERS = frozenset({'model_graded_qa', 'model_graded_fact'})
"""Inspect's own scorers that ask a model."""

TIME_LIMITS = frozenset({'time', 'working'})

TEXT_LIMIT = 2000
"""Characters of one trajectory entry kept; the log has the rest."""

INSTALL_HINT = ('reading Inspect logs needs the `inspect` extra (Python 3.11+): '
                'pip install "intellipandora[inspect]"')


def _inspect():
    try:
        from inspect_ai import log as _log
        from inspect_ai.scorer import value_to_float
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return _log, value_to_float


def _files(source: Union[str, Sequence[str]]) -> List[str]:
    """Every log a path or list of paths names, oldest first."""
    _log, _ = _inspect()
    _sources = [source] if isinstance(source, (str, os.PathLike)) else list(source)
    _out = []
    for _s in _sources:
        _s = os.fspath(_s)
        if os.path.isdir(_s):
            _found = [_i.name for _i in _log.list_eval_logs(_s, recursive=True, descending=False)]
            if not _found:
                raise ValueError('{}: no Inspect logs (.eval or .json) in this directory'.format(_s))
            _out.extend(_found)
        elif os.path.isfile(_s):
            _out.append(_s)
        else:
            raise ValueError('{}: no such log file or directory'.format(_s))
    return _out


def _short(text: Any, limit: int = TEXT_LIMIT) -> str:
    _text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return _text if len(_text) <= limit else _text[:limit] + '…（截断，原文 {} 字符）'.format(len(_text))


def _float(value, convert) -> Optional[float]:
    try:
        return float(convert(value))
    except (TypeError, ValueError):
        return None


def _score_checks(name: str, score, convert, threshold: float, judge: bool) -> List[Dict[str, Any]]:
    """The checks one Inspect Score stands for."""
    _meta = getattr(score, 'metadata', None) or {}
    _own = _meta.get(META_KEY) if isinstance(_meta, dict) else None
    if isinstance(_own, dict) and isinstance(_own.get('checks'), list):
        return [dict(_c) for _c in _own['checks'] if isinstance(_c, dict)]
    _value = score.value
    if isinstance(_value, dict):
        _parts = [('{}.{}'.format(name, _k), _v) for _k, _v in _value.items()]
    elif isinstance(_value, (list, tuple)):
        _parts = [('{}[{}]'.format(name, _i), _v) for _i, _v in enumerate(_value)]
    else:
        _parts = [(name, _value)]
    _explanation = getattr(score, 'explanation', None) or ''
    _out = []
    for _label, _v in _parts:
        _f = _float(_v, convert)
        _expr = '{} = {!r}'.format(_label, _v)
        if _explanation:
            _expr += '（{}）'.format(_short(_explanation, 300))
        _out.append({'name': 'Inspect 评分：{}'.format(_label), 'ok': _f is not None and _f >= threshold,
                     'expr': _expr, 'src': LLM_JUDGE if judge else SOURCE, 'kind': 'assert',
                     'claim': 'inspect score {} >= {:g}'.format(_label, threshold),
                     'weight': 1.0, 'required': True,
                     # a value that is not a score at all decides nothing
                     'uncertain': _f is None})
    return _out


def _limit_check(limit) -> Dict[str, Any]:
    _type = getattr(limit, 'type', '') or 'limit'
    _reason = getattr(limit, 'reason', None) or ''
    return {'name': '预算内：{}'.format(_type), 'ok': False,
            'expr': '达到 Inspect 的 {} 上限 {:g}{}'.format(
                _type, float(getattr(limit, 'limit', 0) or 0), '：' + _reason if _reason else ''),
            'src': BUDGET, 'kind': 'assert', 'claim': 'within the {} limit'.format(_type),
            'weight': 1.0, 'required': True, 'uncertain': False}


def _seconds_since(start, moment) -> float:
    try:
        return round((moment - start).total_seconds(), 3)
    except (TypeError, AttributeError):
        return 0.0


def _events_of(sample) -> List[Dict[str, Any]]:
    """Model turns, tool calls, sandbox commands and errors, in order."""
    _events = list(getattr(sample, 'events', None) or [])
    _start = next((getattr(_e, 'timestamp', None) for _e in _events if getattr(_e, 'timestamp', None)), None)
    _out = []
    for _e in _events:
        _kind = type(_e).__name__
        _t = _seconds_since(_start, getattr(_e, 'timestamp', None))
        _error = getattr(_e, 'error', None)
        _error_text = getattr(_error, 'message', None) or (str(_error) if _error else '')
        if _kind == 'ModelEvent':
            _output = getattr(_e, 'output', None)
            _out.append({'t': _t, 'kind': 'message', 'role': 'assistant', 'name': getattr(_e, 'model', ''),
                         'text': _short(getattr(_output, 'completion', '') or ''), 'error': _error_text})
        elif _kind == 'ToolEvent':
            _out.append({'t': _t, 'kind': 'tool', 'role': 'tool', 'name': getattr(_e, 'function', ''),
                         'text': _short('{} → {}'.format(
                             json.dumps(getattr(_e, 'arguments', None) or {}, ensure_ascii=False, default=str),
                             getattr(_e, 'result', ''))),
                         'error': _error_text})
        elif _kind == 'SandboxEvent':
            _what = getattr(_e, 'cmd', None) or getattr(_e, 'file', None) or ''
            _out.append({'t': _t, 'kind': 'tool', 'role': 'tool',
                         'name': 'sandbox.{}'.format(getattr(_e, 'action', '')),
                         'text': _short('{} → {}'.format(_what, getattr(_e, 'output', '') or '')),
                         'error': ''})
        elif _kind == 'ErrorEvent':
            _out.append({'t': _t, 'kind': 'result', 'role': '', 'name': 'error', 'text': '',
                         'error': _short(_error_text)})
        elif _kind == 'SampleLimitEvent':
            _out.append({'t': _t, 'kind': 'result', 'role': '', 'name': 'limit',
                         'text': _short(getattr(_e, 'message', '') or ''), 'error': ''})
    return _out


def _cost(sample, trajectory) -> Dict[str, float]:
    _in = _out_tokens = 0
    _usd, _priced = 0.0, False
    for _usage in (getattr(sample, 'model_usage', None) or {}).values():
        _in += int(getattr(_usage, 'input_tokens', 0) or 0)
        _out_tokens += int(getattr(_usage, 'output_tokens', 0) or 0)
        if getattr(_usage, 'total_cost', None) is not None:
            _usd += float(_usage.total_cost)
            _priced = True
    _cost = {'tokens_in': _in, 'tokens_out': _out_tokens,
             'tool_calls': sum(1 for _e in trajectory if _e['kind'] == 'tool')}
    if _priced:
        _cost['usd'] = round(_usd, 6)
    _turns = getattr(sample, 'turn_count', None)
    if isinstance(_turns, int):
        _cost['turns'] = _turns
    return _cost


def _trial(task_id: str, sample, convert, threshold, judges) -> Trial:
    _trajectory = _events_of(sample)
    _output = getattr(getattr(sample, 'output', None), 'completion', None)
    _trial = Trial(task_id=task_id, index=max(int(getattr(sample, 'epoch', 1) or 1) - 1, 0),
                   output=_output, trajectory=_trajectory, cost=_cost(sample, _trajectory),
                   seconds=round(float(getattr(sample, 'total_time', None) or 0.0), 3))
    _error = getattr(sample, 'error', None)
    _limit = getattr(sample, 'limit', None)
    if _error is not None:
        _trial.status, _trial.category = INFRA, INFRASTRUCTURE
        _trial.error = _short(getattr(_error, 'message', None) or str(_error))
        return _trial
    if _limit is not None and getattr(_limit, 'type', '') in TIME_LIMITS:
        _trial.status, _trial.category = INFRA, INFRASTRUCTURE
        _trial.error = 'Inspect 的 {} 上限 {:g} 秒'.format(_limit.type, float(_limit.limit or 0))
        return _trial
    _checks = []
    for _name, _score in (getattr(sample, 'scores', None) or {}).items():
        _meta = getattr(_score, 'metadata', None) or {}
        _own = _meta.get(META_KEY) if isinstance(_meta, dict) else None
        if isinstance(_own, dict) and _own.get('grader_error'):
            _trial.status, _trial.category = NO_VERDICT, GRADER
            _trial.error = _short(str(_own['grader_error']))
            return _trial
        _checks.extend(_score_checks(_name, _score, convert, _threshold(threshold, _name),
                                     _name in judges))
    if _limit is not None:
        _checks.append(_limit_check(_limit))
    _trial.checks = _checks
    if _trial.success is None:
        _trial.status = NO_VERDICT
    elif not _trial.success:
        _trial.category = AGENT
    return _trial


def _threshold(threshold, name: str) -> float:
    if isinstance(threshold, dict):
        return float(threshold.get(name, threshold.get('*', 1.0)))
    return float(threshold)


def _task_entry(task_id: str, sample, task_name: str, several: bool) -> Dict[str, Any]:
    _meta = getattr(sample, 'metadata', None) or {}
    _tags = dict(_meta.get('tags') or {}) if isinstance(_meta.get('tags'), dict) else {}
    if several:
        _tags.setdefault('task', task_name)
    _polarity = _meta.get('polarity') if _meta.get('polarity') in POLARITIES else 'do'
    _split = _meta.get('split') if _meta.get('split') in SPLITS else 'test'
    return {'id': task_id, 'tags': _tags, 'polarity': _polarity, 'split': _split}


def _when(text) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _manifest(headers, epochs: int, dataset_hash: str) -> Manifest:
    _spec = headers[0].eval
    _tasks = sorted({_h.eval.task for _h in headers})
    _generate = getattr(_spec, 'model_generate_config', None)
    _generate = {_k: _v for _k, _v in (_generate.model_dump() if _generate is not None else {}).items()
                 if _v is not None}
    _config = getattr(_spec, 'config', None)
    _limits = {_k: getattr(_config, _k, None) for _k in ('time_limit', 'working_limit', 'token_limit',
                                                         'message_limit', 'cost_limit')}
    _sandbox = getattr(_spec, 'sandbox', None)
    _packages = getattr(_spec, 'packages', None) or {}
    _solver = getattr(_spec, 'solver', None) or '+'.join(
        getattr(_s, 'solver', '') for _s in (getattr(getattr(headers[0], 'plan', None), 'steps', None) or []))
    _started = min((_h.stats.started_at for _h in headers if getattr(_h.stats, 'started_at', '')),
                   default='')
    return Manifest(
        dataset=_tasks[0] if len(_tasks) == 1 else (getattr(_spec, 'eval_set_id', None) or '+'.join(_tasks)),
        dataset_version=';'.join('{}@{}'.format(_h.eval.task, _h.eval.task_version) for _h in headers),
        dataset_hash=dataset_hash,
        harness='inspect_ai {} · {}'.format(_packages.get('inspect_ai', ''), _solver or 'solver'),
        model=_spec.model or '',
        config={'generate': _generate, 'task_args': dict(getattr(_spec, 'task_args', None) or {}),
                'epochs': epochs, 'logs': [os.path.basename(str(_h.location or '')) for _h in headers],
                'status': {_h.eval.task: _h.status for _h in headers}},
        resources={'sandbox': str(_sandbox) if _sandbox else '',
                   **{_k: _v for _k, _v in _limits.items() if _v is not None}},
        seed=_generate.get('seed'),
        trials=epochs,
        framework=framework_version(),
        started=str(_started).replace('T', ' ')[:19])


def read(source: Union[str, Sequence[str]], threshold: Union[float, Dict[str, float]] = 1.0,
         judges: Iterable[str] = (), run_id: Optional[str] = None) -> EvalRun:
    """
    One EvalRun from Inspect logs.

    :param source:    a log file (.eval or .json), a directory of them, or a list.
                      Several logs are one run: the tasks of one `eval_set`, all
                      on one model. Sample ids are prefixed with the task name
                      when there is more than one task.
    :param threshold: the value a score must reach to pass, on Inspect's scale
                      (CORRECT = 1, PARTIAL = 0.5); per scorer name with a dict,
                      whose '*' entry is the default for the rest.
    :param judges:    more scorer names that ask a model, besides Inspect's
                      model_graded_qa / model_graded_fact.
    """
    _log, _convert = _inspect()
    _convert = _convert()
    _judges = frozenset(JUDGE_SCORERS) | frozenset(judges)
    _headers = []
    for _file in _files(source):
        _h = _log.read_eval_log(_file, header_only=True)
        _h.location = _h.location or _file
        _headers.append((_file, _h))
    _models = sorted({_h.eval.model for _, _h in _headers})
    if len(_models) > 1:
        raise ValueError('these logs ran on different models ({}): one run is one model -- read '
                         'them one model at a time'.format(', '.join(_models)))
    _names = [_h.eval.task for _, _h in _headers]
    _several = len(set(_names)) > 1
    if len(_names) != len(set(_names)):
        _twice = sorted({_n for _n in _names if _names.count(_n) > 1})
        raise ValueError('more than one log of task {}: a directory may hold several runs -- name the '
                         'log files of one run'.format(', '.join(_twice)))

    _trials, _tasks, _hash = [], {}, hashlib.sha256()
    _epochs = 1
    for _file, _h in sorted(_headers, key=lambda _x: _x[1].eval.task):
        if _h.status == 'error' and not (_h.results and _h.results.completed_samples):
            _message = getattr(getattr(_h, 'error', None), 'message', '') or 'no samples'
            raise ValueError('{}: the Inspect run failed before any sample finished: {}'.format(
                _file, _short(_message, 500)))
        _epochs = max(_epochs, int(getattr(_h.eval.config, 'epochs', None) or 1))
        _hash.update('{}@{}'.format(_h.eval.task, _h.eval.task_version).encode('utf-8'))
        _seen_samples = set()
        for _sample in _log.read_eval_log_samples(_file, all_samples_required=False):
            _id = '{}/{}'.format(_h.eval.task, _sample.id) if _several else str(_sample.id)
            if _id not in _tasks:
                _tasks[_id] = _task_entry(_id, _sample, _h.eval.task, _several)
            if _sample.id not in _seen_samples:
                _seen_samples.add(_sample.id)
                _hash.update(json.dumps([str(_sample.id), _sample.input, _sample.target],
                                        ensure_ascii=False, sort_keys=True, default=str).encode('utf-8'))
            _trials.append(_trial(_id, _sample, _convert, threshold, _judges))

    _trials.sort(key=lambda _t: (_t.task_id, _t.index))
    _times = [(_when(getattr(_h.stats, 'started_at', '')), _when(getattr(_h.stats, 'completed_at', '')))
              for _, _h in _headers]
    _starts = [_s for _s, _ in _times if _s]
    _ends = [_e for _, _e in _times if _e]
    _duration = _seconds_since(min(_starts), max(_ends)) if _starts and _ends else round(
        sum(_t.seconds for _t in _trials), 3)
    _run_id = run_id or (getattr(_headers[0][1].eval, 'run_id', '') and
                         'inspect-{}'.format(_headers[0][1].eval.run_id)) or new_run_id()
    return EvalRun(run_id=_run_id,
                   manifest=_manifest([_h for _, _h in _headers], _epochs, _hash.hexdigest()),
                   tasks=sorted(_tasks.values(), key=lambda _t: _t['id']),
                   trials=_trials, duration=_duration)


__all__ = ['read', 'JUDGE_SCORERS', 'SOURCE', 'META_KEY', 'INSTALL_HINT']

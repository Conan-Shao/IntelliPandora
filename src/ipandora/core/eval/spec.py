# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : spec.py
@Time  : 2026-11-05

An evaluation spec: one Python file that says what to run.

    # evals/coding.py
    DATASET = 'coding.yaml'            # relative to this file; or a Dataset
    MANIFEST = {'harness': 'my-agent@abc123', 'model': 'claude-sonnet-5'}

    def agent(task):
        ...                            # run the agent, return AgentResult or the output

    def grade(task, result):
        return [that(result.output, 'answer') == task.expected]

`ipandora eval run evals/coding.py` loads it. Agents and graders are code,
the tasks are data (docs/design/decisions/13 §4).
"""
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from ipandora.core.eval import dataset as datasets
from ipandora.core.eval.dataset import Dataset


@dataclass
class Spec:
    path: str
    dataset: Dataset
    agent: Callable
    grade: Callable
    manifest: Dict[str, Any] = field(default_factory=dict)


def load(path: str) -> Spec:
    """Import a spec file. Raises ValueError naming what is missing."""
    _path = os.path.abspath(path)
    if not os.path.isfile(_path):
        raise ValueError('no such spec file: {}'.format(path))
    if not _path.endswith('.py'):
        # importlib finds no loader for any other extension and the next line
        # failed with an AttributeError on None
        raise ValueError('a spec is a Python file (.py): {}'.format(path))
    _dir = os.path.dirname(_path)
    _name = 'ipandora_eval_spec_{}'.format(abs(hash(_path)))
    _module_spec = importlib.util.spec_from_file_location(_name, _path)
    _module = importlib.util.module_from_spec(_module_spec)
    # Registered before it runs, as an import would: a @dataclass in the spec
    # looks its own module up in sys.modules, and failed with an
    # AttributeError on None when it was not there.
    sys.modules[_name] = _module
    # the spec's own imports (its graders, its agent wrapper) sit beside it
    sys.path.insert(0, _dir)
    try:
        _module_spec.loader.exec_module(_module)
    except Exception:
        sys.modules.pop(_name, None)
        raise
    finally:
        if sys.path and sys.path[0] == _dir:
            sys.path.pop(0)

    _missing = [_n for _n in ('DATASET', 'agent', 'grade') if not hasattr(_module, _n)]
    if _missing:
        raise ValueError('{} must define {}'.format(path, ', '.join(_missing)))
    _data = _module.DATASET
    if isinstance(_data, str):
        _data = datasets.load(_data if os.path.isabs(_data) else os.path.join(_dir, _data))
    if not isinstance(_data, Dataset):
        raise ValueError('{}: DATASET must be a path or a Dataset'.format(path))
    for _n in ('agent', 'grade'):
        if not callable(getattr(_module, _n)):
            raise ValueError('{}: {} must be callable'.format(path, _n))
    return Spec(path=_path, dataset=_data, agent=_module.agent, grade=_module.grade,
                manifest=dict(getattr(_module, 'MANIFEST', {}) or {}))

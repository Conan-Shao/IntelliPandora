# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : dataset.py
@Time  : 2026-11-05

Evaluation datasets: tasks are data, graders are code.

A dataset is a YAML or JSONL file of tasks. Each task says what goes in,
what the starting state is, what is expected, how it is tagged, what it may
spend, and where its reference solution is:

    name: coding-tasks
    version: 3
    tasks:
      - id: multi/rename-config-key
        input: 把配置项 timeout_s 重命名为 timeout，旧名继续可读
        tags: {kind: 多文件修改, difficulty: medium}
        polarity: do            # do: should be done; dont: should be refused
        split: test             # dev: for tuning; test: for conclusions
        budget: {seconds: 600, usd: 1.0}
        reference: refs/rename-config-key.patch
        expected: {hidden_tests: tests/hidden/test_rename.py}

The dataset is frozen by its content hash -- the tasks plus the bytes of every
reference file -- which goes into the run's manifest. Two runs with the same
hash ran the same questions; a hash that changed means the scores are not
comparable, and the comparison says so instead of pretending.

See docs/design/decisions/13 §4.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

POLARITIES = ('do', 'dont')
SPLITS = ('dev', 'test')


@dataclass
class Task:
    id: str
    input: Any = None
    """What the agent is given: a prompt, a message list, a ticket."""
    initial_state: Any = None
    """What the world looks like before the agent starts: a repo commit, seed data."""
    expected: Any = None
    """What graders compare against. Its shape is the graders' business."""
    tags: Dict[str, Any] = field(default_factory=dict)
    polarity: str = 'do'
    split: str = 'test'
    budget: Dict[str, float] = field(default_factory=dict)
    reference: Any = None
    """The reference solution: inline, or a path relative to the dataset file."""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Dataset:
    name: str
    version: str = ''
    tasks: List[Task] = field(default_factory=list)
    path: str = ''
    """The file it was read from; reference paths are relative to its directory."""

    def task(self, task_id: str) -> Optional[Task]:
        return next((_t for _t in self.tasks if _t.id == task_id), None)

    def split(self, name: Optional[str]) -> 'Dataset':
        """The tasks of one split, or all of them for None."""
        if name is None:
            return self
        if name not in SPLITS:
            raise ValueError('unknown split {!r}; use one of {}'.format(name, ', '.join(SPLITS)))
        return Dataset(self.name, self.version, [_t for _t in self.tasks if _t.split == name],
                       self.path)

    def reference_path(self, task: Task) -> Optional[str]:
        """The file a task's reference names, if it names one that exists."""
        if not isinstance(task.reference, str) or not self.path:
            return None
        _base = os.path.dirname(os.path.abspath(self.path))
        _file = os.path.normpath(os.path.join(_base, task.reference))
        # a reference must not reach outside the dataset's directory
        if os.path.commonpath([_base, _file]) != _base or not os.path.isfile(_file):
            return None
        return _file

    def reference(self, task: Task) -> Any:
        """The reference solution itself: a file's text, or the inline value."""
        _file = self.reference_path(task)
        if _file:
            with open(_file, 'r', encoding='utf-8') as fh:
                return fh.read()
        return task.reference

    @property
    def fingerprint(self) -> str:
        """
        sha256 of the tasks and the bytes of every reference file.

        Order-independent over tasks, so reordering the file does not count as
        a new dataset; any change to a task or a reference does.
        """
        _hash = hashlib.sha256()
        for _task in sorted(self.tasks, key=lambda _t: _t.id):
            _hash.update(json.dumps(_task.to_dict(), sort_keys=True, ensure_ascii=False,
                                    default=str).encode('utf-8'))
            _file = self.reference_path(_task)
            if _file:
                with open(_file, 'rb') as fh:
                    _hash.update(hashlib.sha256(fh.read()).digest())
        return _hash.hexdigest()


def _task(raw: Dict[str, Any], where: str) -> Task:
    if not isinstance(raw, dict):
        raise ValueError('{}: a task must be a mapping, got {}'.format(where, type(raw).__name__))
    _known = {_f for _f in Task.__dataclass_fields__}
    _unknown = sorted(set(raw) - _known)
    if _unknown:
        # a typo ("refrence") must not silently drop the reference solution
        raise ValueError('{}: unknown field(s) {}; known: {}'.format(
            where, ', '.join(_unknown), ', '.join(sorted(_known))))
    if not raw.get('id'):
        raise ValueError('{}: every task needs an id'.format(where))
    _t = Task(**raw)
    _t.id = str(_t.id)
    if _t.polarity not in POLARITIES:
        raise ValueError('{}: polarity must be one of {}, got {!r}'.format(
            where, ', '.join(POLARITIES), _t.polarity))
    if _t.split not in SPLITS:
        raise ValueError('{}: split must be one of {}, got {!r}'.format(
            where, ', '.join(SPLITS), _t.split))
    if not isinstance(_t.tags, dict):
        raise ValueError('{}: tags must be a mapping, e.g. {{kind: 多文件修改}}'.format(where))
    return _t


def from_records(records: List[Dict[str, Any]], name: str, version: str = '',
                 path: str = '') -> Dataset:
    _tasks = [_task(_r, '{} task #{}'.format(name, _i + 1)) for _i, _r in enumerate(records)]
    _ids = [_t.id for _t in _tasks]
    _twice = sorted({_i for _i in _ids if _ids.count(_i) > 1})
    if _twice:
        raise ValueError('{}: duplicate task id(s): {}'.format(name, ', '.join(_twice)))
    return Dataset(name=name, version=str(version or ''), tasks=_tasks, path=path)


def load(path: str) -> Dataset:
    """
    A dataset from YAML (a mapping with `tasks`, or a bare list) or JSONL
    (one task per line). Raises ValueError with the place of the problem.
    """
    _name = os.path.splitext(os.path.basename(path))[0]
    with open(path, 'r', encoding='utf-8') as fh:
        _text = fh.read()
    if path.endswith('.jsonl'):
        _records = []
        for _n, _line in enumerate(_text.splitlines(), 1):
            if _line.strip():
                try:
                    _records.append(json.loads(_line))
                except ValueError as exc:
                    raise ValueError('{}:{}: {}'.format(path, _n, exc))
        return from_records(_records, _name, path=path)
    import yaml
    _data = yaml.safe_load(_text)
    if isinstance(_data, list):
        return from_records(_data, _name, path=path)
    if not isinstance(_data, dict) or not isinstance(_data.get('tasks'), list):
        raise ValueError('{}: expected a list of tasks, or a mapping with a `tasks` list'.format(path))
    return from_records(_data['tasks'], str(_data.get('name') or _name),
                        version=_data.get('version', ''), path=path)

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
import re
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

    root = ''
    """
    The dataset's directory, which the task's files are relative to. Not a
    field: a dataset cannot set it, and it is not part of the task's content.
    """

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def files(self) -> List[str]:
        """
        The data files the task names for the framework to read: its
        initial_state.fixture and the JSON Schemas of its output checks.
        """
        _out = []
        if isinstance(self.initial_state, dict) and isinstance(self.initial_state.get('fixture'), str):
            _out.append(self.initial_state['fixture'])
        _checks = self.expected.get('checks') if isinstance(self.expected, dict) else None
        for _c in _checks if isinstance(_checks, list) else ():
            if isinstance(_c, dict) and isinstance(_c.get('schema'), str):
                _out.append(_c['schema'])
        return _out


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

    def file_path(self, relative: Any) -> Optional[str]:
        """A file next to the dataset, if `relative` names one that exists -- never outside its directory."""
        if not isinstance(relative, str) or not relative or not self.path:
            return None
        _base = os.path.dirname(os.path.abspath(self.path))
        _file = os.path.normpath(os.path.join(_base, relative))
        if os.path.commonpath([_base, _file]) != _base or not os.path.isfile(_file):
            return None
        return _file

    def reference_path(self, task: Task) -> Optional[str]:
        """The file a task's reference names, if it names one that exists."""
        return self.file_path(task.reference)

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
        sha256 of the tasks, the bytes of every reference file, and of the
        files the framework reads for a task (fixtures, schemas): a changed
        fixture is a changed question.

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
            for _name in _task.files():
                _data = self.file_path(_name)
                if _data:
                    with open(_data, 'rb') as fh:
                        _hash.update(b'file:' + _name.encode('utf-8') + hashlib.sha256(fh.read()).digest())
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
    if raw.get('id') is None or str(raw.get('id')).strip() == '':
        # `id: 0` is an id; only a missing or empty one is not
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


# A string reference that looks like a file name: `refs/fix.patch`, `answer.json`.
# The extension must contain a letter, so an inline answer like `3.14` is not one.
_LOOKS_LIKE_FILE = re.compile(r'^[\w./\\-]+\.[A-Za-z][\w]{0,9}$')


def _check_references(dataset: Dataset) -> None:
    """
    A reference written as a file name must be that file. A missing one used
    to be taken as the inline reference -- the text "refs/fix.patch" -- so
    the self-check graded the path itself, and the task's hash ignored the
    file the author meant.
    """
    if not dataset.path:
        return
    for _task in dataset.tasks:
        _ref = _task.reference
        if isinstance(_ref, str) and '\n' not in _ref and _LOOKS_LIKE_FILE.match(_ref.strip()) \
                and dataset.reference_path(_task) is None:
            raise ValueError('{}: task {}: reference file {!r} not found next to the dataset '
                             '(or it points outside its directory)'.format(
                                 dataset.path, _task.id, _ref))
        for _name in _task.files():
            # a fixture that is not there would be found missing only when a
            # trial starts, and not in the hash before that
            if dataset.file_path(_name) is None:
                raise ValueError('{}: task {}: file {!r} not found next to the dataset '
                                 '(or it points outside its directory)'.format(dataset.path, _task.id, _name))


def from_records(records: List[Dict[str, Any]], name: str, version: str = '',
                 path: str = '') -> Dataset:
    _tasks = [_task(_r, '{} task #{}'.format(name, _i + 1)) for _i, _r in enumerate(records)]
    _ids = [_t.id for _t in _tasks]
    _twice = sorted({_i for _i in _ids if _ids.count(_i) > 1})
    if _twice:
        raise ValueError('{}: duplicate task id(s): {}'.format(name, ', '.join(_twice)))
    _data = Dataset(name=name, version=str(version or ''), tasks=_tasks, path=path)
    if path:
        for _t in _tasks:
            _t.root = os.path.dirname(os.path.abspath(path))
    _check_references(_data)
    return _data


def load(path: str) -> Dataset:
    """
    A dataset from YAML (a mapping with `tasks`, or a bare list) or JSONL
    (one task per line). Raises ValueError with the place of the problem.
    """
    _name = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            _text = fh.read()
    except OSError as exc:
        raise ValueError('cannot read dataset {}: {}'.format(path, exc.strerror or exc))
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
    try:
        _data = yaml.safe_load(_text)
    except yaml.YAMLError as exc:
        raise ValueError('{}: not valid YAML: {}'.format(path, exc))
    if isinstance(_data, list):
        return from_records(_data, _name, path=path)
    if not isinstance(_data, dict) or not isinstance(_data.get('tasks'), list):
        raise ValueError('{}: expected a list of tasks, or a mapping with a `tasks` list'.format(path))
    return from_records(_data['tasks'], str(_data.get('name') or _name),
                        version=_data.get('version', ''), path=path)

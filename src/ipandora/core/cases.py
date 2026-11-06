# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : cases.py
@Time  : 2026-11-06

Data-driven cases: the case is Python, the inputs are a data file
(docs/design/decisions/17 §3.5).

    # data/refund_amounts.yaml
    - id: whole-yuan
      amount: '100.00'
      dims: {role: buyer, channel: api}
    - id: with-fen
      amount: '100.50'
      dims: {role: buyer, channel: api}

    @pytest.mark.parametrize('case', cases('data/refund_amounts.yaml'))
    def test_refund_amount(case):
        ...case.amount...

Each row becomes one pytest.param: its `id` is the test id, its `dims` the
@pytest.mark.dims of that run -- so a data file fills cells of the coverage
matrix like a decorator does -- and the rest is handed to the case as a Case,
a dict that also reads as attributes.

Not a step language. Rows hold inputs and expected values; what is done
with them, and every judgement, stays in Python where the judgement
inventory, the zero-judgement check and an IDE can see it.

CSV values are text: a column that holds numbers is compared as text unless
the case converts it -- `.decimal()` for amounts. Columns named `dims.role`
become dims.
"""
import csv
import inspect
import json
import os
from typing import Any, Dict, List, Optional

ID, DIMS = 'id', 'dims'


class Case(dict):
    """One row: `case['amount']` or `case.amount`."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError('this case has no field {!r}; it has: {}'.format(
                name, ', '.join(sorted(self)) or 'none')) from None


def _find(path: str, caller_dir: str) -> str:
    """The file: as given, next to the calling test file, or in a directory above it."""
    if os.path.isabs(path):
        return path
    _dir = caller_dir
    for _ in range(8):
        _candidate = os.path.join(_dir, path)
        if os.path.isfile(_candidate):
            return _candidate
        _parent = os.path.dirname(_dir)
        if _parent == _dir:
            break
        _dir = _parent
    if os.path.isfile(path):
        return os.path.abspath(path)
    raise ValueError('cases(): no file {!r} next to {} or in any directory above it'.format(
        path, caller_dir))


def _rows(file: str) -> List[Any]:
    _lower = file.lower()
    with open(file, 'r', encoding='utf-8-sig', newline='') as _f:
        if _lower.endswith('.csv'):
            return list(csv.DictReader(_f))
        _text = _f.read()
    if _lower.endswith('.json'):
        _data = json.loads(_text)
    elif _lower.endswith(('.yaml', '.yml')):
        import yaml
        try:
            _data = yaml.safe_load(_text)
        except yaml.YAMLError as exc:
            raise ValueError('{}: not valid YAML: {}'.format(file, exc))
    else:
        raise ValueError('cases(): {} is not .yaml, .yml, .json or .csv'.format(file))
    if isinstance(_data, dict) and isinstance(_data.get('cases'), list):
        _data = _data['cases']
    if not isinstance(_data, list):
        raise ValueError('{}: expected a list of cases, or a mapping with a `cases` list'.format(file))
    return _data


def _dims(row: Dict[str, Any], where: str) -> Dict[str, str]:
    _out = {}
    _given = row.pop(DIMS, None)
    if _given is not None:
        if not isinstance(_given, dict):
            raise ValueError('{}: dims must be a mapping such as {{role: buyer}}'.format(where))
        _out.update({str(_k): str(_v) for _k, _v in _given.items()})
    for _key in [_k for _k in row if isinstance(_k, str) and _k.startswith(DIMS + '.')]:
        _value = row.pop(_key)
        if _value not in (None, ''):
            _out[_key[len(DIMS) + 1:]] = str(_value)
    return _out


def cases(path: str, ids: Optional[str] = ID) -> list:
    """
    The rows of a YAML, JSON or CSV file as pytest.param objects, for
    @pytest.mark.parametrize('case', cases('data/x.yaml')).

    :param path: relative to the calling test file, or to a directory above
                 it -- `data/x.yaml` from tests/api/test_x.py finds the
                 project's data/ -- or absolute.
    :param ids:  the field that names each row in the test id. Rows without
                 it are numbered.
    """
    import pytest
    _caller = os.path.dirname(os.path.abspath(inspect.stack()[1].filename))
    _file = _find(path, _caller)
    _out, _seen = [], set()
    for _n, _raw in enumerate(_rows(_file), 1):
        _where = '{} case #{}'.format(_file, _n)
        if not isinstance(_raw, dict):
            raise ValueError('{}: a case must be a mapping, got {}'.format(_where, type(_raw).__name__))
        _row = dict(_raw)
        _dims_of = _dims(_row, _where)
        _id = _row.get(ids) if ids else None
        _id = str(_id) if _id not in (None, '') else '{}-{}'.format(os.path.splitext(
            os.path.basename(_file))[0], _n)
        if _id in _seen:
            # two rows with one id: pytest would run both under names that
            # read as the same case, and a failure could not be pointed at
            raise ValueError('{}: duplicate id {!r}'.format(_where, _id))
        _seen.add(_id)
        _marks = [pytest.mark.dims(**_dims_of)] if _dims_of else []
        _out.append(pytest.param(Case(_row), id=_id, marks=_marks))
    if not _out:
        raise ValueError('{}: no cases in the file -- a parametrized test over nothing would '
                         'pass without running'.format(_file))
    return _out

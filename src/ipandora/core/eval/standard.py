# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : standard.py
@Time  : 2026-11-07

The standard grader (E5a): the `expected` vocabulary of the dataset contract
(docs/guide/eval-dataset.md §5), judged by the framework, so a dataset
written to the contract needs no grader of its own.

    # evals/refunds/spec.py
    from ipandora.core.eval import dialogue, standard
    from shop import Shop, Bot

    DATASET = 'dataset.yaml'

    def world(task):                         # a fresh business system for each trial
        return Shop(standard.initial_state(task))     # initial_state.fixture + patch

    def agent(task):
        shop = world(task)
        return dialogue.converse(Bot(shop).respond, dialogue.ScriptedUser.from_task(task),
                                 state=shop.snapshot)

    # no grade(): the spec gets standard.grader(world)

A world is anything with `call(name, **args)` (its tools) and `snapshot()`
(its data as plain mappings). The standard grader uses it twice: a fresh one,
untouched, is the initial state that `state.changes` are applied to; another
replays a reference written as tool calls, so `ipandora eval selfcheck`
proves every task can be solved.

What it judges, in the contract's order: output constraints (`answer`,
`checks`), the end state (`state`), trajectory rules (`called`,
`not_called`, `called_at_most`, `no_loops`, `finished`), what the agent said
(`says`, `never_says`). Keys it does not judge -- `safety` and `rubric` for
now, the coding fields, a dataset's own keys -- must be named in `skip`: a
misspelt or unsupported key is an error, never a judgement quietly left out.
"""
import copy
import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ipandora.core.assertion.check import Check, brief
from ipandora.core.assertion.jsonpath import MISSING, resolve
from ipandora.core.eval import dialogue
from ipandora.core.eval.trial import Graded, TaskError

OUTPUT_KEYS = ('answer', 'checks')
STATE_KEYS = ('state',)
TRAJECTORY_KEYS = ('called', 'not_called', 'called_at_most', 'no_loops', 'finished')
SAYS_KEYS = ('says', 'never_says')
KNOWN = OUTPUT_KEYS + STATE_KEYS + TRAJECTORY_KEYS + SAYS_KEYS
"""The `expected` keys this grader judges."""

MULTI_TURN = STATE_KEYS + TRAJECTORY_KEYS + SAYS_KEYS
"""Keys that judge a conversation: a list reference of such a task is tool calls to replay."""

ATTRIBUTES = ('required', 'weight')

OUTPUT = dialogue.OUTPUT


# -- files and the initial state --------------------------------------------------------------

def task_file(task, relative: str) -> str:
    """
    A file a task names, relative to its dataset's directory -- never outside
    it. A task built in code has no dataset; its files are relative to the
    working directory.
    """
    if not isinstance(relative, str) or not relative:
        raise TaskError('task {}: a file name is a non-empty string, got {!r}'.format(task.id, relative))
    _base = os.path.abspath(getattr(task, 'root', '') or os.getcwd())
    _file = os.path.normpath(os.path.join(_base, relative))
    if os.path.commonpath([_base, _file]) != _base:
        raise TaskError('task {}: {!r} points outside the dataset directory'.format(task.id, relative))
    if not os.path.isfile(_file):
        raise TaskError('task {}: file {!r} not found next to the dataset'.format(task.id, relative))
    return _file


def _read_data(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as fh:
        _text = fh.read()
    if path.endswith(('.yaml', '.yml')):
        import yaml
        return yaml.safe_load(_text)
    return json.loads(_text)


def _segments(path: str) -> List[str]:
    _parts = str(path).split('.')
    if not path or any(_p == '' for _p in _parts):
        raise TaskError('bad path {!r}: write dotted keys, e.g. orders.A1001.status'.format(path))
    return _parts


def _step(node: Any, key: str, path: str) -> Any:
    if isinstance(node, dict) and key in node:
        return node[key]
    if isinstance(node, list) and re.fullmatch(r'-?\d+', key) and -len(node) <= int(key) < len(node):
        return node[int(key)]
    raise TaskError('path {!r}: {!r} not found'.format(path, key))


def _set(root: Any, parts: Sequence[str], value: Any, path: str, merge: bool) -> None:
    _node = root
    for _key in parts[:-1]:
        _node = _step(_node, _key, path)
    _last = parts[-1]
    if isinstance(_node, list):
        _step(_node, _last, path)                          # an index that exists
        _node[int(_last)] = _merged(_node[int(_last)], value) if merge else value
    elif isinstance(_node, dict):
        _node[_last] = _merged(_node[_last], value) if merge and _last in _node else value
    else:
        raise TaskError('path {!r}: {} is not a mapping or a list'.format(path, '.'.join(parts[:-1])))


def _merged(old: Any, new: Any) -> Any:
    """`new` laid over `old`: mappings merge key by key, anything else replaces."""
    if isinstance(old, dict) and isinstance(new, dict):
        _out = dict(old)
        for _k, _v in new.items():
            _out[_k] = _merged(old[_k], _v) if _k in old else copy.deepcopy(_v)
        return _out
    return copy.deepcopy(new)


def initial_state(task) -> Optional[Any]:
    """
    The world before the agent starts, from `initial_state` (§6.1): the
    `fixture` file (JSON or YAML) with `patch` applied, a new copy on every
    call -- each trial must start from a fresh state. None when the task has
    no fixture: the spec builds its world itself.

        initial_state:
          fixture: fixtures/shop.json
          patch: {orders.A1002.status: shipped}
    """
    _state = task.initial_state
    if not isinstance(_state, dict) or ('fixture' not in _state and 'patch' not in _state):
        return None
    if 'plant' in _state:
        # planting is E5b: a task that plants an injection or a canary and
        # runs without it measures an agent that was never tempted
        raise TaskError('task {}: initial_state.plant is not read by the framework yet (planned, E5b); '
                        'plant in the spec with safety.*'.format(task.id))
    if 'fixture' not in _state:
        raise TaskError('task {}: initial_state.patch needs a fixture to patch'.format(task.id))
    try:
        _data = _read_data(task_file(task, _state['fixture']))
    except (OSError, ValueError) as exc:
        if isinstance(exc, TaskError):
            raise
        raise TaskError('task {}: cannot read fixture {!r}: {}'.format(task.id, _state['fixture'], exc))
    _patch = _state.get('patch') or {}
    if not isinstance(_patch, dict):
        raise TaskError('task {}: initial_state.patch is a mapping of path: value'.format(task.id))
    for _path, _value in _patch.items():
        try:
            _set(_data, _segments(_path), copy.deepcopy(_value), _path, merge=False)
        except TaskError as exc:
            raise TaskError('task {}: initial_state.patch: {}'.format(task.id, exc))
    return _data


def expected_state(initial: Any, changes: Dict[str, Any], task_id: str = '?') -> Any:
    """
    The initial state with `changes` applied (§5.2). A key is a path from the
    root (`orders.A1001`) or a bare record id (`A1001`) found in exactly one
    collection. A mapping merges into the record; any other value replaces.
    """
    if not isinstance(changes, dict):
        raise TaskError('task {}: state.changes is a mapping, e.g. {{orders.A1001: {{status: refunded}}}}'
                        .format(task_id))
    _state = copy.deepcopy(initial)
    for _key, _value in changes.items():
        _parts = _segments(str(_key))
        if len(_parts) == 1 and not (isinstance(_state, dict) and _parts[0] in _state):
            _found = [_c for _c, _records in (_state.items() if isinstance(_state, dict) else ())
                      if isinstance(_records, dict) and _parts[0] in _records]
            if len(_found) != 1:
                raise TaskError('task {}: state.changes: record {!r} is in {} collections; write its path '
                                'from the root, e.g. {}.{}'.format(
                                    task_id, _key, len(_found) if _found else 'no',
                                    _found[0] if _found else 'orders', _key))
            _parts = [_found[0], _parts[0]]
        try:
            _set(_state, _parts, _value, str(_key), merge=True)
        except TaskError as exc:
            raise TaskError('task {}: state.changes: {}'.format(task_id, exc))
    return _state


# -- comparisons -------------------------------------------------------------------------------

def _number(value) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)) or (isinstance(value, str) and value.strip()):
        try:
            _d = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return _d if _d.is_finite() else None
    return None


def _equal(actual, expected) -> bool:
    """Numbers by value ('120.50' == 120.5), structures by differences(), text stripped."""
    if isinstance(expected, (dict, list)):
        return not dialogue.differences(actual, expected)
    _a, _e = _number(actual), _number(expected)
    if _a is not None and _e is not None and not isinstance(expected, str):
        return _a == _e
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip() == expected.strip()
    return not dialogue.differences(actual, expected)


COMPARISONS = ('lt', 'lte', 'gt', 'gte', 'ne', 'regex', 'contains', 'one_of', 'approx', 'tolerance')
"""Operators of an argument comparison: `{amount: {lte: 100}}`."""

_ORDER = {'lt': ('<', lambda a, b: a < b), 'lte': ('<=', lambda a, b: a <= b),
          'gt': ('>', lambda a, b: a > b), 'gte': ('>=', lambda a, b: a >= b)}


def _is_comparison(value) -> bool:
    return isinstance(value, dict) and bool(value) and set(value) <= set(COMPARISONS)


def comparison(spec: Dict[str, Any], where: str = '') -> Callable[[Any], bool]:
    """
    A predicate from `{lte: 100}`, `{regex: 退款}`, `{one_of: [a, b]}`,
    `{approx: 120.5, tolerance: 0.01}`... Several operators must all hold.
    Its __name__ is the condition, so evidence and the judgement inventory
    read `amount=<条件 <= 100>`, and a loosened bound shows up as a change.
    """
    if 'tolerance' in spec and 'approx' not in spec:
        raise TaskError('{}: tolerance goes with approx'.format(where))
    _tests, _names = [], []
    for _op in sorted(spec):
        _want = spec[_op]
        if _op in _ORDER:
            _bound = _number(_want)
            if _bound is None:
                raise TaskError('{}: {} needs a number, got {!r}'.format(where, _op, _want))
            _sym, _cmp = _ORDER[_op]
            _tests.append(lambda v, b=_bound, c=_cmp: _number(v) is not None and c(_number(v), b))
            _names.append('{} {}'.format(_sym, _want))
        elif _op == 'ne':
            _tests.append(lambda v, w=_want: not _equal(v, w))
            _names.append('!= {}'.format(brief(_want, 40)))
        elif _op == 'regex':
            _re = _compile(_want, where)
            _tests.append(lambda v, r=_re: isinstance(v, str) and r.search(v) is not None)
            _names.append('~ /{}/'.format(_want))
        elif _op == 'contains':
            _tests.append(lambda v, w=_want: isinstance(v, (str, list, tuple, dict)) and w in v)
            _names.append('contains {}'.format(brief(_want, 40)))
        elif _op == 'one_of':
            if not isinstance(_want, list):
                raise TaskError('{}: one_of needs a list'.format(where))
            _tests.append(lambda v, w=_want: any(_equal(v, _o) for _o in w))
            _names.append('in {}'.format(brief(_want, 60)))
        elif _op == 'approx':
            _tol, _target = _number(spec.get('tolerance', 0)), _number(_want)
            if _tol is None or _target is None:
                raise TaskError('{}: approx and tolerance need numbers'.format(where))
            _tests.append(lambda v, t=_target, d=_tol: _number(v) is not None and abs(_number(v) - t) <= d)
            _names.append('≈ {} ± {}'.format(_want, spec.get('tolerance', 0)))

    def _predicate(value):
        return all(_t(value) for _t in _tests)
    _predicate.__name__ = ' and '.join(_names)
    return _predicate


def _compile(pattern, where: str):
    if not isinstance(pattern, str):
        raise TaskError('{}: a pattern is a string; quote it in YAML'.format(where))
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise TaskError('{}: bad regular expression {!r}: {}'.format(where, pattern, exc))


def _args(spec: Any, where: str) -> Dict[str, Any]:
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise TaskError('{}: args is a mapping of the arguments to constrain'.format(where))
    return {_k: comparison(_v, '{} args.{}'.format(where, _k)) if _is_comparison(_v) else _v
            for _k, _v in spec.items()}


# -- the output (§5.1) ---------------------------------------------------------------------------

def _is_conversation(output) -> bool:
    return isinstance(output, dict) and 'ended' in output and 'reply' in output


def output_text(output) -> str:
    """The text output constraints judge: the agent's last reply, or the output itself."""
    if _is_conversation(output):
        return str(output.get('reply') or '')
    if isinstance(output, str):
        return output
    if isinstance(output, (dict, list)):
        return json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    return '' if output is None else str(output)


def _structured(output):
    """The output as data for `json` and `schema`: a mapping as is, text parsed as JSON."""
    if isinstance(output, (dict, list)) and not _is_conversation(output):
        return output, ''
    _text = output_text(output).strip()
    try:
        return json.loads(_text), ''
    except ValueError as exc:
        return MISSING, '输出不是 JSON：{}'.format(exc)


_CHECK_OPS = ('equals', 'contains', 'not_contains', 'regex', 'one_of', 'json', 'schema')
_JSON_OPS = ('equals', 'approx', 'length', 'exists')


def _graded(check: Check, entry: Any) -> Graded:
    if not isinstance(entry, dict):
        return Graded(check)
    _weight = entry.get('weight', 1)
    if _number(_weight) is None or _number(_weight) < 0:
        raise TaskError('weight must be a non-negative number, got {!r}'.format(_weight))
    _required = entry.get('required', True)
    if not isinstance(_required, bool):
        raise TaskError('required is true or false, got {!r}'.format(_required))
    return Graded(check, weight=float(_weight), required=_required)


def _output_check(entry: Dict[str, Any], output, task, where: str) -> Check:
    _ops = [_k for _k in entry if _k in _CHECK_OPS]
    _allowed = set(ATTRIBUTES) | {'what'}
    if 'json' in entry:
        _allowed |= {'json', 'tolerance'} | set(_JSON_OPS)
    else:
        _allowed |= set(_CHECK_OPS)
    _extra = sorted(set(entry) - _allowed)
    if _extra:
        # {contains: x, length: 2} must not quietly judge only the first half
        raise TaskError('{}: unknown key(s) {} for this check'.format(where, ', '.join(_extra)))
    if 'json' in entry:
        return _json_check(entry, output, where)
    if len(_ops) != 1:
        raise TaskError('{}: a check has exactly one of {}, got {}'.format(
            where, ', '.join(_CHECK_OPS), ', '.join(_ops) or 'none'))
    _op, _want = _ops[0], entry[_ops[0]]
    _text = output_text(output)
    _what = entry.get('what') or ''
    if _op == 'equals':
        return _equals_check(output, _want)
    if _op == 'contains':
        _ok = str(_want) in _text
        return Check(name='输出包含 {}'.format(_what or brief(_want, 60)), ok=_ok,
                     expr='输出：{}'.format(brief(_text, 160)), src=OUTPUT,
                     claim='output contains {!r}'.format(_want))
    if _op == 'not_contains':
        _ok = str(_want) not in _text
        # like never_says: the evidence does not repeat what must not be there
        return Check(name='输出不包含 {}'.format(_what or brief(_want, 60)), ok=_ok,
                     expr='不包含' if _ok else '输出里出现了 {}'.format(_what or '不该出现的内容'), src=OUTPUT,
                     claim='output does not contain {!r}'.format(_want))
    if _op == 'regex':
        _re = _compile(_want, where)
        _ok = _re.fullmatch(_text.strip()) is not None
        return Check(name='输出匹配 /{}/'.format(_want), ok=_ok, expr='输出：{}'.format(brief(_text.strip(), 160)),
                     src=OUTPUT, claim='output matches /{}/'.format(_want))
    if _op == 'one_of':
        if not isinstance(_want, list):
            raise TaskError('{}: one_of needs a list'.format(where))
        _value = output if not _is_conversation(output) else _text
        _ok = any(_equal(_value, _o) for _o in _want)
        return Check(name='输出是 {} 之一'.format(brief(_want, 60)), ok=_ok,
                     expr='输出：{}'.format(brief(_text.strip(), 160)), src=OUTPUT,
                     claim='output in {!r}'.format(_want))
    # schema
    _body, _why = _structured(output)
    _schema = _read_data(task_file(task, _want))
    _claim = 'output conforms to {}'.format(_want)
    if _why:
        return Check(name='输出符合 {}'.format(_want), ok=False, expr=_why, src=OUTPUT, claim=_claim)
    import jsonschema
    try:
        jsonschema.validate(instance=_body, schema=_schema)
    except jsonschema.ValidationError as exc:
        _at = '/'.join(str(_p) for _p in exc.absolute_path) or '(根)'
        return Check(name='输出符合 {}'.format(_want), ok=False, expr='{}：{}'.format(_at, brief(exc.message, 160)),
                     src=OUTPUT, claim=_claim)
    except jsonschema.SchemaError as exc:
        raise TaskError('{}: {} is not a valid JSON Schema: {}'.format(where, _want, exc.message))
    return Check(name='输出符合 {}'.format(_want), ok=True, expr='符合', src=OUTPUT, claim=_claim)


def _equals_check(output, want) -> Check:
    if isinstance(want, (dict, list)):
        _value, _ = _structured(output)                   # a structured answer: compare as data
    elif _is_conversation(output):
        _value = output_text(output)
    else:
        _value = output
    _ok = _value is not MISSING and _equal(_value, want)
    return Check(name='输出等于 {}'.format(brief(want, 60)), ok=_ok,
                 expr='输出：{}'.format(brief(output_text(output).strip(), 160)), src=OUTPUT,
                 claim='output == {!r}'.format(want))


def _json_check(entry: Dict[str, Any], output, where: str) -> Check:
    _path = entry['json']
    if not isinstance(_path, str) or not _path.startswith('$'):
        raise TaskError('{}: json takes a path starting with $, e.g. $.order_id'.format(where))
    _ops = [_k for _k in _JSON_OPS if _k in entry]
    if len(_ops) != 1:
        raise TaskError('{}: json needs exactly one of {}'.format(where, ', '.join(_JSON_OPS)))
    if 'tolerance' in entry and _ops != ['approx']:
        raise TaskError('{}: tolerance goes with approx'.format(where))
    _op, _want = _ops[0], entry[_ops[0]]
    _body, _why = _structured(output)
    _value, _reason = (MISSING, _why) if _why else resolve(_body, _path[1:].lstrip('.'))
    _label = '{} {}'.format(_path, {'equals': '==', 'approx': '≈', 'length': '长度 =',
                                    'exists': '存在' if _want else '不存在'}[_op])
    if _op == 'exists':
        if not isinstance(_want, bool):
            raise TaskError('{}: exists is true or false'.format(where))
        _ok = (_value is not MISSING) == _want
        return Check(name=_label, ok=_ok, expr=_reason or '值：{}'.format(brief(_value, 120)), src=OUTPUT,
                     claim='{} exists == {}'.format(_path, _want))
    _label += ' {}'.format(brief(_want, 60))
    if _value is MISSING:
        return Check(name=_label, ok=False, expr=_reason, src=OUTPUT, claim='{} {} {!r}'.format(_path, _op, _want))
    if _op == 'equals':
        _ok = _equal(_value, _want)
    elif _op == 'length':
        if _number(_want) is None:
            raise TaskError('{}: length needs a number'.format(where))
        _ok = isinstance(_value, (list, dict, str)) and len(_value) == int(_want)
    else:
        _ok = comparison({'approx': _want, 'tolerance': entry.get('tolerance', 0)}, where)(_value)
        _want = '{} ± {}'.format(_want, entry.get('tolerance', 0))
    return Check(name=_label, ok=_ok, expr='值：{}'.format(brief(_value, 120)), src=OUTPUT,
                 claim='{} {} {}'.format(_path, _op, _want))


# -- the grader ----------------------------------------------------------------------------------

def _list(value, where: str) -> list:
    if not isinstance(value, list):
        raise TaskError('{} is a list'.format(where))
    return value


def _pattern_entry(entry, where: str):
    if isinstance(entry, str):
        return entry, '', entry
    if isinstance(entry, dict) and 'pattern' in entry:
        _extra = sorted(set(entry) - {'pattern', 'what'} - set(ATTRIBUTES))
        if _extra:
            raise TaskError('{}: unknown key(s) {}'.format(where, ', '.join(_extra)))
        _compile(entry['pattern'], where)
        return entry['pattern'], entry.get('what') or '', entry
    raise TaskError('{}: write {{pattern: \'...\', what: ...}}'.format(where))


def _tool_entry(entry, where: str):
    if isinstance(entry, str):
        return entry, {}, entry
    if isinstance(entry, dict) and isinstance(entry.get('tool'), str):
        _extra = sorted(set(entry) - {'tool', 'args'} - set(ATTRIBUTES))
        if _extra:
            raise TaskError('{}: unknown key(s) {}'.format(where, ', '.join(_extra)))
        return entry['tool'], _args(entry.get('args'), where), entry
    raise TaskError('{}: write {{tool: name, args: {{...}}}}'.format(where))


def _world_state(world, task):
    _w = world(task)
    return copy.deepcopy(_w.snapshot())


def grade(task, result, world: Optional[Callable] = None, skip: Iterable[str] = ()) -> List[Graded]:
    """
    Judge `result` by `task.expected` (docs/guide/eval-dataset.md §5).

    :param world: task -> a fresh world with call(name, **args) and
                  snapshot(). Needed for `state` (unless the task has an
                  initial_state.fixture) and to replay a reference written
                  as tool calls.
    :param skip:  `expected` keys the spec judges itself.
    :raises TaskError: on anything in the task it cannot read -- attributed
                  to the task, and reported by `ipandora eval selfcheck`.
    """
    _expected = task.expected
    if not isinstance(_expected, dict):
        raise TaskError('task {}: expected is a mapping (docs/guide/eval-dataset.md §5)'.format(task.id))
    _skip = set(skip)
    _unknown = sorted(set(_expected) - set(KNOWN) - _skip)
    if _unknown:
        raise TaskError('task {}: expected.{} is not judged by the standard grader; judge it in the spec '
                        'and name it in skip (judged: {})'.format(task.id, ', expected.'.join(_unknown),
                                                                   ', '.join(KNOWN)))
    _keys = [_k for _k in KNOWN if _k in _expected and _k not in _skip]
    _output = result.output
    _replayed = False
    if getattr(result, 'is_reference', False) and isinstance(_output, list) \
            and any(_k in MULTI_TURN for _k in _keys):
        # a reference written as tool calls: replay it on a fresh world. Only
        # the reference -- an agent's list output is judged, never executed
        if world is None:
            raise TaskError('task {}: the reference is tool calls; replaying them needs world='.format(task.id))
        _w = world(task)
        result = dialogue.replay(_output, _w.call, state=_w.snapshot)
        _output, _replayed = result.output, True

    _out: List[Graded] = []
    _where = 'task {}: expected'.format(task.id)
    if 'answer' in _keys:
        _out.append(Graded(_equals_check(_output, _expected['answer'])))
    for _i, _entry in enumerate(_list(_expected['checks'], _where + '.checks') if 'checks' in _keys else ()):
        _at = '{}.checks[{}]'.format(_where, _i)
        if not isinstance(_entry, dict):
            raise TaskError('{}: a check is a mapping, e.g. {{contains: A1004}}'.format(_at))
        _out.append(_graded(_output_check(_entry, _output, task, _at), _entry))

    if 'state' in _keys:
        _out.append(_state_check(task, _expected['state'], _output, world, _where + '.state'))

    for _i, _entry in enumerate(_list(_expected['called'], _where + '.called') if 'called' in _keys else ()):
        _tool, _a, _raw = _tool_entry(_entry, '{}.called[{}]'.format(_where, _i))
        _out.append(_graded(dialogue.called(result, _tool, **_a), _raw))
    for _i, _entry in enumerate(_list(_expected['not_called'], _where + '.not_called')
                                if 'not_called' in _keys else ()):
        _tool, _a, _raw = _tool_entry(_entry, '{}.not_called[{}]'.format(_where, _i))
        _out.append(_graded(dialogue.not_called(result, _tool, **_a), _raw))
    if 'called_at_most' in _keys:
        _limits = _expected['called_at_most']
        if not isinstance(_limits, dict):
            raise TaskError('{}.called_at_most is a mapping of tool: times'.format(_where))
        for _tool, _times in sorted(_limits.items()):
            if isinstance(_times, bool) or not isinstance(_times, int) or _times < 0:
                raise TaskError('{}.called_at_most.{}: a whole number'.format(_where, _tool))
            _out.append(Graded(dialogue.called_at_most(result, str(_tool), _times)))
    if 'no_loops' in _keys:
        _n = _expected['no_loops']
        if _n is True:
            _n = 3
        if _n is not False:
            if isinstance(_n, bool) or not isinstance(_n, int) or _n < 2:
                raise TaskError('{}.no_loops: true, or how many repeats count as a loop (2 or more)'.format(_where))
            _out.append(Graded(dialogue.no_loops(result, _n)))
    if 'finished' in _keys:
        if not isinstance(_expected['finished'], bool):
            raise TaskError('{}.finished is true or false'.format(_where))
        if _expected['finished']:
            _out.append(Graded(dialogue.finished(result)))

    # a reference of tool calls says nothing: `says` is left to real conversations
    for _i, _entry in enumerate(_list(_expected['says'], _where + '.says')
                                if 'says' in _keys and not _replayed else ()):
        _p, _what, _raw = _pattern_entry(_entry, '{}.says[{}]'.format(_where, _i))
        _out.append(_graded(dialogue.says(result, _p, _what), _raw))
    for _i, _entry in enumerate(_list(_expected['never_says'], _where + '.never_says')
                                if 'never_says' in _keys else ()):
        _p, _what, _raw = _pattern_entry(_entry, '{}.never_says[{}]'.format(_where, _i))
        _out.append(_graded(dialogue.never_says(result, _p, _what), _raw))
    return _out


def _state_check(task, spec, output, world, where: str) -> Graded:
    if not isinstance(spec, dict) or 'changes' not in spec:
        raise TaskError('{}: write {{changes: {{...}}, ignore: [...]}}'.format(where))
    _extra = sorted(set(spec) - {'changes', 'ignore'} - set(ATTRIBUTES))
    if _extra:
        raise TaskError('{}: unknown key(s) {}'.format(where, ', '.join(_extra)))
    _ignore = spec.get('ignore') or []
    if not isinstance(_ignore, list) or not all(isinstance(_p, str) for _p in _ignore):
        raise TaskError('{}.ignore is a list of paths'.format(where))
    # the world the agent starts in is the truth; the fixture only without one
    _initial = _world_state(world, task) if world is not None else initial_state(task)
    if _initial is None:
        raise TaskError('{}: the initial state is needed: give the spec a world(), or the task an '
                        'initial_state.fixture'.format(where))
    _want = expected_state(_initial, spec['changes'], task.id)
    if not isinstance(output, dict) or 'state' not in output or output['state'] is None:
        return _graded(Check(name='终态与预期一致', ok=False,
                             expr='结果里没有终态：converse()/replay() 要传 state=', src=dialogue.STATE,
                             claim='end state == expected'), spec)
    return _graded(dialogue.same_state(output['state'], _want, ignore=_ignore), spec)


def grader(world: Optional[Callable] = None, skip: Iterable[str] = ()) -> Callable:
    """`grade(task, result)` for a spec: the standard grader with this world."""
    _skip = tuple(skip)

    def _grade(task, result):
        return grade(task, result, world=world, skip=_skip)
    _grade.standard = True
    return _grade


__all__ = ['grade', 'grader', 'initial_state', 'expected_state', 'comparison', 'output_text', 'task_file',
           'TaskError', 'KNOWN', 'COMPARISONS']

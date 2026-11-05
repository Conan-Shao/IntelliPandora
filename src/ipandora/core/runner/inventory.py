# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : inventory.py
@Time  : 2026-11-05

The judgement inventory: what each case checked, and whether that got weaker.

pytest answers "did anything fail". It cannot answer "is this pass as strong
as the last one", because a passing assert leaves no trace. Here every
judgement is recorded -- Checks, plain asserts that held, pytest.raises -- so
a run can be compared with a baseline:

    - removed     data.items[*].price > 0
    ~ loosened    data.fee <= 100   ->  data.fee <= 1000
    ~ changed     data.status == 'paid'  ->  data.status == 'pending'
    -> skipped    test_refund       was passing, now skipped
    o unverified  test_cancel       passes, judges nothing

Why this matters now: when an agent writes the code and its tests in the same
turn, a green run proves less. Studies of coding agents find most of their
shortcuts are edits to the tests themselves. The usual guard counts `assert`
lines in a diff, which cannot tell `<= 100` from `<= 1000`. This compares
what actually ran, so a same-length rewrite, an assert moved into a helper,
or a parametrised case expanding differently are all visible.

The baseline is a file, conf/judgements.json by default, meant to be
committed. Updating it is deliberate (`ipandora run --update-baseline`), and
the update shows up in review as a short diff of judgements -- which is the
thing a reviewer actually needs to see. Protect that one file (CODEOWNERS)
and an agent can still edit tests freely, but cannot weaken them unseen.

Deterministic, offline, no LLM -- like every other verdict in the framework.
"""
import json
import os
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from ipandora.core.runner.result import PASSED, SKIPPED, RunResult
from ipandora.core.schedule import config

VERSION = 1
DEFAULT_NAME = 'judgements.json'

# entry states
S_PASSED, S_SKIPPED, S_EXCLUDED, S_UNVERIFIED = 'passed', 'skipped', 'excluded', 'unverified'

# finding kinds
REMOVED, LOOSENED, TIGHTENED, CHANGED, ADDED = 'removed', 'loosened', 'tightened', 'changed', 'added'
NOW_SKIPPED, NOW_EXCLUDED, UNVERIFIED, DELETED, NEW_CASE = (
    'now_skipped', 'now_excluded', 'unverified', 'deleted', 'new_case')

WEAKENING = frozenset({REMOVED, LOOSENED, CHANGED, NOW_SKIPPED, NOW_EXCLUDED,
                       UNVERIFIED, DELETED})
"""
Kinds that fail --fail-on-weakened. CHANGED is in: `== 100` becoming `== 200`
may be a spec change or may be the expected value bent to match a wrong
output, and only a person can tell. TIGHTENED, ADDED and NEW_CASE are not.
"""

# what a reader sees in front of each kind
MARK = {REMOVED: '-', LOOSENED: '~', TIGHTENED: '+', CHANGED: '~', ADDED: '+',
        NOW_SKIPPED: '→', NOW_EXCLUDED: '→', UNVERIFIED: '○', DELETED: '-',
        NEW_CASE: '+'}
LABEL = {REMOVED: '删除', LOOSENED: '放宽', TIGHTENED: '收紧', CHANGED: '改变',
         ADDED: '新增', NOW_SKIPPED: '改为跳过', NOW_EXCLUDED: '被排除',
         UNVERIFIED: '零判定', DELETED: '用例删除', NEW_CASE: '新用例'}


def default_path() -> str:
    return os.path.join(config.project_conf_dir(), DEFAULT_NAME)


# --------------------------------------------------------------------------
# building and storing
# --------------------------------------------------------------------------

def _claims(case) -> List[str]:
    return sorted({(_c.get('claim') or _c.get('name') or '')
                   for _c in case.checks if _c.get('kind', 'assert') != 'gap'} - {''})


def case_entry(case) -> Optional[Dict[str, Any]]:
    """
    What one case says about its own judgements -- or None when it says
    nothing reliable. A failed case stopped part-way, so the judgements it
    did not reach would read as removed; it is left out and compared again
    once it passes.
    """
    if case.outcome == PASSED:
        if case.unverified:
            return {'state': S_UNVERIFIED, 'claims': []}
        return {'state': S_PASSED, 'claims': _claims(case)}
    if case.outcome == SKIPPED:
        return {'state': S_SKIPPED, 'claims': [], 'reason': case.message or ''}
    return None


def build(result: RunResult) -> Dict[str, Any]:
    _cases = {}
    for _case in result.cases:
        _entry = case_entry(_case)
        if _entry is not None:
            _cases[_case.nodeid] = _entry
    for _nodeid in result.deselected or ():
        _cases.setdefault(_nodeid, {'state': S_EXCLUDED, 'claims': []})
    return {'version': VERSION, 'selector': result.selector, 'cases': _cases}


def load(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as _f:
        _data = json.load(_f)
    if not isinstance(_data, dict) or not isinstance(_data.get('cases'), dict):
        raise ValueError('{} is not a judgement inventory'.format(path))
    return _data


def save(path: str, inventory: Dict[str, Any]) -> str:
    _dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(_dir, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as _f:
        # one case per block and sorted keys: the file is reviewed as a diff
        json.dump(inventory, _f, ensure_ascii=False, indent=2, sort_keys=True)
        _f.write('\n')
    return os.path.abspath(path)


def updated(old: Optional[Dict[str, Any]], result: RunResult) -> Dict[str, Any]:
    """
    The baseline after accepting this run.

    Cases this run said nothing reliable about (failed, errored, or simply
    not selected) keep their old entry. A run over the same selector as the
    baseline drops cases that no longer exist; a narrower run cannot know.
    """
    _new = build(result)
    if not old:
        return _new
    _same_scope = (old.get('selector') or '') == (result.selector or '')
    _present = {_c.nodeid for _c in result.cases} | set(result.deselected or ())
    _cases = {}
    for _nodeid, _entry in old.get('cases', {}).items():
        if _same_scope and _nodeid not in _present:
            continue
        _cases[_nodeid] = _entry
    _cases.update(_new['cases'])
    return {'version': VERSION, 'selector': old.get('selector', result.selector),
            'cases': _cases}


# --------------------------------------------------------------------------
# comparing
# --------------------------------------------------------------------------

@dataclass
class Finding:
    kind: str
    nodeid: str
    before: str = ''
    after: str = ''
    note: str = ''

    @property
    def weakening(self) -> bool:
        return self.kind in WEAKENING

    @property
    def case(self) -> str:
        return self.nodeid.split('::')[-1] if '::' in self.nodeid else self.nodeid

    def line(self) -> str:
        _what = {
            LOOSENED: '{} → {}', TIGHTENED: '{} → {}', CHANGED: '{} → {}',
        }.get(self.kind)
        _body = _what.format(self.before, self.after) if _what else (self.before or self.after)
        _tail = '  ({})'.format(self.note) if self.note else ''
        return '{} {}  {}  {}{}'.format(MARK[self.kind], LABEL[self.kind], self.case,
                                        _body, _tail).rstrip()

    def to_dict(self) -> Dict[str, Any]:
        _out = asdict(self)
        _out.update({'weakening': self.weakening, 'label': LABEL[self.kind],
                     'case': self.case, 'line': self.line()})
        return _out


_OPERATOR = re.compile(
    r'\s(<=|>=|==|!=|<|>|not in|in|contains|starts with|matches|exists|is|conforms to schema)(?:\s|$)')
_DECIMAL = re.compile(r"""^Decimal\(['"](.+)['"]\)$""")
_UPPER, _LOWER = ('<', '<='), ('>', '>=')


def parse(claim: str):
    """(subject, operator, operand) -- or (claim, '', '') when there is no operator."""
    _text = claim[len('assert '):] if claim.startswith('assert ') else claim
    _match = _OPERATOR.search(_text)
    if not _match:
        return _text.strip(), '', ''
    return (_text[:_match.start()].strip(), _match.group(1),
            _text[_match.end():].strip())


def _number(text: str) -> Optional[Decimal]:
    _text = text.strip()
    _m = _DECIMAL.match(_text)
    if _m:
        _text = _m.group(1)
    try:
        _d = Decimal(_text)
    except (InvalidOperation, ValueError):
        return None
    return _d if _d.is_finite() else None


def classify(old: str, new: str) -> str:
    """
    LOOSENED, TIGHTENED or CHANGED for two claims about the same subject.

    Only a numeric bound has a direction anyone can state without knowing
    the domain: `<= 100` to `<= 1000` admits more values. Everything else is
    CHANGED, which is gated -- deciding whether a new expected value is a
    spec change or a test bent to fit is exactly the call a person makes.
    """
    _, _old_op, _old_v = parse(old)
    _, _new_op, _new_v = parse(new)
    _a, _b = _number(_old_v), _number(_new_v)
    if _a is None or _b is None:
        return CHANGED
    for _family, _wider in ((_UPPER, lambda x, y: y > x), (_LOWER, lambda x, y: y < x)):
        if _old_op in _family and _new_op in _family:
            if _a == _b:
                # same bound, strictness changed: < to <= admits the bound itself
                _strict_before, _strict_after = len(_old_op) == 1, len(_new_op) == 1
                if _strict_before and not _strict_after:
                    return LOOSENED
                if _strict_after and not _strict_before:
                    return TIGHTENED
                return CHANGED
            return LOOSENED if _wider(_a, _b) else TIGHTENED
    return CHANGED


def _diff_claims(nodeid: str, before: List[str], after: List[str]) -> List[Finding]:
    _removed = sorted(set(before) - set(after))
    _added = sorted(set(after) - set(before))
    _findings = []
    _unpaired_added = list(_added)
    for _old in _removed:
        _subject = parse(_old)[0]
        _partner = next((_n for _n in _unpaired_added if parse(_n)[0] == _subject), None)
        if _partner is None:
            _findings.append(Finding(REMOVED, nodeid, before=_old))
            continue
        _unpaired_added.remove(_partner)
        _findings.append(Finding(classify(_old, _partner), nodeid, before=_old, after=_partner))
    _findings.extend(Finding(ADDED, nodeid, after=_n) for _n in _unpaired_added)
    return _findings


def compare(baseline: Optional[Dict[str, Any]], result: RunResult) -> List[Finding]:
    """Everything that changed in what the suite judges, weakening first."""
    if not baseline:
        return []
    _base = baseline.get('cases', {})
    _now = build(result)['cases']
    _messages = {_c.nodeid: _c.message for _c in result.cases}
    _findings = []

    for _nodeid, _entry in _now.items():
        _before = _base.get(_nodeid)
        _state = _entry['state']

        if _state == S_UNVERIFIED:
            # judging nothing is reported whether the case is new or had
            # judgements before -- except when the baseline already accepted it
            if not _before or _before.get('state') != S_UNVERIFIED:
                _n = len((_before or {}).get('claims', []))
                _findings.append(Finding(UNVERIFIED, _nodeid, before='通过，但没有任何判定',
                                         note='基线里有 {} 条判定'.format(_n) if _n else '新用例'))
            continue

        if _before is None:
            if _state == S_PASSED:
                _findings.append(Finding(NEW_CASE, _nodeid,
                                         after='{} 条判定'.format(len(_entry['claims']))))
            continue

        if _before.get('state') != S_PASSED:
            continue    # was not passing before: nothing to weaken
        if _state == S_SKIPPED:
            _findings.append(Finding(NOW_SKIPPED, _nodeid, before='原本通过',
                                     note=(_messages.get(_nodeid) or '')[:120]))
        elif _state == S_EXCLUDED:
            _findings.append(Finding(NOW_EXCLUDED, _nodeid, before='原本通过',
                                     note='被 -m / --exclude-flaky 排除'))
        elif _state == S_PASSED:
            _findings.extend(_diff_claims(_nodeid, _before.get('claims', []), _entry['claims']))

    if (baseline.get('selector') or '') == (result.selector or ''):
        _present = {_c.nodeid for _c in result.cases} | set(result.deselected or ())
        for _nodeid, _before in _base.items():
            if _nodeid not in _present and _before.get('state') == S_PASSED:
                _findings.append(Finding(DELETED, _nodeid, before='用例不见了',
                                         note='基线里有 {} 条判定'.format(
                                             len(_before.get('claims', [])))))

    _findings.sort(key=lambda _f: (not _f.weakening, _f.nodeid, _f.kind))
    return _findings

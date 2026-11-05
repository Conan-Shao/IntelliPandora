# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : junit.py
@Time  : 2026-11-05

JUnit XML, rendered from the same ReportData the HTML report is built from.

This is the format CI gates on and qa-report-visualizer reads, so it is the
one output whose *shape* is not ours to choose. What is ours to choose is what
happens to the three outcomes JUnit has no word for -- and that choice is the
whole content of this module.

Why not `pytest --junitxml`
---------------------------
pytest can write this file itself, and it would be two lines to pass the flag
through. But pytest's view of a run is the one the assertion layer was built
to replace: one failure message per test, re-parsed out of a string. ReportData
carries every Check as the assertion layer made it, the triage verdict, the
coverage dimensions and the declared gaps. Rendering from it keeps the XML and
the HTML telling the same story, and keeps the redaction that already happened
once in the builder.

The lossy part, stated plainly
------------------------------
JUnit knows four outcomes: pass, failure, error, skipped. This framework has
six. BLOCKED ("written, but never reached") and GAP ("a check that should
exist and does not") have no equivalent, and both get written as `<skipped>`.

That loses information, so nothing is left to the reader's inference: the real
status goes in the element's `type` attribute, in its message, and in a
`<property>` on the case. A consumer that only understands JUnit sees "not
run", which is true; a consumer that looks closer gets the real word.

What must never happen is the reverse -- something unresolved reading as a
pass. Two guards for that:

  * a collection error becomes a real `<testcase>` carrying `<error>`. Without
    it a failed collection produces `tests="0"`, and a JUnit file with no
    tests is green in every CI there is. That is this repo's recurring bug
    shape: the failure that looks exactly like success.
  * GAP and BLOCKED are counted in `skipped`, never omitted and never folded
    into the pass count.
"""
import re
import xml.etree.ElementTree as ET
from typing import Dict, List
from xml.dom import minidom

from ipandora.core.report.model import ReportCase, ReportData, Status

COLLECT_ERROR_CASE = 'collection'
"""Name of the synthetic case that carries a collection failure."""

# XML 1.0 forbids most C0 control characters outright -- they cannot be
# escaped, only removed. Response bodies and tracebacks contain them, and a
# parser that hits one rejects the whole document, so a single stray byte in
# one assertion message would cost the entire run its report.
_ILLEGAL = re.compile(
    u'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f﷐-﷟￾￿]')

# How each status is written. (element, type attribute) -- None means the case
# is reported bare, i.e. passed.
_OUTCOME = {
    Status.PASS: (None, ''),
    Status.FAIL: ('failure', 'assertion'),
    Status.ERROR: ('error', 'error'),
    Status.SKIPPED: ('skipped', 'precondition'),
    Status.BLOCKED: ('skipped', 'blocked'),
    Status.GAP: ('skipped', 'gap'),
    Status.UNVERIFIED: ('skipped', 'unverified'),
}

_SKIP_NOTE = {
    Status.SKIPPED: '前置条件不满足，本条没有对产品做出任何判断',
    Status.BLOCKED: '上游失败导致本条未被执行（JUnit 无此状态，记为 skipped）',
    Status.GAP: '声明了应有而缺失的断言（JUnit 无此状态，记为 skipped）',
    Status.UNVERIFIED: '通过了但没有任何判定，只说明没有抛异常（JUnit 无此状态，记为 skipped）',
}


def clean(text) -> str:
    """Drop characters no XML parser will accept. Escaping happens downstream."""
    return _ILLEGAL.sub('', str(text or ''))


def _classname(case: ReportCase) -> str:
    """
    What CI groups by.

    pytest nodeids look like `test/testapi/test_order.py::TestX::test_y`.
    Most consumers expect a dotted class path, so the file part becomes dots
    and the test name is dropped -- it is already the testcase name.
    """
    _nodeid = case.nodeid or ''
    _path = _nodeid.split('::')[0] if '::' in _nodeid else _nodeid
    _parts = [_p for _p in _nodeid.split('::')[1:-1]]
    _base = _path.rsplit('.', 1)[0].replace('/', '.').replace('\\', '.')
    return '.'.join([_p for _p in [_base] + _parts if _p]) or (case.suite or 'ipandora')


def _detail(case: ReportCase) -> str:
    """
    The body of a failure/error element.

    The message first, then every judgement the assertion layer made. Someone
    reading this in a CI log should not have to open the HTML report to see
    which check failed and on what value.
    """
    _lines = []
    if case.message:
        _lines.append(case.message)
    if case.reason:
        _lines.append('归因: {}{}'.format(
            case.reason, '（{}）'.format(case.category) if case.category else ''))
    if case.next_step:
        _lines.append('下一步: {}'.format(case.next_step))

    _checks = case.judgements
    if _checks:
        _lines.append('')
        _lines.append('判定 {} 条，失败 {} 条:'.format(len(_checks), case.checks_failed))
        for _check in _checks:
            _lines.append('  [{}] {} · {}'.format(
                'PASS' if _check.get('ok') else 'FAIL',
                _check.get('name') or '', _check.get('expr') or ''))
    for _gap in case.gaps:
        _lines.append('  [GAP ] {} · {}'.format(
            _gap.get('name') or '', _gap.get('expr') or ''))
    return clean('\n'.join(_lines))


def _properties(parent: ET.Element, case: ReportCase) -> None:
    _items = {}
    if case.status not in (Status.PASS, Status.FAIL, Status.ERROR):
        # the word JUnit threw away
        _items['ipandora.status'] = case.status
    if case.title:
        _items['ipandora.title'] = case.title
    if case.flaky:
        _items['ipandora.flaky'] = case.flaky
    if case.category:
        _items['ipandora.category'] = case.category
    for _axis, _value in (case.dims or {}).items():
        _items['ipandora.dim.{}'.format(_axis)] = _value
    if case.judgements:
        _items['ipandora.checks.passed'] = str(case.checks_passed)
        _items['ipandora.checks.failed'] = str(case.checks_failed)
    if case.gaps:
        _items['ipandora.checks.gap'] = str(len(case.gaps))

    if not _items:
        return
    _node = ET.SubElement(parent, 'properties')
    for _name, _value in _items.items():
        ET.SubElement(_node, 'property',
                      {'name': clean(_name), 'value': clean(_value)})


def _testcase(parent: ET.Element, case: ReportCase) -> None:
    _node = ET.SubElement(parent, 'testcase', {
        'name': clean(case.name or case.nodeid or 'case'),
        'classname': clean(_classname(case)),
        'time': '{:.3f}'.format(case.duration or 0.0),
    })
    _properties(_node, case)

    _tag, _type = _OUTCOME.get(case.status, ('error', 'unknown'))
    if _tag is None:
        return

    _message = case.message or _SKIP_NOTE.get(case.status, '') or case.status
    _element = ET.SubElement(_node, _tag, {
        'message': clean(_message)[:1000],
        'type': _type,
    })
    _body = _detail(case)
    if _tag == 'skipped':
        # A skip's body is advisory; keep the note so the lost status is
        # readable even where properties are not shown.
        _body = clean('\n'.join(
            _p for _p in (_SKIP_NOTE.get(case.status, ''), _body) if _p))
    if _body:
        _element.text = _body


def _collect_error_case(parent: ET.Element, report: ReportData) -> None:
    """
    A failed collection as a real, failing testcase.

    `tests="0" failures="0"` is indistinguishable from a clean run to CI. This
    is the one place where emitting something is safer than emitting nothing.
    """
    _node = ET.SubElement(parent, 'testcase', {
        'name': COLLECT_ERROR_CASE,
        'classname': 'ipandora',
        'time': '0.000',
    })
    _error = ET.SubElement(_node, 'error', {
        'message': clean(report.collect_error)[:1000],
        'type': 'collection',
    })
    _error.text = clean(
        '用例收集失败，本次运行没有执行任何用例。\n'
        '没有这条记录的话，XML 里会是 tests="0" failures="0"，在 CI 上读起来和全绿一样。\n\n'
        + (report.collect_error or ''))


def _counts(cases: List[ReportCase], collect_error: bool) -> Dict[str, str]:
    _failures = sum(1 for _c in cases if _c.status == Status.FAIL)
    _errors = sum(1 for _c in cases if _c.status == Status.ERROR)
    _skipped = sum(1 for _c in cases
                   if _c.status in (Status.SKIPPED, Status.BLOCKED, Status.GAP,
                                    Status.UNVERIFIED))
    return {
        'tests': str(len(cases) + (1 if collect_error else 0)),
        'failures': str(_failures),
        'errors': str(_errors + (1 if collect_error else 0)),
        'skipped': str(_skipped),
    }


def to_junit(report: ReportData, indent: bool = True) -> str:
    """Render the run as a JUnit XML document."""
    _collect_error = bool(report.collect_error)
    _root = ET.Element('testsuites', dict(
        name=clean(report.title or 'IntelliPandora'),
        time='{:.3f}'.format(report.duration or 0.0),
        **_counts(report.cases, _collect_error)))
    if report.judgement_changes:
        # JUnit has nowhere to put "this pass is weaker than the last one";
        # a property keeps it in the artifact for anything that looks.
        _props = ET.SubElement(_root, 'properties')
        ET.SubElement(_props, 'property', {
            'name': 'ipandora.judgements.weakened', 'value': str(len(report.weakened))})
        ET.SubElement(_props, 'property', {
            'name': 'ipandora.judgements.changed', 'value': str(len(report.judgement_changes))})

    # One <testsuite> per suite, so CI groups the way the source is organised.
    _groups = report.by_suite if report.cases else {}
    for _suite, _cases in _groups.items():
        _node = ET.SubElement(_root, 'testsuite', dict(
            name=clean(_suite),
            time='{:.3f}'.format(sum(_c.duration or 0.0 for _c in _cases)),
            **_counts(_cases, False)))
        if report.generated:
            _node.set('timestamp', clean(report.generated))
        if report.run_id:
            _node.set('hostname', clean(report.run_id))
        for _case in _cases:
            _testcase(_node, _case)

    if _collect_error:
        _node = ET.SubElement(_root, 'testsuite', dict(
            name='ipandora.collection', tests='1', failures='0',
            errors='1', skipped='0', time='0.000'))
        _collect_error_case(_node, report)

    _raw = ET.tostring(_root, encoding='unicode')
    if not indent:
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + _raw
    return minidom.parseString(_raw).toprettyxml(indent='  ', encoding=None)

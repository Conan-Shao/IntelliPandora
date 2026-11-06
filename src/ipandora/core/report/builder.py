# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : builder.py
@Time  : 2026-08-01
"""
import dataclasses
import os
from datetime import datetime
from typing import Any, Dict

from ipandora.core.report.model import ReportCase, ReportData, Status
from ipandora.core.report.redact import redact, redact_body

EMBEDDED = ('screenshot', 'golden', 'actual', 'diff')
"""Artifact kinds shown as images in the report."""

MAX_EMBEDDED_SCREENSHOT = 2 * 1024 * 1024
"""Bytes. Larger screenshots are linked by path instead of embedded."""
from ipandora.core.triage import triage as run_triage

# runner outcome -> report status
OUTCOME_STATUS = {
    'passed': Status.PASS,
    'failed': Status.FAIL,
    'error': Status.ERROR,
    'skipped': Status.SKIPPED,
}


def suite_of(nodeid: str) -> str:
    """The file a case came from, used to group the report."""
    _path = nodeid.split('::', 1)[0]
    return os.path.basename(_path) or 'default'


def _redact_exchange(exchange: Dict[str, Any]) -> Dict[str, Any]:
    """
    An exchange, safe to publish.

    Bodies go through redact_body rather than redact: a body is a string, and
    plain string redaction only ever applied the value-shape patterns -- so a
    field literally named `token` survived, because the rule that knows what
    `token` means only looks at dict keys.
    """
    _out = redact(dict(exchange or {}))
    for _side in ('request_body', 'response_body'):
        if _side in _out:
            _out[_side] = redact_body((exchange or {}).get(_side))
    return _out


def _artifact(artifact: dict) -> dict:
    """
    A failure's screenshot, embedded; its trace, as the command that opens it.

    Embedded rather than linked: a report is archived and passed around (a CI
    artifact, a link in a chat), and the run's own files do not travel with
    it. A trace is a zip meant for Playwright's viewer, so it stays a path.
    """
    import base64
    _kind = artifact.get('kind', '')
    _path = artifact.get('path', '')
    _out = {'kind': _kind, 'path': _path, 'src': '', 'command': ''}
    _out['group'] = artifact.get('group', '')
    if _kind in EMBEDDED:
        try:
            if os.path.getsize(_path) <= MAX_EMBEDDED_SCREENSHOT:
                with open(_path, 'rb') as _f:
                    _out['src'] = 'data:image/png;base64,' + base64.b64encode(_f.read()).decode()
        except OSError:
            pass
    elif _kind == 'trace':
        _out['command'] = 'playwright show-trace "{}"'.format(_path)
    elif _kind == 'history':
        _out['command'] = artifact.get('command', '')     # core/consistency.py: re-check it by hand
    return _out


def build_from_run(result, title: str = None, include_triage: bool = True) -> ReportData:
    """
    Build report data from a RunResult.

    Secrets are stripped here, before anything is serialised or rendered --
    see redact.py for why that has to happen on this side.
    """
    _report = None
    if include_triage:
        _report = run_triage(result, include_skipped=True)

    _findings = {_f.nodeid: _f for _f in (_report.findings if _report else [])}

    _cases = []
    for _case in getattr(result, 'cases', []):
        _finding = _findings.get(_case.nodeid)
        _cases.append(ReportCase(
            name=_case.name,
            nodeid=_case.nodeid,
            status=(Status.UNVERIFIED if getattr(_case, 'unverified', False)
                    else OUTCOME_STATUS.get(_case.outcome, Status.ERROR)),
            duration=round(_case.duration, 3),
            message=redact(_case.message or (
                '通过了，但没有任何判定：没有 Check、没有成立的 assert、没有 pytest.raises'
                if getattr(_case, 'unverified', False) else '')),
            category=_finding.category if _finding else '',
            reason=redact(_finding.reason) if _finding else '',
            next_step=_finding.next_step if _finding else '',
            confidence=_finding.confidence if _finding else '',
            suite=suite_of(_case.nodeid),
            title=getattr(_case, 'title', ''),
            dims=dict(getattr(_case, 'dims', {}) or {}),
            flaky=redact(getattr(_case, 'flaky', '') or ''),
            # Evidence is the richest thing in the report and therefore the
            # likeliest to carry a credential: an Authorization header sits in
            # every request. It goes through the same redaction as everything
            # else, before it is ever written.
            checks=redact(list(getattr(_case, 'checks', []) or [])),
            exchanges=[_redact_exchange(_e)
                       for _e in (getattr(_case, 'exchanges', []) or [])],
            artifacts=[_artifact(_a) for _a in (getattr(_case, 'artifacts', []) or [])],
            faults=redact(list(getattr(_case, 'faults', []) or []))))

    return ReportData(
        title=title or 'IntelliPandora Test Report',
        run_id=getattr(result, 'run_id', ''),
        selector=redact(getattr(result, 'selector', '')),
        env=getattr(result, 'env', ''),
        generated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        duration=getattr(result, 'duration', 0.0),
        cases=_cases,
        triage=redact(_report.to_dict()) if _report else {},
        coverage=list(getattr(result, 'coverage', []) or []),
        collect_error=redact(getattr(result, 'collect_error', '')),
        baseline=getattr(result, 'baseline', '') or '',
        # claims quote expected values, which can be anything a test compared
        judgement_changes=redact(list(getattr(result, 'judgement_changes', []) or [])),
        against_baseline=dict(getattr(result, 'against_baseline', {}) or {}))


def build_from_dict(data: Dict[str, Any]) -> ReportData:
    """Rebuild report data from its serialised form."""
    _report = ReportData(
        title=data.get('title', ''),
        run_id=data.get('run_id', ''),
        selector=data.get('selector', ''),
        env=data.get('env', ''),
        generated=data.get('generated', ''),
        duration=data.get('duration', 0.0),
        triage=data.get('triage', {}),
        collect_error=data.get('collect_error', ''),
        baseline=data.get('baseline', ''),
        judgement_changes=list(data.get('judgement_changes', []) or []),
        against_baseline=dict(data.get('against_baseline', {}) or {}),
        against_run=dict(data.get('against_run', {}) or {}),
        view=data.get('view', 'tests') or 'tests',
        coverage=list(data.get('coverage_axes', []) or []),
        shards=list(data.get('shards', []) or []),
        merge_conflicts=list(data.get('merge_conflicts', []) or []),
        duplicates=int(data.get('duplicates', 0) or 0))
    # to_dict emits derived fields (checks_passed, gaps, ...) that are not
    # constructor arguments; drop them rather than have a round-trip fail.
    _fields = {_f.name for _f in dataclasses.fields(ReportCase)}
    _report.cases = [ReportCase(**{_k: _v for _k, _v in _c.items() if _k in _fields})
                     for _c in data.get('cases', [])]
    return _report

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : builder.py
@Time  : 2026-08-01
"""
import os
from datetime import datetime
from typing import Any, Dict

from ipandora.core.report.model import ReportCase, ReportData, Status
from ipandora.core.report.redact import redact
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
            status=OUTCOME_STATUS.get(_case.outcome, Status.ERROR),
            duration=round(_case.duration, 3),
            message=redact(_case.message or ''),
            category=_finding.category if _finding else '',
            reason=redact(_finding.reason) if _finding else '',
            next_step=_finding.next_step if _finding else '',
            suite=suite_of(_case.nodeid)))

    return ReportData(
        title=title or 'IntelliPandora Test Report',
        run_id=getattr(result, 'run_id', ''),
        selector=redact(getattr(result, 'selector', '')),
        env=getattr(result, 'env', ''),
        generated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        duration=getattr(result, 'duration', 0.0),
        cases=_cases,
        triage=redact(_report.to_dict()) if _report else {},
        collect_error=redact(getattr(result, 'collect_error', '')))


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
        collect_error=data.get('collect_error', ''))
    _report.cases = [ReportCase(**_c) for _c in data.get('cases', [])]
    return _report

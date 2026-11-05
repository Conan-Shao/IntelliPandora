# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-08-01

Test reporting.

    from ipandora.core.runner import run
    from ipandora.core.report import build, write

    report = build(run('test/api', quiet=True))
    write(report, 'out/')          # report.html + report.json + report.xml

Building and rendering are separate steps. The harness produces ReportData;
templates only consume it. That is what lets the same run back an HTML page
and a JSON artifact, and -- more importantly -- it is where secrets get
stripped, once, before anything is written. Masking in a template would
protect one view and leave the JSON behind it readable.

The report also shows what a run did *not* establish: skipped, blocked and
gap cases are counted separately and the pass rate excludes them. A suite that
skips half its cases is not 100% healthy, and saying so is the point.
"""
from ipandora.core.report.builder import build_from_dict, build_from_run
from ipandora.core.report.junit import to_junit
from ipandora.core.report.model import INCONCLUSIVE, ReportCase, ReportData, Status
from ipandora.core.report.redact import MASK, redact, redact_text
from ipandora.core.report.render import to_html, to_json, write
from ipandora.core.report.merge import merge, merge_files

# the common case
build = build_from_run

__all__ = [
    'build', 'build_from_run', 'build_from_dict',
    'ReportData', 'ReportCase', 'Status', 'INCONCLUSIVE',
    'to_html', 'to_json', 'to_junit', 'write', 'merge', 'merge_files',
    'redact', 'redact_text', 'MASK',
]

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-08-01

Failure triage.

    from ipandora.core.runner import run
    from ipandora.core.triage import triage

    report = triage(run('test/api'))
    report.headline()            # '2 defect, 1 environment'
    report.product_failures      # only the ones that implicate the product

Classification is rule-based: free, reproducible, and always on. A failure
that could not reach the endpoint is not the same thing as one where the
endpoint answered wrongly, and a suite that cannot tell them apart teaches
people to ignore red builds.

An optional LLM pass can add a natural-language root cause on top, but it
never decides a category and is off by default -- see
docs/design/03-LLM接入边界.md, and ipandora.ai.enable() to turn it on.
"""
from ipandora.core.triage.category import BLAMES_SYSTEM_UNDER_TEST, Category, Confidence
from ipandora.core.triage.hooks import analyze, has_analyzer, register_analyzer
from ipandora.core.triage.rules import (Finding, TriageReport, classify,
                                        failed_check_sources, triage)

__all__ = [
    'triage', 'classify', 'Finding', 'TriageReport', 'failed_check_sources',
    'Category', 'Confidence', 'BLAMES_SYSTEM_UNDER_TEST',
    'register_analyzer', 'has_analyzer', 'analyze',
]

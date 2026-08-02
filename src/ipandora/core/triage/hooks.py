# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : hooks.py
@Time  : 2026-08-01

Optional enrichment slot for triage.

core/ must never import ai/ -- basic test capability cannot be allowed to
acquire a paid, latent, non-reproducible dependency (see
docs/design/03-LLM接入边界.md). So core/ owns the *slot* and knows nothing
about who fills it; ipandora.ai.enable() registers an analyzer into it.

With nothing registered, everything here is a no-op returning ''. That is the
default, and it is what `rm -rf ai/` leaves behind.
"""
from typing import Callable, Optional

from ipandora.utils.log import logger

# (TriageReport, RunResult) -> str
Analyzer = Callable[[object, object], str]

_analyzer = None  # type: Optional[Analyzer]


def register_analyzer(analyzer: Optional[Analyzer]):
    """Install (or clear, with None) the enrichment analyzer."""
    global _analyzer
    _analyzer = analyzer
    logger.debug('triage analyzer %s', 'registered' if analyzer else 'cleared')


def has_analyzer() -> bool:
    return _analyzer is not None


def analyze(report, result) -> str:
    """
    Ask the registered analyzer for a root-cause summary.

    Fail-open by design: an analyzer that errors, times out or is not
    configured must not change the verdict of a test run. The rules already
    produced a classification; this only ever adds prose.
    """
    if _analyzer is None:
        return ''
    try:
        return _analyzer(report, result) or ''
    except Exception as exc:  # noqa: BLE001 - triage must never fail a run
        logger.warning('triage analyzer failed, continuing without it: %s', exc)
        return ''

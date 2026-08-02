# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-08-01

Optional LLM support.

Nothing here is imported by core/, and nothing here runs unless it is turned
on explicitly. `pip install intellipandora` does not install a model SDK, the
default config sets `ai.enabled: false`, and deleting this package leaves a
working framework -- CI asserts all three. See docs/design/03-LLM接入边界.md.

To turn it on:

    pip install intellipandora[ai]
    # conf/config.yaml -> ai.enabled: true, ai.provider, ai.api_key

    import ipandora.ai
    ipandora.ai.enable()
"""
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger


def enable(force: bool = False) -> bool:
    """
    Register the LLM analyzer with core's triage hook.

    Returns whether it was registered. Respects `ai.enabled` unless `force`
    is set, so importing this module is never enough on its own to start
    spending money.
    """
    if not force and not Runtime.Ai.enabled:
        logger.debug('ai.enabled is false; LLM triage stays off')
        return False

    from ipandora.ai.triage import analyze
    from ipandora.core.triage import register_analyzer

    register_analyzer(analyze)
    logger.info('LLM triage enabled (provider=%s, max %s calls/run)',
                Runtime.Ai.provider, Runtime.Ai.max_calls_per_run)
    return True


def disable():
    """Unregister the analyzer. Triage falls back to rules only."""
    from ipandora.core.triage import register_analyzer
    register_analyzer(None)


__all__ = ['enable', 'disable']

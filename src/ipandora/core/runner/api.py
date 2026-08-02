# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : api.py
@Time  : 2026-08-01
"""
import io
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from typing import List, Optional, Sequence

from ipandora.core.runner.collector import ResultCollector
from ipandora.core.runner.result import RunResult
from ipandora.core.runner import store
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.fileload import FileLoad
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

# Quiet, and no cache writes -- the caller gets structure from the collector,
# not from stdout.
#
# --import-mode=importlib matters for a library entry point. Under the default
# 'prepend' mode pytest keys imported test modules by basename in sys.modules,
# so a second in-process run over a different directory containing, say,
# another test_api.py aborts collection with "import file mismatch". Since
# run() is meant to be called repeatedly in one process (that is the whole
# point of not shelling out), the default mode is unusable here.
BASE_ARGS = ('-q', '--no-header', '-p', 'no:cacheprovider', '--import-mode=importlib')

# pytest exit codes that mean the run did not happen properly. 0 (all passed)
# and 1 (tests failed) are the two where the case results tell the story;
# for the rest there is nothing to report per-case, so the run must not read
# as ok just because no failures were recorded.
EXIT_CODE_REASONS = {
    2: 'the run was interrupted',
    3: 'pytest hit an internal error',
    4: 'pytest usage error -- check the selector',
    5: 'no tests were collected',
}


def new_run_id() -> str:
    return 'run-{}'.format(datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3])


def _load_env_settings(env: str) -> bool:
    """
    Overlay conf/<env>.yaml onto Runtime.settings, if that file exists.

    Returns whether anything was loaded. Environments are per-deployment, so a
    missing file is normal rather than an error.
    """
    if not env:
        return False
    _file = os.path.join(PathUtils().pandora_path, 'conf', '{}.yaml'.format(env))
    if not os.path.isfile(_file):
        logger.debug('no config for env %r at %s', env, _file)
        return False
    _settings = FileLoad(_file).load_yaml() or {}
    _merged = dict(Runtime.settings or {})
    _merged.update(_settings)
    Runtime.settings = _merged
    # config values memoise on first read, so previously-read ones would keep
    # the old environment's value without this
    Runtime.reset()
    return True


def run(selector: str = '', env: str = '', extra_args: Sequence[str] = (),
        persist: bool = True, quiet: bool = False) -> RunResult:
    """
    Execute tests and return a structured result.

    This is the single execution entry point. The pytest CLI and the MCP
    `run_tests` tool both come through here rather than each growing their own
    logic -- and specifically, MCP does not shell out to pytest and scrape
    stdout, which loses structure and floods an agent's context.

    :param selector: what to run -- a path, a nodeid, or a `-k` expression.
                     Empty means the whole suite.
    :param env:      environment name; overlays conf/<env>.yaml when present.
    :param extra_args: extra pytest arguments.
    :param persist:  archive the full run so explain_failure can retrieve it.
    :param quiet:    swallow pytest's own stdout/stderr. Required when the
                     caller is speaking a protocol over stdout -- an MCP stdio
                     server would otherwise interleave pytest's progress dots
                     into its JSON-RPC stream and break the connection.

    Note: pytest runs in-process, so test modules are imported into this
    interpreter and stay imported. Repeated runs therefore reuse module-level
    state; where a test suite depends on being freshly imported, use a new
    process. (Module *name* collisions between runs are handled -- see
    BASE_ARGS.)
    """
    try:
        import pytest
    except ImportError as exc:
        raise RuntimeError('pytest is required to run tests: {}'.format(exc))

    _run_id = new_run_id()
    _restore_env = bool(env) and _load_env_settings(env)
    _collector = ResultCollector()
    _args = _build_args(selector, extra_args)

    logger.info('run %s: pytest %s', _run_id, ' '.join(_args))
    _start = time.perf_counter()
    _sink = io.StringIO()
    try:
        if quiet:
            with redirect_stdout(_sink), redirect_stderr(_sink):
                _exit = pytest.main(list(_args), plugins=[_collector])
        else:
            _exit = pytest.main(list(_args), plugins=[_collector])
    finally:
        _duration = time.perf_counter() - _start
        if _restore_env:
            Runtime.reset()

    _collect_error = '\n'.join(_collector.collect_errors)
    if not _collect_error and int(_exit) in EXIT_CODE_REASONS:
        # Asking to run something and having nothing run is a failed request,
        # not a clean run. Without this a typo'd selector or a missing file
        # reads as "everything passed".
        _reason = EXIT_CODE_REASONS[int(_exit)]
        _collect_error = ('{} (selector {!r})'.format(_reason, selector)
                          if selector else _reason)

    _result = RunResult(
        run_id=_run_id,
        selector=selector,
        env=env,
        duration=_duration,
        exit_code=int(_exit),
        cases=_collector.results(),
        collect_error=_collect_error)

    if persist:
        store.save(_result)
    return _result


def looks_like_path(selector: str) -> bool:
    """Whether a selector is meant as a file path rather than a -k expression."""
    _path_part = selector.split('::', 1)[0]
    return (os.sep in _path_part or '/' in _path_part
            or _path_part.endswith('.py') or os.path.exists(_path_part))


def _build_args(selector: str, extra_args: Sequence[str]) -> List[str]:
    _args = list(BASE_ARGS)
    if selector:
        # A path (optionally with ::nodeid) is passed through; anything else
        # is a -k expression.
        _args.append(selector) if looks_like_path(selector) \
            else _args.extend(['-k', selector])
    _args.extend(extra_args)
    return _args


def explain(run_id: str) -> Optional[dict]:
    """
    Full context for a past run: every failure with its traceback.

    Deliberately a separate call. Summaries stay small so they can be read;
    this is where the detail lives when someone actually wants it.
    """
    _result = store.load(run_id)
    if _result is None:
        return None
    return {
        'run_id': _result.run_id,
        'selector': _result.selector,
        'env': _result.env,
        'summary': _result.headline(),
        'collect_error': _result.collect_error,
        'failures': [
            {'case': _c.name, 'nodeid': _c.nodeid, 'outcome': _c.outcome,
             'duration': round(_c.duration, 3),
             'message': _c.message, 'detail': _c.detail}
            for _c in _result.failures],
    }

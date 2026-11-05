# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : api.py
@Time  : 2026-08-01
"""
import io
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from typing import List, Optional, Sequence

from ipandora.core.runner.collector import ResultCollector
from ipandora.core.runner.result import RunResult
from ipandora.core.runner import inventory, store
from ipandora.core.schedule import config as _config
from ipandora.core.schedule.runtime import Runtime
from ipandora.core.triage import hooks, triage
from ipandora.utils.log import logger

# Quiet, and no cache writes -- the caller gets structure from the collector,
# not from stdout.
#
# --import-mode=importlib matters for a library entry point. Under the default
# 'prepend' mode pytest keys imported test modules by basename in sys.modules,
# so a second in-process run over a different directory containing, say,
# another test_api.py aborts collection with "import file mismatch". Since
# run() is meant to be called repeatedly in one process (that is the whole
# point of not shelling out), the default mode is unusable here.
#
# enable_assertion_pass_hook makes pytest report every plain `assert` that
# held, which is how a suite written with bare asserts still gets a judgement
# inventory. See _bytecode_cache() for the catch.
BASE_ARGS = ('-q', '--no-header', '-p', 'no:cacheprovider', '--import-mode=importlib',
             '-o', 'enable_assertion_pass_hook=true')

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


def _apply_env(env: str):
    """
    Overlay this env's yaml onto Runtime.settings for one run.

    Returns (settings before, file loaded or ''). The caller restores the
    first when the run ends -- see run(). Without that restore the overlay
    stayed in place for the life of the process: in the MCP server, which
    calls run() repeatedly, a run with `env=staging` followed by `env=prod`
    (no prod.yaml) or `env=''` still ran with staging's settings.
    """
    _before = Runtime.settings
    _file = _config.find_env_file(env)
    if _file:
        Runtime.settings = _config.deep_merge(_before, _config.read_yaml(_file))
        # config values memoise on first read, so previously-read ones would
        # keep the old environment's value without this
        Runtime.reset()
    return _before, _file


def _forget_project_modules(before: set, rootdir: str) -> None:
    """
    Drop the modules this run imported from the project under test.

    Only files under pytest's rootdir, and never the framework, the standard
    library or anything installed: those are shared with the caller, and
    re-importing them would split class identities -- a Check from before and
    a Check from after would no longer be the same type.
    """
    if not rootdir:
        return
    import pytest
    import ipandora
    _root = os.path.abspath(rootdir) + os.sep
    _shared = [os.path.abspath(_p) + os.sep for _p in (
        os.path.dirname(ipandora.__file__), os.path.dirname(pytest.__file__),
        sys.prefix, sys.base_prefix)]
    for _name in set(sys.modules) - before:
        _file = getattr(sys.modules.get(_name), '__file__', None)
        if not _file:
            continue
        _path = os.path.abspath(_file)
        if not _path.startswith(_root) or 'site-packages' in _path \
                or any(_path.startswith(_s) for _s in _shared):
            continue
        sys.modules.pop(_name, None)


def _bytecode_cache() -> str:
    """
    Where rewritten test modules are cached during a run.

    The assertion-pass hook is compiled into the rewritten bytecode. pytest
    caches that bytecode in __pycache__ and reuses it without checking which
    options produced it, so a module first run by plain `pytest` keeps the
    hook-less version and its asserts silently go unrecorded -- every case
    would then read as unverified. Verified on pytest 9.2. A separate cache
    keeps the two from ever sharing a file.
    """
    _dir = os.environ.get('IPANDORA_PYCACHE_DIR') or os.path.join(
        os.path.dirname(store.runs_dir()), 'pycache')
    os.makedirs(_dir, exist_ok=True)
    return _dir


def run(selector: str = '', env: str = '', extra_args: Sequence[str] = (),
        persist: bool = True, quiet: bool = False, baseline: Optional[str] = None) -> RunResult:
    """
    Execute tests and return a structured result.

    This is the single execution entry point. The pytest CLI and the MCP
    `run_tests` tool both come through here rather than each growing their own
    logic -- and specifically, MCP does not shell out to pytest and scrape
    stdout, which loses structure and floods an agent's context.

    :param selector: what to run -- a path, a nodeid, or a `-k` expression.
                     Empty means the whole suite.
    :param env:      environment name; overlays <env>.yaml for this run only,
                     found as described in core/schedule/config.py.
    :param extra_args: extra pytest arguments.
    :param persist:  archive the full run so explain_failure can retrieve it.
    :param quiet:    swallow pytest's own stdout/stderr. Required when the
                     caller is speaking a protocol over stdout -- an MCP stdio
                     server would otherwise interleave pytest's progress dots
                     into its JSON-RPC stream and break the connection.
    :param baseline: judgement inventory to compare against (inventory.py).
                     None uses conf/judgements.json when it exists; '' turns
                     the comparison off. Comparing never changes `ok` -- a
                     weaker pass is reported in `judgement_changes`, and
                     gating on it is the caller's decision.

    Note: pytest runs in-process. The project modules a run imports -- test
    files, conftest.py, the suite's own helpers -- are dropped from
    sys.modules when it ends, so the next run imports them afresh. Without
    that, a long-lived caller kept executing the first version of every test
    file: an agent editing a test through the MCP server and re-running it
    got the old result back. See _forget_project_modules.
    """
    try:
        import pytest
    except ImportError as exc:
        raise RuntimeError('pytest is required to run tests: {}'.format(exc))

    _run_id = new_run_id()
    _settings_before, _env_file = _apply_env(env)
    _collector = ResultCollector()
    _args = _build_args(selector, extra_args)

    logger.info('run %s: pytest %s', _run_id, ' '.join(_args))
    _start = time.perf_counter()
    _sink = io.StringIO()
    _prefix_before = sys.pycache_prefix
    _nowrite_before = sys.dont_write_bytecode
    sys.pycache_prefix = _bytecode_cache()
    # Nothing a run compiles is written back. A .pyc is trusted when the
    # source's mtime (whole seconds) and size match, so a test edited within
    # the same second without changing length -- `== 1` to `== 2` -- kept
    # running its old bytecode. That is exactly what an agent fixing a test
    # through the MCP server does. Test modules are small; recompiling them
    # every run costs milliseconds, a stale verdict costs the whole loop.
    sys.dont_write_bytecode = True
    _modules_before = set(sys.modules)
    try:
        if quiet:
            with redirect_stdout(_sink), redirect_stderr(_sink):
                _exit = pytest.main(list(_args), plugins=[_collector])
        else:
            _exit = pytest.main(list(_args), plugins=[_collector])
    finally:
        sys.pycache_prefix = _prefix_before
        sys.dont_write_bytecode = _nowrite_before
        _forget_project_modules(_modules_before, _collector.rootdir)
        _duration = time.perf_counter() - _start
        if _env_file:
            Runtime.settings = _settings_before
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
        coverage=list(_collector.coverage),
        deselected=list(_collector.deselected),
        collect_error=_collect_error)

    _compare_with_baseline(_result, baseline)

    if persist:
        store.save(_result)
    return _result


def _compare_with_baseline(result: RunResult, baseline: Optional[str]) -> None:
    _path = inventory.default_path() if baseline is None else baseline
    if not _path:
        return
    try:
        _base = inventory.load(_path)
    except (OSError, ValueError) as exc:
        # an unreadable baseline must not pass for "nothing changed"
        logger.warning('judgement baseline %s unreadable: %s', _path, exc)
        result.baseline = _path
        result.judgement_changes = [inventory.Finding(
            inventory.CHANGED, '<baseline>', before=str(exc),
            note='基线文件无法读取').to_dict()]
        return
    if _base is None:
        if baseline:
            logger.warning('judgement baseline %s does not exist', _path)
        return
    result.baseline = _path
    result.judgement_changes = [_f.to_dict() for _f in inventory.compare(_base, result)]


def looks_like_path(selector: str) -> bool:
    """Whether a selector is meant as a file path rather than a -k expression."""
    _path_part = selector.split('::', 1)[0]
    return (os.sep in _path_part or '/' in _path_part
            or _path_part.endswith('.py') or os.path.exists(_path_part))


def _build_args(selector: str, extra_args: Sequence[str]) -> List[str]:
    _args = list(BASE_ARGS)
    # `extra_args=None` is the natural way for a caller to say "none", and it
    # used to raise from inside pytest argument assembly rather than here.
    extra_args = extra_args or ()
    if selector:
        # A path (optionally with ::nodeid) is passed through; anything else
        # is a -k expression.
        _args.append(selector) if looks_like_path(selector) \
            else _args.extend(['-k', selector])
    _args.extend(extra_args)
    return _args


def explain(run_id: str) -> Optional[dict]:
    """
    Full context for a past run: every failure with its traceback, plus
    triage.

    Deliberately a separate call. Summaries stay small so they can be read;
    this is where the detail lives when someone actually wants it.

    Triage classification is rule-based and always present. A natural-language
    root cause appears under `triage.analysis` only when LLM triage has been
    enabled -- see ipandora.ai.enable().
    """
    _result = store.load(run_id)
    if _result is None:
        return None

    _report = triage(_result)
    _report.analysis = hooks.analyze(_report, _result)

    return {
        'run_id': _result.run_id,
        'selector': _result.selector,
        'env': _result.env,
        'summary': _result.headline(),
        'collect_error': _result.collect_error,
        'triage': _report.to_dict(),
        'failures': [
            {'case': _c.name, 'nodeid': _c.nodeid, 'outcome': _c.outcome,
             'duration': round(_c.duration, 3),
             'message': _c.message, 'detail': _c.detail}
            for _c in _result.failures],
    }

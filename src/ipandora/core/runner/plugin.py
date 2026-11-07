# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : plugin.py
@Time  : 2026-11-05

The half of the runner that has to live where the tests run.

Loaded with `-p ipandora.core.runner.plugin`, which run() always passes. With
pytest-xdist each worker is a separate process, and `-p` is what xdist hands
on to every one of them -- a plugin *object* given to pytest.main(plugins=...)
exists only in the process that created it. That is how `-n 4` used to lose
every judgement: they were recorded in the workers, into a collector that was
not there, and all four cases came back unverified.

So everything that happens during a case is done here: judgements (the
assertion-pass hook, pytest.raises / warns), request evidence, the case's own
declarations (dims, flaky, title, whether it can be judged), and exclusive
resources. At the end of each case all of it is attached to the teardown
report as one `user_properties` entry, `ipandora.evidence`. Reports are what
xdist sends back to the main process, and `user_properties` travels with them.
The collector there (collector.py) reads only from reports.

Serial and parallel run the same code: serial is one process doing both
halves, not a second implementation.

This is deliberately not a `pytest11` entry point. Loaded automatically, it
would wrap pytest.raises for anyone who merely has the package installed and
runs plain `pytest` -- not ours to do.

PYTEST_DONT_REWRITE: pytest marks every -p module for assertion rewriting,
and warns in every run's output when the module was imported first -- which
this one always is, by the runner itself. It has no asserts to rewrite.
"""
import ast
import hashlib
import json
import logging
import os
import re
import sys
import time

import pytest

from ipandora.core.assertion.check import Check, Source
from ipandora.core.evidence import recorder

logger = logging.getLogger('ipandora.runner')

KEY = 'ipandora.evidence'
"""The user_properties entry a case's evidence travels in."""

DESELECTED_KEY = 'ipandora.deselected'
"""Worker output carrying the cases --exclude-flaky removed; xdist does not forward the hook."""

NARROWED_KEY = 'ipandora.narrowed'
"""Worker output: `-k` or `-m` left cases out of this run."""

EXCLUDE_FLAKY_OPTION = '--ipandora-exclude-flaky'
"""What run(exclude_flaky=True) passes. See pytest_collection_modifyitems."""

ENV_VAR = 'IPANDORA_RUN_ENV'
"""The run's environment name, for workers to overlay <env>.yaml themselves."""

PYCACHE_VAR = 'IPANDORA_RUN_PYCACHE'
"""Where a run's rewritten test bytecode goes; set by run(), see api._bytecode_cache."""

LOCK_DIR_VAR = 'IPANDORA_LOCK_DIR'
RESOURCE_TIMEOUT_VAR = 'IPANDORA_RESOURCE_TIMEOUT'
DEFAULT_RESOURCE_TIMEOUT = 300.0

RESOURCE_WAIT_MARKER = 'ipandora: gave up waiting for resource'
"""Start of the failure a lock timeout produces. triage keys on it."""

# Items whose checks are not `assert` statements: unittest's assertEqual and
# doctest's expected output. The runner cannot see their judgements, so it
# must not call them unverified.
OPAQUE_ITEMS = ('TestCaseFunction', 'DoctestItem', 'DoctestTextfile')

_INDEX = pytest.StashKey[int]()
_DECLARED = pytest.StashKey[dict]()
_LOCKS = pytest.StashKey[list]()
_EXCLUDED = pytest.StashKey[bool]()
_AUTH_DIR = pytest.StashKey[str]()
_STARTED = pytest.StashKey[float]()
_PATCHED = {}
_SESSIONS = {'depth': 0}
"""How many pytest sessions in this process have this plugin configured.

run() may be called from inside a test (this framework tests itself that way),
so sessions nest. The patches below belong to the outermost one: an inner
session that restored pytest.raises on its way out left the outer session's
remaining cases recording nothing."""


def is_worker(config) -> bool:
    return hasattr(config, 'workerinput')


# -- judgements pytest does not hand over by itself ------------------------

def _names(expected) -> str:
    if isinstance(expected, tuple):
        return ' | '.join(getattr(_e, '__name__', repr(_e)) for _e in expected)
    return getattr(expected, '__name__', repr(expected))


def _constant(source: str) -> bool:
    """
    Whether an assert's expression is a literal -- `assert True`, `assert 1`.

    Such an assert cannot fail, so it judges nothing. Recording it would let
    `assert True` turn an empty test into a "verified" one, which is precisely
    the shortcut the unverified status exists to expose.
    """
    try:
        ast.literal_eval(source.strip())
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False
    return True


def _record_judgement(claim: str, ok: bool = True, expr: str = '') -> None:
    recorder.add_checks([Check(name=claim, ok=ok, expr=expr or claim,
                               src=Source.ASSERT, claim=claim)])


class _Recording:
    """
    Wraps the context manager pytest.raises / pytest.warns returns, and
    records the judgement once it has held.

    Recorded on a clean exit only. When the expected exception never comes,
    pytest's own __exit__ raises and the case fails -- there is no passed
    judgement to record. When a different exception escapes, __exit__ returns
    False and nothing is recorded either.
    """

    def __init__(self, inner, claim: str):
        self._inner = inner
        self._claim = claim

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *exc):
        _handled = self._inner.__exit__(*exc)
        if _handled or exc[0] is None:
            _record_judgement(self._claim)
        return _handled

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _recording(original, verb: str):
    """
    A drop-in for pytest.raises / pytest.warns that records a judgement.

    `with pytest.raises(ValueError): f()` checks something real, but it is not
    an `assert` statement, so the assertion-pass hook never sees it. Without
    this, every test written that way would read as unverified.
    """
    def _wrapped(expected, *args, **kwargs):
        _claim = '{} {}'.format(verb, _names(expected))
        if kwargs.get('match'):
            _claim += ' match {!r}'.format(kwargs['match'])
        if args and callable(args[0]):
            # function form: pytest.raises(E, func, *args) -- returns only on success
            _info = original(expected, *args, **kwargs)
            _record_judgement(_claim)
            return _info
        return _Recording(original(expected, *args, **kwargs), _claim)
    _wrapped.__wrapped__ = original
    _wrapped.__doc__ = original.__doc__
    return _wrapped


# -- session ----------------------------------------------------------------

@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    """
    Put this process's test bytecode where run() put the main process's.

    For a worker, which is a new interpreter. Not via PYTHONPYCACHEPREFIX:
    that redirects every import from the first one, so each worker recompiled
    pytest, requests and the rest of the standard library from source on every
    run -- measured, it cost more than four workers saved. This runs after
    those are loaded and before the first conftest or test module is, which
    is the same point run() sets it in the main process.

    Not set by plain `pytest`, so outside run() nothing changes.
    """
    _prefix = os.environ.get(PYCACHE_VAR)
    if _prefix:
        sys.pycache_prefix = _prefix
        sys.dont_write_bytecode = True


def pytest_addoption(parser):
    parser.addoption(
        EXCLUDE_FLAKY_OPTION, action='store_true', default=False,
        help='ipandora: deselect cases marked flaky and report them as excluded')


def pytest_configure(config):
    _SESSIONS['depth'] += 1
    _make_auth_dir(config)
    _clean_faults(config, 'start')
    # Patched for the duration of the run, restored in pytest_unconfigure.
    # A module that did `from pytest import raises` during this run keeps the
    # wrapper afterwards, which is harmless: outside a case it records nothing
    # and behaves exactly like the original.
    if not _PATCHED:
        _PATCHED.update({'raises': pytest.raises, 'warns': pytest.warns})
        pytest.raises = _recording(_PATCHED['raises'], 'raises')
        pytest.warns = _recording(_PATCHED['warns'], 'warns')
    config.addinivalue_line(
        'markers',
        'dims(**axes): place this case in the coverage matrix, '
        'e.g. @pytest.mark.dims(role="admin", channel="web")')
    config.addinivalue_line(
        'markers',
        'flaky(reason): this case is known-unstable. The reason is '
        'required -- a bare marker is how a failure gets parked forever. '
        'Run with --exclude-flaky to keep these out of a gate.')
    config.addinivalue_line(
        'markers',
        'resource(*names): this case needs exclusive use of a shared resource '
        '(a test account, a fixed order number). Cases naming the same '
        'resource never run at the same time, across workers and across '
        'concurrent runs on one machine.')
    if is_worker(config):
        _apply_worker_env()
    # Playwright, when installed: expect() as judgements, locators remembered
    # by what they point at. See core/web.py.
    from ipandora.core import web
    if web.install() and config.pluginmanager.hasplugin('playwright'):
        config.pluginmanager.register(web.ContextDefaults(), 'ipandora-web-context')
    # uiautomator2, when installed: the `device` fixture, and every selector
    # that finds nothing looked for by name in the widget tree. See core/android.py.
    from ipandora.core import android
    if android.install() and config.pluginmanager.get_plugin('ipandora-android') is None:
        config.pluginmanager.register(android.Fixtures(), 'ipandora-android')


def _apply_worker_env():
    """
    Overlay the run's <env>.yaml in this worker.

    The main process overlays it in run(), but that is a change to its own
    memory; a worker is a new process that starts from the defaults. Without
    this, `ipandora run -e staging --workers 4` ran every case against the
    default config while the report said staging.
    """
    _env = os.environ.get(ENV_VAR, '')
    if not _env:
        return
    from ipandora.core.schedule import config as _config
    from ipandora.core.schedule.runtime import Runtime
    _file = _config.find_env_file(_env)
    if _file:
        Runtime.settings = _config.deep_merge(Runtime.settings, _config.read_yaml(_file))
        Runtime.reset()
    Runtime.Option.env = _env


def _make_auth_dir(config):
    """
    The private directory where xdist workers share a single-session login
    (core/auth.py): made by the process that starts the workers, which
    inherit it through the environment. Here rather than in run(), so plain
    `pytest -n 4` gets it too. 0700 from mkdtemp; removed when the run ends.
    """
    from ipandora.core import auth
    if is_worker(config) or os.environ.get(auth.AUTH_DIR_VAR):
        return
    import tempfile
    _dir = tempfile.mkdtemp(prefix='ipandora-auth-')
    os.environ[auth.AUTH_DIR_VAR] = _dir
    config.stash[_AUTH_DIR] = _dir


def _remove_auth_dir(config):
    _dir = config.stash.get(_AUTH_DIR, None)
    if not _dir:
        return
    import shutil
    from ipandora.core import auth
    shutil.rmtree(_dir, ignore_errors=True)
    if os.environ.get(auth.AUTH_DIR_VAR) == _dir:
        os.environ.pop(auth.AUTH_DIR_VAR, None)


def _clean_faults(config, when: str) -> None:
    """
    Remove injected faults left on the environment's backends (Toxiproxy by
    default, `faults.backends`): at the start, what a killed run left behind;
    at the end, anything this run did not undo. Only where injection is
    allowed, and only in the process that starts the workers. Each backend on
    its own: one that cannot be reached does not keep the others dirty.
    """
    # Only the outermost session: a run started inside a case -- run() called
    # from a test -- would otherwise remove the faults that case is injecting
    # at this moment. And never while a fault is in effect in this process.
    if is_worker(config) or _SESSIONS['depth'] != 1:
        return
    from ipandora.core import faults
    if faults.active():
        return
    try:
        if not faults.allowed():
            return
        _names = faults.configured()
    except (OSError, ValueError) as exc:
        logger.info('ipandora: fault cleanup at {} skipped: {}'.format(when, exc))
        return
    for _name in _names:
        try:
            _backend = faults.Toxiproxy(timeout=2.0) if _name == 'toxiproxy' else faults.backend(_name)
            _removed = _backend.clean()
        except (faults.BackendError, OSError, ValueError) as exc:
            logger.info('ipandora: fault cleanup on {} at {} skipped: {}'.format(_name, when, exc))
            continue
        if _removed:
            logger.warning('ipandora: removed {} injected fault(s) left on {} at {}: {}'.format(
                len(_removed), _name, when, ', '.join(_removed[:5])))


def pytest_unconfigure(config):
    _clean_faults(config, 'end')
    _remove_auth_dir(config)
    _SESSIONS['depth'] = max(_SESSIONS['depth'] - 1, 0)
    if _SESSIONS['depth']:
        return      # an outer session is still running and still needs them
    from ipandora.core import android, auth, web
    web.uninstall()
    android.uninstall()
    # credentials and identity sessions are this run's (core/auth.py); the
    # MCP server lives across runs and must not carry a token over
    auth.reset()
    for _name, _original in _PATCHED.items():
        setattr(pytest, _name, _original)
    _PATCHED.clear()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """
    --exclude-flaky, done here rather than as `-m 'not flaky'`.

    Two reasons. pytest keeps only the last `-m`, so appending one silently
    replaced whatever marker expression the user passed. And pytest_deselected
    cannot tell a flaky exclusion from a `-k` selector or the user's own `-m`:
    every case outside `ipandora run login` was recorded as excluded, compared
    with a full-suite baseline as "used to pass, now excluded", and failed
    --fail-on-weakened for cases nobody touched. Only what is removed here is
    an exclusion; what a selector leaves out is simply outside the run.

    trylast: after `-k` and `-m` have narrowed the list, so only the flaky
    cases that would otherwise have run are named.
    """
    if not config.getoption(EXCLUDE_FLAKY_OPTION.lstrip('-').replace('-', '_'), False):
        return
    _keep, _drop = [], []
    for _item in items:
        (_drop if _item.get_closest_marker('flaky') is not None else _keep).append(_item)
    if not _drop:
        return
    for _item in _drop:
        _item.stash[_EXCLUDED] = True
    items[:] = _keep
    config.hook.pytest_deselected(items=_drop)


def excluded(item) -> bool:
    """Whether --exclude-flaky removed this item (as opposed to a selector)."""
    _stash = getattr(item, 'stash', None)
    return bool(_stash is not None and _stash.get(_EXCLUDED, False))


def pytest_collection_finish(session):
    # The position in collection order. Every worker collects the same list,
    # so this is what puts parallel results back in a stable order: arrival
    # order depends on which worker finished first.
    for _index, _item in enumerate(session.items):
        _item.stash[_INDEX] = _index


def pytest_deselected(items):
    # Recorded here only for workers; in a serial run the collector sees the
    # hook itself. See collector.py for the other half.
    _config = items[0].config if items else None
    if _config is not None and is_worker(_config):
        _config.workeroutput.setdefault(DESELECTED_KEY, []).extend(
            _i.nodeid for _i in items if excluded(_i))
        if any(not excluded(_i) for _i in items):
            _config.workeroutput[NARROWED_KEY] = True


# -- per case ---------------------------------------------------------------

def pytest_assertion_pass(item, lineno, orig, expl):
    """
    A plain `assert` that held.

    pytest only calls this with enable_assertion_pass_hook, which run() sets.
    `orig` is the source text -- `r['fee'] <= 100` -- and is what the
    inventory compares; `expl` carries the values it saw.
    """
    if _constant(orig):
        return
    _expr = (expl or '').splitlines()[0] if expl else orig
    _record_judgement('assert {}'.format(orig), ok=True, expr=_expr)


def pytest_runtest_makereport(item, call):
    """
    A plain `assert` that failed. The pass hook only sees successes, so
    without this a case failing on a bare assert would show no failed
    judgement at all. assert_all records its own failures first, so a case
    that already has one is left alone.
    """
    _excinfo = getattr(call, 'excinfo', None)
    if call.when in ('setup', 'call') and _excinfo is not None \
            and not _excinfo.errisinstance(pytest.skip.Exception):
        _keep_service_logs(item)
        _keep_device_evidence(item, _excinfo)
    if call.when != 'call' or _excinfo is None \
            or not _excinfo.errisinstance(AssertionError):
        return None
    if any(not _c.get('ok') for _c in recorder.current_checks()):
        return None
    _lines = [_l for _l in str(_excinfo.value).splitlines() if _l.strip()]
    _expr = ' / '.join(_lines[:2]) or 'AssertionError'
    _record_judgement('assert (failed)', ok=False, expr=_expr)
    return None


def _keep_service_logs(item) -> None:
    """
    A case failed while services of a compose stack were up (core/stack.py):
    keep what each of them logged since the case began. Their side of the
    story is usually where a 500 is explained.
    """
    from ipandora.core import stack
    if not stack.active():
        return
    try:
        stack.keep_logs(item.nodeid, item.stash.get(_STARTED, time.time()))
    except Exception as exc:  # noqa: BLE001 -- evidence must never break the run
        # inside pytest_runtest_makereport: an exception here is an INTERNALERROR
        # that ends the whole session, not one case's missing logs
        logger.warning('could not keep the service logs of %s: %s', item.nodeid, exc)


def _keep_device_evidence(item, excinfo=None) -> None:
    """
    A case failed on an Android device (core/android.py): its screen, widget
    tree and log now, before the fixture stops the app -- and whether the app
    crashed, which decides the verdict. A failed assert hands over its text
    and statement: an assert on a lookup that came back empty is diagnosed.
    """
    from ipandora.core import android
    if not android.active():
        return
    _failure = ''
    if excinfo is not None and excinfo.errisinstance(AssertionError):
        try:
            _failure = '{}\n{}'.format(excinfo.value, excinfo.traceback[-1].statement)
        except Exception:  # noqa: BLE001 -- no statement: the message alone
            _failure = str(excinfo.value)
    try:
        android.keep_evidence(item.nodeid, _failure)
    except Exception as exc:  # noqa: BLE001 -- evidence must never break the run
        logger.warning('could not keep the device evidence of %s: %s', item.nodeid, exc)


def pytest_runtest_setup(item):
    """
    Open an evidence slot and take the case's resources before its fixtures
    run.

    Setup, not call: fixtures make requests too, and a fixture that fails is
    exactly when someone wants to see what it asked for. And a fixture that
    logs in with the shared account is already using it.
    """
    _params = getattr(getattr(item, 'callspec', None), 'params', {}) or {}
    item.stash[_STARTED] = time.time()
    recorder.begin(item.nodeid, path=getattr(item, 'path', ''),
                   browser=_params.get('browser_name', ''))
    item.stash[_DECLARED] = _declarations(item)
    _acquire_resources(item)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    """
    Pack up after fixture teardown, before the teardown report is made.

    A wrapper so this runs once the fixtures are torn down -- their requests
    belong to the case, and a resource is not free until the fixture that
    used it has let go -- yet still before pytest builds the teardown report,
    which copies item.user_properties.
    """
    try:
        yield
    finally:
        _release_resources(item)
        _payload = _pack(item)
        if _payload is not None:
            item.user_properties.append((KEY, _payload))


def _merged_dims(item) -> dict:
    """
    Every dims marker of the item, merged: module and class first, then the
    function, then the parameter row -- the most specific wins a conflict.

    Not the closest marker alone: pytest lists a function's marks before a
    parameter's, so with `@pytest.mark.dims(channel='api')` on the function
    every row of cases(...) lost its own dims, and the coverage matrix never
    saw them.
    """
    _merged = {}
    for _m in reversed(list(item.iter_markers('dims'))):
        _merged.update(_m.kwargs or {})
    for _m in getattr(getattr(item, 'callspec', None), 'marks', None) or ():
        if getattr(_m, 'name', '') == 'dims':
            _merged.update(_m.kwargs or {})
    return {str(_k): str(_v) for _k, _v in _merged.items()}


def _declarations(item) -> dict:
    """
    What a test declares about itself: where it sits in the coverage matrix,
    whether it is known-unstable, and what it is for.
    """
    _out = {'judgeable': type(item).__name__ not in OPAQUE_ITEMS}

    _dims = _merged_dims(item)
    if _dims:
        _out['dims'] = _dims

    _flaky = item.get_closest_marker('flaky')
    if _flaky is not None:
        # A reason is the whole value of the marker. Without one this is just
        # a quieter way of ignoring a failing test.
        _out['flaky'] = str((_flaky.kwargs or {}).get('reason')
                            or (_flaky.args[0] if _flaky.args else '')
                            or '未说明原因')

    _function = getattr(item, 'function', None)
    _doc = _function.__doc__ if _function is not None else None
    if _doc:
        _out['title'] = _doc.strip().splitlines()[0].strip()

    # Axes are declared once per module, not per test: the whole point of the
    # matrix is the cells with no test in them, and a run can only know those
    # if the full value set is stated independently of what ran. Sent with
    # every case and de-duplicated by the collector, because in a parallel run
    # no single worker sees every module.
    _module = getattr(item, 'module', None)
    _axes = getattr(_module, 'COVERAGE', None)
    if _axes:
        _out['coverage'] = {'module': getattr(_module, '__name__', ''), 'axes': list(_axes)}
    return _out


def _pack(item):
    _evidence = recorder.end(item.nodeid)
    # A case skipped by its marker never reaches our setup hook: pytest's
    # skipping plugin raises first. Its declarations and its position still
    # matter -- without the index it sorted by arrival, so the case order (and
    # the judgement inventory) differed between a serial and a parallel run.
    _declared = item.stash.get(_DECLARED, None)
    if _declared is None:
        _declared = _declarations(item)
    _payload = dict(_declared)
    if _evidence is not None:
        _payload['checks'] = list(_evidence.checks)
        _payload['exchanges'] = list(_evidence.exchanges)
        if _evidence.locators:
            _payload['locators'] = dict(_evidence.locators)
        if _evidence.locator_failures:
            _payload['locator_failures'] = list(_evidence.locator_failures)
        if _evidence.faults:
            _payload['faults'] = [dict(_f) for _f in _evidence.faults]
        if _evidence.app_events:
            _payload['app_events'] = [dict(_e) for _e in _evidence.app_events]
        if _evidence.artifacts:
            _payload['artifacts'] = list(_evidence.artifacts)
        if _evidence.trace_shown and _evidence.trace_id:
            _payload['trace_id'] = _evidence.trace_id
    if _INDEX in item.stash:
        _payload['index'] = item.stash[_INDEX]
    # Reports cross a process boundary under xdist, and execnet carries only
    # plain types. A response body is whatever the test handed over; one
    # object it cannot serialise would take the worker's whole report with
    # it. The same normalisation runs serially, so both modes produce the
    # same data.
    return json.loads(json.dumps(_payload, default=str))


# -- exclusive resources ----------------------------------------------------

def lock_dir() -> str:
    """
    One directory per user on this machine, whatever else is configured.

    It used to sit next to the run store, so two runs with different
    IPANDORA_RUNS_DIR -- two CI jobs, the MCP server and a terminal -- each
    took "their own" lock on the same test account and ran at the same time.
    """
    _dir = os.environ.get(LOCK_DIR_VAR)
    if not _dir:
        import getpass
        import tempfile
        try:
            _user = getpass.getuser()
        except Exception:  # noqa: BLE001 -- no login name: fall back to one shared directory
            _user = 'user'
        _dir = os.path.join(tempfile.gettempdir(),
                            'ipandora-locks-' + re.sub(r'[^A-Za-z0-9._-]+', '_', _user))
    os.makedirs(_dir, mode=0o700, exist_ok=True)
    return _dir


def lock_path(name: str) -> str:
    # Resource names are free text ('account:vip', 'order 42'); a filename is
    # not. Readable prefix for whoever looks in the directory, hash for
    # uniqueness.
    _safe = re.sub(r'[^A-Za-z0-9._-]+', '_', name)[:40]
    _digest = hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]
    return os.path.join(lock_dir(), '{}-{}.lock'.format(_safe, _digest))


def _resource_names(item):
    return sorted({str(_a) for _m in item.iter_markers('resource') for _a in _m.args})


class ResourceLock:
    """
    An exclusive lock on one file, held across processes on one machine.

    The standard library, not filelock: all this needs is a blocking lock with
    a timeout, and filelock shipped 26 releases in seven weeks and dropped
    Python 3.10 halfway through its 4.x line. A fast-moving dependency for a
    dozen lines is a poor trade (docs/design/decisions/15 §3, necessity).

    flock on POSIX; msvcrt.locking on Windows, which CI does not run. The lock
    belongs to the open file, so a process that dies releases it -- a crashed
    worker cannot leave a resource taken.
    """

    POLL = 0.05

    def __init__(self, path: str):
        self.path = path
        self._fd = None

    def acquire(self, timeout: float) -> bool:
        import time
        _deadline = time.monotonic() + max(timeout, 0)
        _fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        while True:
            if self._try(_fd):
                self._fd = _fd
                return True
            if time.monotonic() >= _deadline:
                os.close(_fd)
                return False
            time.sleep(self.POLL)

    @staticmethod
    def _try(fd) -> bool:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _acquire_resources(item):
    """
    Take every resource the case names, in sorted order -- two cases naming
    the same pair in different orders would otherwise deadlock.

    Serial runs lock too: two runs on one machine -- two CI jobs, a developer
    and the MCP server -- share accounts as readily as two workers do.
    """
    _names = _resource_names(item)
    if not _names:
        return
    _timeout = float(os.environ.get(RESOURCE_TIMEOUT_VAR) or DEFAULT_RESOURCE_TIMEOUT)
    _held = []
    item.stash[_LOCKS] = _held
    for _name in _names:
        _lock = ResourceLock(lock_path(_name))
        if not _lock.acquire(_timeout):
            _release_resources(item)
            pytest.fail('{} {!r} after {:g}s: another case or another run on this '
                        'machine still holds it'.format(RESOURCE_WAIT_MARKER, _name, _timeout),
                        pytrace=False)
        _held.append(_lock)


def _release_resources(item):
    for _lock in reversed(item.stash.get(_LOCKS, [])):
        try:
            _lock.release()
        # bandit B110: a lock that will not release must not turn a result red; the process exit frees it
        except Exception:  # noqa: BLE001  # nosec B110
            pass
    item.stash[_LOCKS] = []

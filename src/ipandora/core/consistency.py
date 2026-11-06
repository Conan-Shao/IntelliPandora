# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : consistency.py
@Time  : 2026-11-06

Consistency checks on an operation history (docs/design/decisions/18, D3a):
record what each concurrent operation asked for and what came back, then let
an established checker decide whether some sequential order explains it all.

    from ipandora.core import consistency
    from ipandora.core.concurrency import concurrently

    history = consistency.History()

    def add():
        return history.call('add', 1, lambda: CounterApi().incr(), ok=lambda r: r.status_code == 200)

    def read():
        return history.call('read', None, lambda: CounterApi().get(),
                            ok=lambda r: r.status_code == 200, value=lambda r: r.json()['n'])

    concurrently([add] * 10)
    read()
    assert_all(history.check('counter'))

No algorithm of our own (decision 14, "integrate, not reimplement"): the
checker is elle-cli -- Knossos for linearizability (cas-register, mutex),
Elle for transactional anomalies (rw-register, list-append), Jepsen's
checkers for counter, set, bank. It is a Java tool, run as a child process on
a history this module writes in EDN. Admitted under decision 15: one version,
its SHA-256 pinned below, verified before every run (see
docs/security/components.md).

Outcomes, as the checker gives them:
- valid      -> a passing Check;
- invalid    -> a failing Check, with the checker's counterexample;
- unknown    -> no verdict (the checker ran out of time or memory): a gap,
                which never passes a case on its own;
- no Java 21 or no checker -> the case is skipped, saying why.

Each operation is an invoke and a completion. A completion is `ok` (it took
effect), `fail` (it certainly did not) or `info` (unknown: a timeout, a
dropped connection -- it may or may not have happened). The case says which
through `ok=` / `fail=`; an exception is `info`. After an `info` the thread
continues as a new process, as Jepsen requires: the old one may still be
in flight.
"""
import hashlib
import json
import os
import re
import shutil
# bandit B404: the checker is a Java tool run as a child process, never through a shell
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from ipandora.core.assertion.check import Check, brief, gap

CONSISTENCY = 'consistency'
"""Check.src of the judgements this module makes."""

ELLE_CLI_VERSION = '0.1.11'
ELLE_CLI_SHA256 = '85c39a6247509075bf21762d4c8ed3a2cb3d2c9b2c169cb2c80dde25fa760388'
"""SHA-256 of elle-cli-0.1.11-standalone.jar, from elle-cli-bin-0.1.11.zip on the project's GitHub release."""
ELLE_CLI_URL = 'https://github.com/ligurio/elle-cli/releases/download/0.1.11/elle-cli-bin-0.1.11.zip'
JAVA_MIN = 21

MODELS = ('cas-register', 'mutex', 'rw-register', 'list-append', 'counter', 'set', 'set-full', 'bank',
          'long-fork')


_KEYWORD = re.compile(r'^[A-Za-z*+!_?<>=][A-Za-z0-9*+!_?<>=.\-]*$')


class K(str):
    """
    An EDN keyword: K('append') is written `:append`. Only names EDN can read
    back: `add one` would be `:add one`, which the checker parsed as two
    things and died on.
    """

    def __new__(cls, name):
        if not _KEYWORD.match(str(name)):
            raise ValueError('{!r} cannot be an EDN keyword: letters, digits and - _ . * + ! ? < > = only, '
                             'starting with a letter'.format(name))
        return super().__new__(cls, name)


def append(key, value) -> list:
    """A list-append micro-op."""
    return [K('append'), key, value]


def read(key, value=None) -> list:
    """A read micro-op (list-append, rw-register); the value is filled in on completion."""
    return [K('r'), key, value]


def write(key, value) -> list:
    """An rw-register write micro-op."""
    return [K('w'), key, value]


def edn(value) -> str:
    """`value` as EDN: dicts with keyword keys, lists as vectors, K as keywords, None as nil."""
    if value is None:
        return 'nil'
    if isinstance(value, K):
        return ':' + str(value)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        # the checkers do arithmetic on values; a NaN in a history crashed them
        raise ValueError('a history value must be a finite number, not {}'.format(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return '{' + ', '.join('{} {}'.format(edn(_k if isinstance(_k, K) else K(str(_k))), edn(_v))
                               for _k, _v in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ' '.join(edn(_v) for _v in value) + ']'
    raise TypeError('cannot write {!r} as EDN'.format(type(value).__name__))


class History:
    """
    The operations of a test, in the order they happened: invokes and their
    completions, with the process (thread) that made them and when.
    """

    def __init__(self):
        self.ops: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        """The checker's full answer after check()."""
        self._lock = threading.Lock()
        self._start = time.monotonic_ns()
        self._processes: Dict[int, int] = {}
        self._next = 0

    def _process(self, renew: bool = False) -> int:
        _thread = threading.get_ident()
        with self._lock:
            if renew or _thread not in self._processes:
                self._processes[_thread] = self._next
                self._next += 1
            return self._processes[_thread]

    def _add(self, op: Dict[str, Any]) -> None:
        with self._lock:
            op['time'] = time.monotonic_ns() - self._start
            self.ops.append(op)

    def call(self, f: str, value: Any, operation: Callable[[], Any], ok: Optional[Callable[[Any], bool]] = None,
             fail: Optional[Callable[[Any], bool]] = None, result: Optional[Callable[[Any], Any]] = None) -> Any:
        """
        Run `operation` and record it as `f` with `value`.

        :param ok:     the operation took effect (default: it returned).
        :param fail:   it certainly did not -- a 409, a validation error.
        :param result: the value it completed with -- what a read read.
        Returns what `operation` returned; re-raises what it raised, after
        recording the operation as `info`.
        """
        _f = K(f)
        edn(value)                    # refuse a value the history could not be written with, before running
        _process = self._process()
        self._add({'process': _process, 'type': K('invoke'), 'f': _f, 'value': value})
        try:
            _r = operation()
        except BaseException as exc:
            # BaseException too: pytest.skip() / fail() and KeyboardInterrupt are
            # not Exceptions. Without a completion the process kept an open
            # invoke, its next operation opened a second one, and the checker
            # crashed on the history instead of judging it.
            self._add({'process': _process, 'type': K('info'), 'f': _f, 'value': value,
                       'error': '{}: {}'.format(type(exc).__name__, exc)[:200]})
            self._process(renew=True)
            raise
        if fail is not None and fail(_r):
            self._add({'process': _process, 'type': K('fail'), 'f': _f, 'value': value})
        elif ok is None or ok(_r):
            self._add({'process': _process, 'type': K('ok'), 'f': _f,
                       'value': result(_r) if result is not None else value})
        else:
            # neither confirmed nor refused: it may have happened
            self._add({'process': _process, 'type': K('info'), 'f': _f, 'value': value})
            self._process(renew=True)
        return _r

    def to_edn(self) -> str:
        with self._lock:
            return '\n'.join(edn(_op) for _op in self.ops) + '\n'

    def save(self, path: str) -> str:
        with open(path, 'w', encoding='utf-8') as _f:
            _f.write(self.to_edn())
        return path

    def check(self, model: str, consistency_models: Sequence[str] = (), anomalies: Sequence[str] = (),
              timeout: float = 300) -> Check:
        """
        The checker's verdict on this history under `model` (MODELS). For
        rw-register and list-append, `consistency_models` (serializable,
        snapshot-isolation, ...) and `anomalies` (G0, G1c, ...) say what to
        look for.
        """
        if model not in MODELS:
            raise ValueError('unknown model {!r}; one of {}'.format(model, ', '.join(MODELS)))
        _name = '历史符合 {} 模型'.format(model) + ('（{}）'.format('、'.join(consistency_models))
                                               if consistency_models else '')
        _claim = 'history consistent under {}{}'.format(model, ' ' + ','.join(consistency_models)
                                                        if consistency_models else '')
        if not self.ops:
            return Check(name=_name, ok=False, expr='历史是空的：没有记录任何操作', src=CONSISTENCY, claim=_claim)
        _java, _jar = checker()
        _work = tempfile.mkdtemp(prefix='ipandora-history-')
        try:
            _file = self.save(os.path.join(_work, 'history.edn'))
            _cmd = [_java, '-jar', _jar, '--model', model, '--output', 'json']
            for _c in consistency_models:
                _cmd += ['--consistency-models', _c]
            for _a in anomalies:
                _cmd += ['--anomalies', _a]
            try:
                # bandit B603: the verified checker jar, our own arguments and file; no shell
                _done = subprocess.run(_cmd + [_file], capture_output=True, text=True,  # nosec B603
                                       timeout=timeout, cwd=_work)
            except subprocess.TimeoutExpired:
                return gap(_name, '检查器 {:g} 秒内没有给出结论，无法判定'.format(timeout), src=CONSISTENCY)
        finally:
            shutil.rmtree(_work, ignore_errors=True)
        self.result = _parse(_done.stdout)
        if self.result is None:
            raise RuntimeError('elle-cli gave no result (exit {}): {}'.format(
                _done.returncode, (_done.stderr or _done.stdout).strip()[-500:]))
        _valid = self.result.get('valid?')
        if _valid is True:
            return Check(name=_name, ok=True, expr='{} 个操作，检查器判定一致'.format(self._operations()),
                         src=CONSISTENCY, claim=_claim)
        if _valid is False:
            return Check(name=_name, ok=False, expr=counterexample(self.result), src=CONSISTENCY, claim=_claim)
        return gap(_name, '检查器无法判定（{}）'.format(_valid), src=CONSISTENCY)

    def _operations(self) -> int:
        return sum(1 for _op in self.ops if _op['type'] == 'invoke')


def _parse(stdout: str) -> Optional[Dict[str, Any]]:
    _start = (stdout or '').find('{')
    if _start < 0:
        return None
    try:
        return json.loads(stdout[_start:])
    except ValueError:
        return None


def counterexample(result: Dict[str, Any], limit: int = 400) -> str:
    """What the checker found, in a sentence: the anomalies, or the operation no order can explain."""
    if result.get('anomaly-types'):
        _text = '异常：{}'.format('、'.join(map(str, result['anomaly-types'])))
        if result.get('not'):
            _text += '；不满足 {}'.format('、'.join(map(str, result['not'])))
        return _text[:limit]
    _paths = result.get('final-paths') or []
    if _paths and _paths[0]:
        _last = _paths[0][-1]
        _op = _last.get('op') or {}
        return '没有任何顺序能解释这个操作：进程 {} 的 {} {}（{}）'.format(
            _op.get('process'), _op.get('f'), brief(_op.get('value'), 80),
            (_last.get('model') or {}).get('msg', ''))[:limit]
    _errors = result.get('errors') or []
    if _errors and all(isinstance(_e, list) and len(_e) == 3 for _e in _errors):
        # Jepsen's counter: [lowest possible, value read, highest possible]
        return '；'.join('读到 {}，按已确认的操作应在 {} 到 {} 之间'.format(_e[1], _e[0], _e[2])
                        for _e in _errors[:3])[:limit]
    if _errors:
        return '不一致的读：{}'.format(brief(_errors, limit - 10))
    if result.get('lost') or result.get('unexpected'):
        return '丢失 {}，多出 {}'.format(brief(result.get('lost'), 120), brief(result.get('unexpected'), 120))[:limit]
    return '检查器判定不一致：{}'.format(brief(result, limit - 12))


# -- the checker ---------------------------------------------------------------------------------

def _java_version(java: str) -> int:
    try:
        # bandit B603: a java executable we located, asking its version; no shell
        _done = subprocess.run([java, '-version'], capture_output=True, text=True, timeout=30)  # nosec B603
    except (OSError, subprocess.TimeoutExpired):
        return 0
    _m = re.search(r'version "(\d+)', _done.stderr + _done.stdout)
    return int(_m.group(1)) if _m else 0


def _settings() -> Dict[str, Any]:
    from ipandora.common.dictutils import DictUtils
    from ipandora.core.schedule.runtime import Runtime
    return DictUtils.safe_get(Runtime.settings, 'consistency') or {}


_VERIFIED = {}


def checker():
    """
    (java, jar) to run, or skip the case saying what is missing. The jar is
    elle-cli at ELLE_CLI_SHA256 -- another build runs only when the project
    pins its hash in `consistency.elle_cli_sha256`, i.e. admitted it itself.
    """
    from ipandora.core.assertion import require
    _s = _settings()
    _jar = _s.get('elle_cli') or os.environ.get('ELLE_CLI_JAR') or ''
    _candidates = [_s.get('java'), os.environ.get('IPANDORA_JAVA'),
                   os.path.join(os.environ['JAVA_HOME_21_X64'], 'bin', 'java')
                   if os.environ.get('JAVA_HOME_21_X64') else None,
                   os.path.join(os.environ['JAVA_HOME'], 'bin', 'java') if os.environ.get('JAVA_HOME') else None,
                   shutil.which('java')]
    _java = next((_j for _j in _candidates if _j and os.path.isfile(_j) and _java_version(_j) >= JAVA_MIN), None)
    require(Check(name='有 Java {}+'.format(JAVA_MIN), ok=bool(_java),
                  expr='一致性检查器（elle-cli）需要 Java {} 或更新的版本；没有找到。设置 IPANDORA_JAVA 或 '
                       'consistency.java'.format(JAVA_MIN)),
            Check(name='有一致性检查器 elle-cli', ok=bool(_jar) and os.path.isfile(_jar),
                  expr='设置 ELLE_CLI_JAR 或 consistency.elle_cli 指向 elle-cli-{}-standalone.jar（{}）'.format(
                      ELLE_CLI_VERSION, ELLE_CLI_URL)))
    _expected = (_s.get('elle_cli_sha256') or ELLE_CLI_SHA256).lower()
    # keyed by what the file is now, not only its path: a jar swapped after
    # the first check of the process must be checked again
    _stat = os.stat(_jar)
    _key = (_jar, _stat.st_size, _stat.st_mtime_ns)
    if _VERIFIED.get(_key) != _expected:
        with open(_jar, 'rb') as _f:
            _actual = hashlib.sha256(_f.read()).hexdigest()
        if _actual != _expected:
            raise RuntimeError('{} has SHA-256 {}, not the admitted {}: refusing to run it. A different build '
                               'needs its own admission and `consistency.elle_cli_sha256`'.format(
                                   _jar, _actual, _expected))
        _VERIFIED[_key] = _expected
    return _java, _jar


__all__ = ['History', 'K', 'append', 'read', 'write', 'edn', 'counterexample', 'checker', 'MODELS',
           'ELLE_CLI_VERSION', 'ELLE_CLI_SHA256', 'ELLE_CLI_URL', 'CONSISTENCY']

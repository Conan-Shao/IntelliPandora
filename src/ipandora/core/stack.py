# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : stack.py
@Time  : 2026-11-06

The services a case needs, from the project's own compose file
(docs/design/decisions/19, D5): started and waited for, always taken down,
their logs kept when a case fails.

    from ipandora.core import stack

    @pytest.fixture(scope='session')
    def shop():
        with stack.compose('compose.yaml', wait=120) as s:
            yield s

    def test_order(shop):
        base = shop.url('api', 8080)          # http://127.0.0.1:<the port Docker picked>

Integrate, not wrap: Docker Compose (v2.20+) does the work -- `up --wait`
waits on the services' own health checks, `port` reads the published port,
`logs --since` the logs, `down -v` removes everything. Compose is a system
tool like git; the framework neither installs nor pins it.

- A compose file publishes container ports only ("8080"), so parallel runs
  never collide; Stack.port() finds where each one landed.
- Each process has its own project, `ipandora-<host>-<pid>-<name>`: xdist
  workers each start their own stack. Projects of processes that died
  without taking theirs down are removed the next time a stack starts here.
- A stack that does not come up raises StackError, which triage calls an
  environment problem, with the failing services' last log lines.
- Without Docker the case is skipped, saying why.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import socket
# bandit B404: Docker Compose is run as a child process, never through a shell
import subprocess  # nosec B404
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

_log = logging.getLogger(__name__)

PREFIX = 'ipandora-'
COMPOSE_MIN = (2, 20)
STACK_MARKER = 'ipandora: environment did not start'
"""In StackError's message; core/triage/rules.py calls such a failure the environment's."""
LOG_LINES = 80
"""Lines of each service's log kept with a failed case."""
LOG_SETTLE = 0.25
"""
Seconds to wait before reading a failed case's logs. Docker stamps and
stores a line when its daemon reads it from the container, a little after
the container wrote it: read at once, the log could lack the very request
the case failed on.
"""


class StackError(RuntimeError):
    """The services did not come up (or could not be reached): the environment, not the system under test."""


def _settings() -> Dict[str, Any]:
    from ipandora.common.dictutils import DictUtils
    from ipandora.core.schedule.runtime import Runtime
    return DictUtils.safe_get(Runtime.settings, 'stack') or {}


def _host_tag() -> str:
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:6]


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:40] or 'stack'


_CHECKED: Dict[str, Any] = {}


def docker() -> str:
    """
    The docker executable, with Compose v2.20+ and a daemon that answers --
    or the case is skipped, saying which is missing.
    """
    from ipandora.core.assertion import require
    from ipandora.core.assertion.check import Check
    _exe = _settings().get('docker') or shutil.which('docker') or ''
    if _CHECKED.get('exe') == _exe and _exe:
        return _exe
    _version, _daemon = (), ''
    if _exe and os.path.isfile(_exe):
        _version = _compose_version(_exe)
        _daemon = _run([_exe, 'info', '--format', '{{.ServerVersion}}'], timeout=20, check=False).stdout.strip()
    require(Check(name='有 Docker', ok=bool(_exe) and os.path.isfile(_exe),
                  expr='依赖环境（core/stack.py）需要 Docker 和 Docker Compose；没有找到 docker。'
                       '安装 Docker，或在配置里写 stack.docker'),
            Check(name='Docker Compose {}.{}+'.format(*COMPOSE_MIN), ok=_version >= COMPOSE_MIN,
                  expr='需要 Docker Compose v{}.{} 或更新的版本（`docker compose version`），现在是 {}'.format(
                      COMPOSE_MIN[0], COMPOSE_MIN[1], '.'.join(map(str, _version)) or '没有')),
            Check(name='Docker 守护进程在运行', ok=bool(_daemon),
                  expr='docker 连不上守护进程（`docker info` 失败）：启动 Docker，或检查 DOCKER_HOST'))
    _CHECKED['exe'] = _exe
    return _exe


def _compose_version(exe: str) -> tuple:
    _out = _run([exe, 'compose', 'version', '--short'], timeout=20, check=False).stdout
    _m = re.search(r'(\d+)\.(\d+)', _out or '')
    return (int(_m.group(1)), int(_m.group(2))) if _m else ()


def _run(cmd: List[str], timeout: float, check: bool = True, env: Optional[Dict[str, str]] = None,
         cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    try:
        # bandit B603: docker, located by full path; arguments are ours, no shell
        _done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,  # nosec B603
                               cwd=cwd)
    except subprocess.TimeoutExpired:
        if check:
            raise StackError('{}: `{}` did not finish in {:g}s'.format(STACK_MARKER, ' '.join(cmd[1:4]), timeout))
        return subprocess.CompletedProcess(cmd, -1, '', 'timed out')
    except OSError as exc:
        if check:
            raise StackError('{}: could not run docker: {}'.format(STACK_MARKER, exc)) from None
        return subprocess.CompletedProcess(cmd, -1, '', str(exc))
    if check and _done.returncode != 0:
        raise StackError('{}: `{}` failed: {}'.format(STACK_MARKER, ' '.join(cmd[1:4]),
                                                       (_done.stderr or _done.stdout).strip()[-1500:]))
    return _done


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_ACTIVE: List['Stack'] = []
_GUARD = threading.Lock()
_SWEPT = []


def active() -> List['Stack']:
    """The stacks this process has up right now."""
    with _GUARD:
        return list(_ACTIVE)


def clean(exe: Optional[str] = None) -> List[str]:
    """
    Take down the projects of processes on this host that died with a stack
    up (`ipandora-<this host>-<pid>-...` whose pid is gone). Returns their names.
    Never a project of a live process, or of another host sharing the daemon.
    """
    _exe = exe or docker()
    _done = _run([_exe, 'compose', 'ls', '--all', '--format', 'json'], timeout=60, check=False)
    try:
        _projects = json.loads(_done.stdout or '[]') or []
    except ValueError:
        return []
    _mine = re.compile(r'^{}{}-(\d+)-'.format(re.escape(PREFIX), _host_tag()))
    _removed = []
    for _p in _projects:
        _m = _mine.match(str(_p.get('Name', '')))
        if _m and int(_m.group(1)) != os.getpid() and not _alive(int(_m.group(1))):
            _run([_exe, 'compose', '-p', _p['Name'], 'down', '-v', '--remove-orphans', '--timeout', '5'],
                 timeout=120, check=False)
            _removed.append(_p['Name'])
    return _removed


_STAMP = re.compile(r'(?:^|\|\s)(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z\s')


def _since(text: str, since: float) -> str:
    """
    Only the lines logged at or after `since`. Docker's own --since stops at
    whole seconds, so a failed case's evidence began with the log of the case
    before it whenever the two ran within the same second -- a request that
    case never made, shown as its own. Every line carries the timestamp
    `--timestamps` asked for; a line without one belongs to the line before.
    The timestamp is when Docker's daemon read the line, a little after the
    container wrote it, so a line the previous case caused in its last
    moments can still fall just inside: documented in docs/guide/stack.md.
    """
    _kept, _keep = [], True
    for _line in text.splitlines(keepends=True):
        _m = _STAMP.search(_line)
        if _m:
            _at = datetime.strptime(_m.group(1), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
            _at += float('0.' + (_m.group(2) or '0'))
            _keep = _at >= since
        if _keep:
            _kept.append(_line)
    return ''.join(_kept)


class Stack:
    """A compose project this process started. See compose()."""

    def __init__(self, files: Sequence[str], project: str, exe: str, env: Dict[str, str], host: str):
        self.files, self.project, self._exe, self._env, self.host = list(files), project, exe, env, host
        self.started = time.time()

    def _cmd(self, *args: str) -> List[str]:
        _cmd = [self._exe, 'compose', '-p', self.project]
        for _f in self.files:
            _cmd += ['-f', _f]
        return _cmd + list(args)

    def _call(self, *args: str, timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
        return _run(self._cmd(*args), timeout=timeout, check=check, env=self._env,
                    cwd=os.path.dirname(self.files[0]) or None)

    def services(self) -> List[str]:
        return [_s for _s in self._call('config', '--services').stdout.split() if _s]

    def port(self, service: str, container_port: Union[int, str], protocol: str = 'tcp') -> int:
        """The host port `service`'s `container_port` is published on."""
        _out = self._call('port', '--protocol', protocol, service, str(container_port), check=False)
        _m = re.search(r':(\d+)\s*$', _out.stdout or '')
        if _out.returncode != 0 or not _m:
            raise StackError('{}: {} does not publish port {}/{} -- list it under `ports:` as "{}"'.format(
                STACK_MARKER, service, container_port, protocol, container_port))
        return int(_m.group(1))

    def address(self, service: str, container_port: Union[int, str]) -> str:
        """`host:port` to reach `service`'s `container_port` from here."""
        return '{}:{}'.format(self.host, self.port(service, container_port))

    def url(self, service: str, container_port: Union[int, str], scheme: str = 'http', path: str = '') -> str:
        return '{}://{}{}'.format(scheme, self.address(service, container_port), path)

    def logs(self, service: Optional[str] = None, since: Optional[float] = None, tail: Optional[int] = None) -> str:
        """The service's log (all services' without one), from `since` (epoch seconds) on."""
        _args = ['logs', '--no-color', '--timestamps']
        if since is not None:
            _args += ['--since', datetime.fromtimestamp(since, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')]
        if tail is not None:
            _args += ['--tail', str(int(tail))]
        _out = self._call(*(_args + ([service] if service else [])), timeout=60, check=False).stdout
        return _out if since is None else _since(_out, since)

    def keep_logs(self, nodeid: str, since: float) -> List[Dict[str, str]]:
        """
        Each service's log since `since`, last LOG_LINES lines, redacted, as
        artifacts of the case: written next to the report and quoted in it.
        """
        from ipandora.core.assertion.visual import ARTIFACTS_VAR
        from ipandora.core.report.redact import redact_text
        _dir = os.environ.get(ARTIFACTS_VAR) or os.path.join(tempfile.gettempdir(), 'ipandora-service-logs')
        os.makedirs(_dir, exist_ok=True)
        _entries = []
        for _service in self.services():
            _lines = self.logs(_service, since=since, tail=LOG_LINES).splitlines()[-LOG_LINES:]
            if not _lines:
                continue
            _text = redact_text('\n'.join(_lines))
            _path = os.path.join(_dir, '{}-{}-{}.log'.format(
                re.sub(r'[^A-Za-z0-9_.-]+', '_', nodeid)[-100:], _slug(_service), int(since * 1000)))
            with open(_path, 'w', encoding='utf-8') as _f:
                _f.write(_text + '\n')
            _entries.append({'kind': 'service-log', 'path': os.path.abspath(_path), 'group': _service,
                             'text': _text})
        return _entries

    def _failing(self) -> str:
        """Which services did not come up, with their last log lines."""
        _out = self._call('ps', '--all', '--format', 'json', timeout=60, check=False).stdout or ''
        _rows = []
        for _line in _out.splitlines():
            try:
                _row = json.loads(_line)
            except ValueError:
                continue
            _rows += _row if isinstance(_row, list) else [_row]
        _bad = [_r for _r in _rows if _r.get('Health') not in ('', 'healthy', None)
                or _r.get('State') not in ('running',)]
        _parts = []
        for _r in _bad[:3]:
            _service = _r.get('Service', '?')
            _tail = self.logs(_service, tail=15).strip()
            _parts.append('{}：{}{}\n{}'.format(_service, _r.get('State', '?'),
                                               '（{}）'.format(_r['Health']) if _r.get('Health') else '', _tail))
        return '\n'.join(_parts)

    def up(self, services: Sequence[str], wait: float) -> None:
        try:
            self._call('up', '--detach', '--wait', '--wait-timeout', str(int(wait)), *services,
                       timeout=wait + 600)                # pulling images is not part of `wait`
        except StackError as exc:
            _detail = ''
            try:
                _detail = self._failing()
            except StackError:
                pass
            from ipandora.core.report.redact import redact_text
            raise StackError('{}\n{}'.format(exc, redact_text(_detail)).strip()) from None

    def down(self) -> None:
        self._call('down', '--volumes', '--remove-orphans', '--timeout', '10', timeout=300, check=False)


def compose(files: Union[str, Iterable[str]], services: Sequence[str] = (), env: Optional[Dict[str, str]] = None,
            wait: float = 120, name: Optional[str] = None) -> '_Up':
    """
    Start the compose project in `files` (one path or several) and wait for
    its services' health checks; a context manager yielding the Stack, taken
    down -- volumes included -- whatever happens. `services`: only these
    (and what they depend on). `env`: variables for the file's ${...}.
    """
    _files = [files] if isinstance(files, str) else list(files)
    if not _files:
        raise ValueError('compose() needs a compose file')
    _files = [os.path.abspath(_f) for _f in _files]
    for _f in _files:
        if not os.path.isfile(_f):
            raise FileNotFoundError('compose file not found: {}'.format(_f))
    return _Up(_files, list(services), env, wait, name)


def _project_name(name: str, files: Sequence[str]) -> str:
    """
    `ipandora-<host>-<pid>-<name>-<files>`, and a number when the same files
    are up twice at once. The files' paths are in it: by its name alone, the
    compose.yaml of shop/ and of payment/ were one project -- the second `up`
    joined the first, and taking either down removed both.
    """
    _base = '{}{}-{}-{}-{}'.format(PREFIX, _host_tag(), os.getpid(), _slug(name),
                                   hashlib.sha256('\n'.join(files).encode()).hexdigest()[:6])
    with _GUARD:
        _taken = {_s.project for _s in _ACTIVE}
    _project, _n = _base, 1
    while _project in _taken:
        _n += 1
        _project = '{}-{}'.format(_base, _n)
    return _project


class _Up:
    def __init__(self, files, services, env, wait, name):
        self.files, self.services, self.env, self.wait = files, services, env, wait
        self.name = name or os.path.splitext(os.path.basename(files[0]))[0]
        self.stack: Optional[Stack] = None

    def __enter__(self) -> Stack:
        _exe = docker()
        if not _SWEPT:
            _SWEPT.append(True)
            try:
                _removed = clean(_exe)
                if _removed:
                    _log.info('removed stacks left by processes that died: %s', ', '.join(_removed))
            except StackError as exc:
                _log.warning('could not look for leftover stacks: %s', exc)
        _env = dict(os.environ, **{_k: str(_v) for _k, _v in (self.env or {}).items()})
        _project = _project_name(self.name, self.files)
        self.stack = Stack(self.files, _project, _exe, _env, str(_settings().get('host') or '127.0.0.1'))
        try:
            self.stack.up(self.services, self.wait)
        except BaseException:
            self.stack.down()
            raise
        with _GUARD:
            _ACTIVE.append(self.stack)
        return self.stack

    def __exit__(self, *exc) -> None:
        with _GUARD:
            if self.stack in _ACTIVE:
                _ACTIVE.remove(self.stack)
        self.stack.down()


def keep_logs(nodeid: str, since: float) -> None:
    """Service logs of every stack up, for a case that failed (core/runner/plugin.py)."""
    from ipandora.core.evidence import recorder
    _stacks = active()
    if _stacks:
        time.sleep(LOG_SETTLE)
    for _stack in _stacks:
        try:
            for _entry in _stack.keep_logs(nodeid, since):
                recorder.add_artifact(_entry)
        except (StackError, OSError) as exc:
            _log.warning('could not keep the service logs of %s: %s', nodeid, exc)


__all__ = ['compose', 'Stack', 'StackError', 'active', 'clean', 'docker', 'keep_logs', 'STACK_MARKER', 'PREFIX']

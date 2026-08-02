# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : runtime.py
@Time  : 2024-04-19
"""
import os
import socket
import threading
from typing import Union, List
from ipandora.common.dictutils import DictUtils
from ipandora.common.stringaction import StringAction
from ipandora.common.systeminfo import SystemInfo
from ipandora.core.base.classwrap.classproperty import (ClassProperty, ClassPropertyMeta,
                                                        classproperty)
from ipandora.core.engine.crypto.crypto import CryptoFactory
from ipandora.utils.fileload import FileLoad
from ipandora.utils.pathutils import PathUtils


class Runtime(object):
    exc_info = ''
    product = ''
    settings = FileLoad(
        os.path.join(PathUtils().pandora_path, 'conf/config.yaml')).load_yaml()  # type:dict

    # Snapshot of every section's memo slots, taken at import before anything
    # has been read. Populated by _snapshot_config_defaults() below.
    _config_defaults = {}

    @classmethod
    def reset(cls, *sections):
        """
        Drop the lazily-cached config values so they are re-read from
        `settings` on next access.

        Every config classproperty memoises into a private `_field` on first
        read, process-wide. That is fine in a normal run, but it means a test
        that overrides one leaks the override into every test after it, and
        that reassigning `Runtime.settings` has no effect on anything already
        touched. Call this after changing settings, or between tests that
        override config.

            Runtime.reset()            # everything
            Runtime.reset('Http')      # one section
        """
        _names = sections or list(cls._config_defaults)
        for _name in _names:
            _slots = cls._config_defaults.get(_name)
            if _slots is None:
                raise ValueError('unknown Runtime section {!r}; known: {}'.format(
                    _name, ', '.join(sorted(cls._config_defaults))))
            _section = getattr(cls, _name)
            for _attr, _value in _slots.items():
                # bypass ClassPropertyMeta.__setattr__, which would route a
                # public name to its property setter instead of the memo slot
                type.__setattr__(_section, _attr,
                                 list(_value) if isinstance(_value, list) else _value)

    class User(metaclass=ClassPropertyMeta):
        _user = ''

        @classproperty
        def user(self):
            if not self._user:
                self._user = SystemInfo().user
            return self._user

        @user.set
        def user(self, value):
            self._user = value

    class Mysql(metaclass=ClassPropertyMeta):
        _host = ''
        _username = ''
        _password = ''
        _port = 3306
        _database = ''

        @classproperty
        def host(self):
            if not self._host:
                self._host = DictUtils.safe_get(Runtime.settings, 'mysql', 'host')
            return self._host

        @host.set
        def host(self, value):
            self._host = value

        @classproperty
        def username(self):
            if not self._username:
                self._username = DictUtils.safe_get(Runtime.settings, 'mysql', 'username')
            return self._username

        @username.set
        def username(self, value):
            self._username = value

        @classproperty
        def password(self):
            if not self._password:
                self._password = DictUtils.safe_get(Runtime.settings, 'mysql', 'password')
                if self._password and StringAction.is_base64_encoded(self._password):
                    self._password = CryptoFactory().aes.decrypt(self._password)
            return self._password

        @password.set
        def password(self, value):
            self._password = value

        @classproperty
        def port(self):
            if not self._port:
                self._port = DictUtils.safe_get(Runtime.settings, 'mysql', 'port')
            return self._port

        @port.set
        def port(self, value):
            self._port = value

        @classproperty
        def database(self):
            if not self._database:
                self._database = DictUtils.safe_get(Runtime.settings, 'mysql', 'database')
            return self._database

        @database.set
        def database(self, value):
            self._database = value

    class Email(metaclass=ClassPropertyMeta):
        _host = ''
        _username = ''
        _password = ''
        _port = 465
        _recipients = []

        @classproperty
        def host(self):
            if not self._host:
                self._host = DictUtils.safe_get(Runtime.settings, 'email', 'host')
            return self._host

        @host.set
        def host(self, value):
            self._host = value

        @classproperty
        def username(self):
            if not self._username:
                self._username = DictUtils.safe_get(Runtime.settings, 'email', 'username')
            return self._username

        @username.set
        def username(self, value):
            self._username = value

        @classproperty
        def password(self):
            if not self._password:
                self._password = DictUtils.safe_get(Runtime.settings, 'email', 'password')
            if self._password and StringAction.is_base64_encoded(self._password):
                self._password = CryptoFactory().aes.decrypt(self._password)
            return self._password

        @password.set
        def password(self, value):
            self._password = value

        @classproperty
        def port(self):
            if not self._port:
                self._port = DictUtils.safe_get(Runtime.settings, 'email', 'port')
            return self._port

        @port.set
        def port(self, value):
            self._port = value

        @classproperty
        def recipients(self):
            if not self._recipients:
                _tmp = DictUtils.safe_get(Runtime.settings, 'addressesTo', 'recipients')
                self._recipients = _tmp if _tmp else []
            return self._recipients

        @recipients.set
        def recipients(self, value):
            self._recipients = value

    class Http(metaclass=ClassPropertyMeta):
        """
        Transport reliability settings. See core/protocol/http/transport.py.

        `verify` defaults to True on purpose. It used to be forced to False for
        every HTTPS request, which hid exactly the certificate problems a test
        suite ought to catch.
        """
        _connect_timeout = 0
        _read_timeout = 0
        _verify = None
        _max_retries = None
        _backoff_factor = None
        _pool_maxsize = 0

        @classproperty
        def connect_timeout(self):
            if not self._connect_timeout:
                self._connect_timeout = DictUtils.safe_get(
                    Runtime.settings, 'http', 'connect_timeout') or 10.0
            return float(self._connect_timeout)

        @connect_timeout.set
        def connect_timeout(self, value):
            self._connect_timeout = value

        @classproperty
        def read_timeout(self):
            if not self._read_timeout:
                self._read_timeout = DictUtils.safe_get(
                    Runtime.settings, 'http', 'read_timeout') or 30.0
            return float(self._read_timeout)

        @read_timeout.set
        def read_timeout(self, value):
            self._read_timeout = value

        @classproperty
        def verify(self):
            if self._verify is None:
                _configured = DictUtils.safe_get(Runtime.settings, 'http', 'verify')
                # absent/'' means "not configured" -> secure default
                self._verify = True if _configured in ('', None) else bool(_configured)
            return self._verify

        @verify.set
        def verify(self, value):
            self._verify = value

        @classproperty
        def max_retries(self):
            if self._max_retries is None:
                _configured = DictUtils.safe_get(Runtime.settings, 'http', 'max_retries')
                self._max_retries = 2 if _configured in ('', None) else int(_configured)
            return self._max_retries

        @max_retries.set
        def max_retries(self, value):
            self._max_retries = value

        @classproperty
        def backoff_factor(self):
            if self._backoff_factor is None:
                _configured = DictUtils.safe_get(Runtime.settings, 'http', 'backoff_factor')
                self._backoff_factor = 0.3 if _configured in ('', None) else float(_configured)
            return self._backoff_factor

        @backoff_factor.set
        def backoff_factor(self, value):
            self._backoff_factor = value

        @classproperty
        def pool_maxsize(self):
            if not self._pool_maxsize:
                self._pool_maxsize = DictUtils.safe_get(
                    Runtime.settings, 'http', 'pool_maxsize') or 10
            return int(self._pool_maxsize)

        @pool_maxsize.set
        def pool_maxsize(self, value):
            self._pool_maxsize = value

    class Ai(metaclass=ClassPropertyMeta):
        """
        LLM access config. Disabled by default: nothing in core/ may depend on
        it, and it is never consulted during test execution.
        See docs/design/03-LLM接入边界.md.
        """
        _enabled = None
        _provider = ''
        _api_key = ''
        _model = ''
        _base_url = ''
        _timeout = 0
        _max_tokens = 0
        _max_calls_per_run = 0

        @classproperty
        def enabled(self):
            if self._enabled is None:
                self._enabled = DictUtils.safe_get(Runtime.settings, 'ai', 'enabled') or False
            return bool(self._enabled)

        @enabled.set
        def enabled(self, value):
            self._enabled = value

        @classproperty
        def max_calls_per_run(self):
            if not self._max_calls_per_run:
                self._max_calls_per_run = DictUtils.safe_get(
                    Runtime.settings, 'ai', 'max_calls_per_run') or 20
            return self._max_calls_per_run

        @max_calls_per_run.set
        def max_calls_per_run(self, value):
            self._max_calls_per_run = value

        @classproperty
        def provider(self):
            if not self._provider:
                self._provider = DictUtils.safe_get(Runtime.settings, 'ai', 'provider') or 'mock'
            return self._provider

        @provider.set
        def provider(self, value):
            self._provider = value

        @classproperty
        def api_key(self):
            if not self._api_key:
                self._api_key = DictUtils.safe_get(Runtime.settings, 'ai', 'api_key')
                if self._api_key and StringAction.is_base64_encoded(self._api_key):
                    self._api_key = CryptoFactory().aes.decrypt(self._api_key)
            return self._api_key

        @api_key.set
        def api_key(self, value):
            self._api_key = value

        @classproperty
        def model(self):
            if not self._model:
                self._model = DictUtils.safe_get(Runtime.settings, 'ai', 'model')
            return self._model

        @model.set
        def model(self, value):
            self._model = value

        @classproperty
        def base_url(self):
            if not self._base_url:
                self._base_url = DictUtils.safe_get(Runtime.settings, 'ai', 'base_url')
            return self._base_url

        @base_url.set
        def base_url(self, value):
            self._base_url = value

        @classproperty
        def timeout(self):
            if not self._timeout:
                self._timeout = DictUtils.safe_get(Runtime.settings, 'ai', 'timeout') or 30
            return self._timeout

        @timeout.set
        def timeout(self, value):
            self._timeout = value

        @classproperty
        def max_tokens(self):
            if not self._max_tokens:
                self._max_tokens = DictUtils.safe_get(Runtime.settings, 'ai', 'max_tokens') or 1024
            return self._max_tokens

        @max_tokens.set
        def max_tokens(self, value):
            self._max_tokens = value

    class Mcp(metaclass=ClassPropertyMeta):
        _enabled = None
        _name = ''
        _transport = ''

        @classproperty
        def enabled(self):
            if self._enabled is None:
                self._enabled = DictUtils.safe_get(Runtime.settings, 'mcp', 'enabled')
            return bool(self._enabled)

        @enabled.set
        def enabled(self, value):
            self._enabled = value

        @classproperty
        def name(self):
            if not self._name:
                self._name = DictUtils.safe_get(Runtime.settings, 'mcp', 'name') or 'intellipandora'
            return self._name

        @name.set
        def name(self, value):
            self._name = value

        @classproperty
        def transport(self):
            if not self._transport:
                self._transport = DictUtils.safe_get(Runtime.settings, 'mcp', 'transport') or 'stdio'
            return self._transport

        @transport.set
        def transport(self, value):
            self._transport = value

    class Path(metaclass=ClassPropertyMeta):
        _pandora_path = ''

        @classproperty
        def pandora_path(self):
            if not self._pandora_path:
                self._pandora_path = PathUtils().pandora_path
            return self._pandora_path

        @pandora_path.set
        def pandora_path(self, value):
            self._pandora_path = value

    class Device(metaclass=ClassPropertyMeta):

        ip = socket.gethostbyname(socket.gethostname())

    class Host(metaclass=ClassPropertyMeta):
        """
        Reporting endpoint. Credentials must never be hardcoded here -- put
        them in conf/config.yaml (AES-encrypted, same as mysql/email) and read
        them through a classproperty.
        """
        _report_host = ''

        @classproperty
        def report_host(self):
            if not self._report_host:
                self._report_host = DictUtils.safe_get(Runtime.settings, 'report', 'host') or ''
            return self._report_host

        @report_host.set
        def report_host(self, value):
            self._report_host = value

    class Case(metaclass=ClassPropertyMeta):
        """
        Per-case step recording.

        State is thread-local. It used to be a process-global dict keyed by a
        single process-global case name, so under any concurrency every
        thread's steps landed under whichever case name was set last. Reading
        `steps` also used to pop, meaning the first reader emptied it and a
        second read silently returned [].
        """
        _local = threading.local()

        @classmethod
        def _steps_store(cls) -> dict:
            if not hasattr(cls._local, 'case_steps'):
                cls._local.case_steps = {}
            return cls._local.case_steps

        @classproperty
        def case_list(self) -> List:
            if not hasattr(self._local, 'case_list'):
                self._local.case_list = []
            return self._local.case_list

        @case_list.set
        def case_list(self, value):
            self._local.case_list = value

        @classproperty
        def cur_case_name(self) -> str:
            return getattr(self._local, 'cur_case_name', None)

        @cur_case_name.set
        def cur_case_name(self, case_name):
            self._local.cur_case_name = case_name

        @classproperty
        def steps(self) -> List:
            # Non-destructive: reading a value must not consume it. Use
            # drain_steps() where the caller genuinely wants to take them.
            return list(self._steps_store().get(self.cur_case_name, []))

        @steps.set
        def steps(self, step: list):
            if step:
                _l = self._steps_store().setdefault(self.cur_case_name, [])
                _l.append(step)

        @classmethod
        def drain_steps(cls, case_name=None) -> List:
            """Take and clear the steps for a case (the old `steps` behaviour)."""
            return cls._steps_store().pop(
                cls.cur_case_name if case_name is None else case_name, [])

        @classmethod
        def clear(cls):
            """Drop everything recorded for the current thread."""
            cls._steps_store().clear()
            cls._local.cur_case_name = None
            cls._local.case_list = []

    class Option(metaclass=ClassPropertyMeta):

        _project_name = None
        _only_api = False

        @classproperty
        def project_name(self):
            return self._project_name

        @project_name.set
        def project_name(self, v):
            self._project_name = v

        @classmethod
        def getMetaData(cls, option=None, default: Union[bool, str] = False):
            if option is None:
                return default
            try:
                if Runtime.Frame.is_rf:
                    return Runtime.settings \
                        .get('suite_config', {}) \
                        .get('metadata', {}) \
                        .get(option, default)
                elif Runtime.Frame.is_pytest:
                    return Runtime.settings.get(option, default)
                else:
                    return Runtime.settings.get(option, default)
            except (KeyError, TypeError, AttributeError):
                pass
            return default

        @classproperty
        def project_id(self):
            return self.getMetaData(option='project_id') or self.getMetaData(option='pid')

        @classproperty
        def task_id(self):
            return self.getMetaData(option='task_id') or self.getMetaData(option='tid')

        @classproperty
        def test_type(self):
            return self.getMetaData(option='test_type') or self.getMetaData(option='tp')

        @classproperty
        def job_name(self):
            return self.getMetaData(option='job_name')

        @classproperty
        def ros(self):
            return self.getMetaData(option='ros')

        @classproperty
        def model(self):
            return self.getMetaData(option='model')

        @classproperty
        def upload_tag(self):
            return self.getMetaData(option='upload_tag')

        @classproperty
        def tester(self):
            return self.getMetaData(option='tester')

        @classproperty
        def case_release(self):
            return self.getMetaData(option='case_release')

        @classproperty
        def no_log(self):
            return self.getMetaData(option='no_log')

        @classmethod
        def report_detail(cls):
            return cls.getMetaData(option='upload_detail')

        @classmethod
        def browser(cls):
            return str(cls.getMetaData(option='browser', default='chrome')) \
                .capitalize()

        @classmethod
        def browser_executable_path(cls, default=''):
            return str(cls.getMetaData(option='browser_executable_path', default=''))

        @classmethod
        def remote(cls):
            return cls.getMetaData(option='remote', default='')

        @classproperty
        def only_api(self):
            return self._only_api \
                or self.getMetaData(option='only_api', default=False)

        @only_api.set
        def only_api(self, v: bool = False):
            self._only_api = v

    class Frame(metaclass=ClassPropertyMeta):

        _is_pytest = False

        _is_locust = False

        @classproperty
        def is_rf(self):
            try:
                from robot.running import EXECUTION_CONTEXTS
                if EXECUTION_CONTEXTS.current:
                    return True
            except ImportError:
                return False

            return False

        @classproperty
        def is_pytest_upload_case(self):
            return Runtime.Option \
                .getMetaData(option='pandora_upload_case', default=False)

        @classproperty
        def is_pytest(self):
            return self._is_pytest

        @is_pytest.set
        def is_pytest(self, v):
            self._is_pytest = v

        @classproperty
        def is_locust(self):
            return self._is_locust

        @is_locust.set
        def is_locust(self, v):
            self._is_locust = v

    class Ui(metaclass=ClassPropertyMeta):
        _platform = 'web'

        @classproperty
        def is_web(self):
            return True

        @classproperty
        def is_android(self):
            return False

        @classproperty
        def is_ios(self):
            return False

        @classproperty
        def is_mobile(self):
            return self.is_ios or self.is_android

        @classproperty
        def platform(self):
            return self._platform or 'ui'

        @platform.set
        def platform(self, v: str):
            self._platform = v.lower()

def _snapshot_config_defaults():
    """
    Record each section's memo slots before anything reads them, so
    Runtime.reset() can restore real defaults instead of guessing blanks by
    type. Runs once at import.
    """
    _memo_types = (str, int, float, bool, list, type(None))
    for _name, _section in vars(Runtime).items():
        if not isinstance(_section, type) or not _name[0].isupper():
            continue
        _slots = {}
        for _attr, _value in vars(_section).items():
            if not _attr.startswith('_') or _attr.startswith('__'):
                continue
            if isinstance(_value, ClassProperty) or callable(_value):
                continue
            # threading.local and similar live state must not be restored
            if not isinstance(_value, _memo_types):
                continue
            _slots[_attr] = list(_value) if isinstance(_value, list) else _value
        if _slots:
            Runtime._config_defaults[_name] = _slots


_snapshot_config_defaults()

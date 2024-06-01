# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : runtime.py
@Time  : 2024-04-19
"""
import os
import socket
from typing import Union

from ipandora.common.dictutils import DictUtils
from ipandora.common.stringaction import StringAction
from ipandora.common.systeminfo import SystemInfo
from ipandora.core.base.classwrap.classproperty import classproperty, ClassPropertyMeta
from ipandora.core.engine.crypto.crypto import CryptoFactory
from ipandora.utils.fileload import FileLoad
from ipandora.utils.pathutils import PathUtils


class Runtime(object):
	exc_info = ''
	product = ''
	settings = FileLoad(
		os.path.join(PathUtils().pandora_path, 'conf/config.yaml')).load_yaml()  # type:dict

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

		# influx_host = 'internal-mirrors.yitu-inc.com'
		report_host = 'https://xxxx.com'
		# report_host = 'http://10.40.56.199:31000'
		user_name = 'ficus-ci'
		password = 'Hello=1@3$5^'

	class Case(metaclass=ClassPropertyMeta):

		case_list = []

		_case_steps = {}

		_cur_case_name = None

		@classproperty
		def cur_case_name(self) -> str:
			return self._cur_case_name

		@cur_case_name.set
		def cur_case_name(self, case_name):
			self._cur_case_name = case_name

		@classproperty
		def steps(self) -> list:
			return self._case_steps.pop(self.cur_case_name, [])

		@steps.set
		def steps(self, step: list):
			if step:
				_l = self._case_steps.setdefault(self.cur_case_name, [])
				_l.append(step)

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
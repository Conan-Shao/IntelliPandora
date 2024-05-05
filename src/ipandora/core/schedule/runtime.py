# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : runtime.py
@Time  : 2024-04-19
"""
import socket
from typing import Union
from ipandora.core.base.classwrap.classproperty import classproperty, ClassPropertyMeta


class Runtime(object):
	exc_info = ''
	product = ''
	settings = {}  # type:dict

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
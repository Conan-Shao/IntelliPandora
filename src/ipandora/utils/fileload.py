# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : fileload.py
@Time  : 2024-05-07
"""
import os
import json
import yaml
from ipandora.utils.log import logger
from ipandora.utils.error import FileError, DataError


class FileLoad(object):
    def __init__(self, _config):
        self.config = _config
        if not self.config or not os.path.exists(self.config):
            raise DataError("Initialization fail. The file not exists.<{}>".format(self.config))

    def load_yaml(self):
        return self._load_file('yaml')

    def load_json(self):
        return self._load_file('json')

    def _load_file(self, file_type):
        try:
            with open(self.config, 'r') as f:
                if file_type == 'yaml':
                    _result = yaml.safe_load(f)
                elif file_type == 'json':
                    _result = json.load(f)
                else:
                    raise FileError("Unsupported file type: {}".format(file_type))
                logger.debug("{} Content: {}".format(file_type.upper(), _result))
                return _result
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise FileError("Failed to load {} file: {}".format(file_type, e))


if __name__ == '__main__':
    _c_path = '/ipandora/conf/generator/robot_gen_config.yaml'
    result = FileLoad(_c_path).load_yaml()
    a = result.get('data').get('suites')
    print(a)

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : fileaction.py
@Time  : 2024-04-24
"""
import os


class FileAction(object):
    def __init__(self):
        self._home_path = None
        self._pandora_path = None

    @property
    def pandora_path(self):
        if not self._pandora_path:
            self._pandora_path = FileAction.get_pandora_path()
        return self._pandora_path

    @property
    def home_path(self):
        if not self._home_path:
            self._home_path = FileAction.get_home_path()
        return self._home_path

    @staticmethod
    def get_pandora_path():
        """
        return the abs path of pandoragt lib, not the code repo
        :return:
        """
        here = FileAction.current_path()
        here_list = here.split('/')
        if 'ipandora' not in here_list:
            index = -1
        else:
            index = here_list.index('ipandora')
        return '/'.join(here_list[:index+1])

    @staticmethod
    def current_path(file_path: str = ''):
        if not file_path:
            return os.path.abspath(os.path.dirname(__file__)).replace('\\', '/')
        else:
            return os.path.abspath(file_path)

    @staticmethod
    def get_home_path():
        _home_path = os.path.expanduser('~')
        return _home_path


if __name__ == '__main__':
    print(FileAction().pandora_path)
    print(FileAction().home_path)

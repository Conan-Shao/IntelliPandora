# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : pathutils.py
@Time  : 2024-04-24
"""
import os
from ipandora.utils.log import logger


class PathUtils(object):
    def __init__(self):
        self._home_path = ''
        self._pandora_path = ''

    @property
    def pandora_path(self):
        if not self._pandora_path:
            self._pandora_path = PathUtils.get_pandora_path()
        return self._pandora_path

    @property
    def home_path(self):
        if not self._home_path:
            self._home_path = PathUtils.get_home_path()
        return self._home_path

    @property
    def current_path(self):
        return os.getcwd()

    @staticmethod
    def get_pandora_path():
        """
        return the abs path of ipandora lib, not the code repo
        :return:
        """
        here = PathUtils.file_path()
        here_list = here.split('/')
        if 'ipandora' not in here_list:
            index = -1
        else:
            index = here_list.index('ipandora')
        return '/'.join(here_list[:index+1])

    @staticmethod
    def file_path(file_path: str = ''):
        if not file_path:
            return os.path.abspath(os.path.dirname(__file__)).replace('\\', '/')
        else:
            return os.path.abspath(file_path)

    @staticmethod
    def get_home_path():
        _home_path = os.path.expanduser('~')
        return _home_path

    @staticmethod
    def is_directory(dir_path):
        """Check if the given path is a directory."""
        return os.path.isdir(dir_path)

    @staticmethod
    def create_directory(dir_path):
        """Create a directory at the specified path if it is not a directory or does not exist."""
        dir_path = PathUtils.remove_trailing_slashes(os.path.expanduser(dir_path))
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
                logger.info(f"Directory created at: {dir_path}")
            except Exception as e:
                logger.error(f"Error: {e}")
                return False
        else:
            logger.warn(f"Directory already exists: {dir_path}")
        return dir_path

    @staticmethod
    def remove_trailing_slashes(s):
        return s.rstrip('/\\')

    @staticmethod
    def filter_files_in_directory(directory, filename_pattern=None, extension_pattern=None):
        """
        Filter files in the current directory based on the given patterns.
        Return a list of file names.
        :param directory:
        :param filename_pattern:
        :param extension_pattern: eg. '.txt', '.py', '.pem'
        :return:
        """
        filename_pattern = str(os.path.basename(os.path.splitext(filename_pattern)[0])) if (
            filename_pattern) else None
        filtered_files = []
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                name, ext = os.path.splitext(filename)
                if ((filename_pattern is None or filename_pattern in name) and
                        (extension_pattern is None or extension_pattern == ext)):
                    filtered_files.append(filename)
        return filtered_files


if __name__ == '__main__':
    # print(PathUtils().pandora_path)
    # print(PathUtils().home_path)
    # PathUtils().create_directory('~/robot_copilot')
    a = PathUtils().file_path('/ipandora/common/log/output.xml')
    print(os.path.dirname(a))
    res = PathUtils().filter_files_in_directory(
        '/Users/shaofeng/Repos/ipandora/src/ipandora/conf/crypto',
        extension_pattern='pem')
    print(res)

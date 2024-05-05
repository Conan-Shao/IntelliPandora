# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : cmd.py
# @Time  : 2024-04-17
import glob
import inspect
from os.path import abspath, join, dirname, isfile
from typing import Dict

from ipandora.run.commandbase import CommandBase
from ipandora.utils.importpath import ImportPath


class Cmd(object):
    cmd_map = {}  # type:Dict[str,CommandBase]

    @classmethod
    def find_modules(cls, path=None):
        path = path or join(dirname(abspath(__file__)), 'commands', '*.py')
        modules = glob.glob(join(path))
        return [m for m in modules if isfile(m) and not m.startswith('_')]

    @classmethod
    def load_sub_parsers(cls, parser, logger):
        for _file in cls.find_modules():
            for name, obj in inspect.getmembers(ImportPath(_file).module):
                if inspect.isclass(obj) and issubclass(obj, CommandBase) \
                        and obj != CommandBase:
                    _cmd = obj(parser, logger)
                    cls.cmd_map.update({_cmd.sub_command_name: _cmd})


if __name__ == '__main__':
    Cmd().load_sub_parsers()
    print(Cmd().cmd_map)


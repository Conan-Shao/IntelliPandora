# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : commandbase.py
# @Time  : 2024-04-17
from abc import ABCMeta, abstractmethod
from argparse import ArgumentParser, Namespace
from functools import update_wrapper
from typing import Optional


def hook_option(f):
    def hook(*args, **kwargs):
        _self = args[0]
        if len(args) > 1:
            setattr(_self, 'options', args[1])
        elif len(kwargs) > 0:
            setattr(_self, 'options', kwargs.get('options', None))
        return f(*args, **kwargs)

    return update_wrapper(hook, f)


class CommandBase(metaclass=ABCMeta):

    def __init__(self, sub_parser, logger=None):
        self.logger = logger
        self.sub_parser = sub_parser
        self.options = None  # type:Optional[Namespace]

        self.parser = sub_parser.add_parser(
            self.sub_command_name,
            help=self.help)  # type:ArgumentParser
        self.globalArguments()
        self.add_arguments()

    @property
    @abstractmethod
    def help(self): pass

    @property
    @abstractmethod
    def sub_command_name(self):
        pass

    @abstractmethod
    def add_arguments(self):
        pass

    @abstractmethod
    def handle(self, options: Namespace):
        pass

    def globalArguments(self):
        # set global arguments here
        # self.parser.add_argument('-u', '--user', action='store')
        pass

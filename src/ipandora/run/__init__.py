# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : cmd.py
# @Time  : 2024-04-17
from ipandora.run.commandmanager import CommandManager


def command_line():
    CommandManager().parse_args()

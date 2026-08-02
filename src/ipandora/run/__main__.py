# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __main__.py
@Time  : 2026-08-02

`python -m ipandora.run`, equivalent to the `ipandora` console script.

Worth having on its own: it works from a source checkout with no install step,
and it lets a test drive the CLI through the interpreter it is already running
rather than whichever `ipandora` happens to be on PATH.
"""
from ipandora.run import command_line

if __name__ == '__main__':
    command_line()

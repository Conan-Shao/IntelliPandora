# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : check.py
@Time  : 2026-11-06
"""
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase


class Command(CommandBase):
    """
    Static checks of a case library. `layout`: the layering rules of
    docs/design/decisions/17 §3.3 -- judgements only in tests/, no fixed
    waits, no direct requests in cases, no hard-coded addresses in apis/.
    """

    def handle(self, options: Namespace):
        if getattr(options, 'check_action', None) != 'layout':
            self.parser.print_help()
            sys.exit(2)
        from ipandora.core import layout
        _root = os.path.abspath(options.directory)
        if not any(os.path.isdir(os.path.join(_root, _l)) for _l in layout.LAYERS):
            print('  ERROR  {} has none of {}: nothing to check'.format(
                _root, ', '.join(layout.LAYERS)), file=sys.stderr)
            sys.exit(2)
        _findings = layout.check(_root)
        for _f in _findings:
            print('  {}'.format(_f))
        if not _findings:
            print('  OK  分层规则全部满足')
            sys.exit(0)
        print('')
        print('  {} 处不符合分层规则（规则见 docs/guide/layout.md）'.format(len(_findings)))
        sys.exit(0 if options.warn_only else 1)

    @property
    def help(self):
        return 'static checks of a case library: layout'

    @property
    def sub_command_name(self):
        return 'check'

    def add_arguments(self):
        _sub = self.parser.add_subparsers(dest='check_action')
        _layout = _sub.add_parser(
            'layout', help='judgements only in tests/; no sleeps, no direct requests in cases, '
                           'no fixed addresses in apis/. Exit 1 on any finding')
        _layout.add_argument('directory', nargs='?', default='.',
                             help='the project root, holding apis/, pages/, flows/, tests/')
        _layout.add_argument('--warn-only', action='store_true',
                             help='print the findings but exit 0, while a library is being moved over')

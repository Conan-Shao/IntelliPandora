# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : commandmanager.py
# @Time  : 2024-04-17
from argparse import ArgumentParser
from ipandora.version import get_latest_version
from ipandora.run.cmd import Cmd
from ipandora.run.ipandoracommand import IPandoraCommand
from ipandora.utils.log import Log
version = get_latest_version()


class CommandManager(object):
    ap = ArgumentParser()

    def __init__(self):
        self.cmd = Cmd()
        self.init_parser()
        self.args = None

    def parse_args(self):
        self.args = self.ap.parse_args()
        self.execute()

    def add_arguments(self):
        # add common arguments here
        self.ap.add_argument(
            '-v', '--verbosity',
            dest='verbosity',
            help="log verbosity",
            action='count'
        )

        self.ap.add_argument(
            '-V', '--version', dest='version',
            help="print version",
            action='version',
            version=version
        )

    def init_parser(self):
        self.add_arguments()
        _sub = self.ap.add_subparsers(
            help='ipandora support these sub-commands.',
            dest='subcommand')
        self.cmd.load_sub_parsers(_sub, self)

    def get_subparser(self, help_info='sub command'):
        return self.ap.add_subparsers(help=help_info, dest='subcommand')

    def execute(self):
        self.args.logger = self
        # handle
        if self.args.subcommand is not None and self.args.verbosity:
            IPandoraCommand().execute(self.args)
        elif self.args.subcommand is None:
            self.warn('command [ipandora] need a subcommand,'
                      ' please read the help info.')
        else:
            _handle = self.cmd.cmd_map.get(self.args.subcommand, None)
            if not _handle:
                self.warn(
                    'sub-command [{}] is invalid'.format(self.args.subcommand))

            _handle.handle(options=self.args)

    @classmethod
    def warn(cls, msg, sub_command=None):
        print(Log.redInfo(msg))
        print(cls.ap.format_help())
        exit(0)

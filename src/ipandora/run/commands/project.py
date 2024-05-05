# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : project.py
@Time  : 2024-04-19
"""
from argparse import Namespace
from ipandora.run.commandbase import CommandBase
from ipandora.run.ipandoracommand import IPandoraCommand


class Command(CommandBase):
    def handle(self, options: Namespace):
        if options.generator:
            if not options.test_framework:
                options.logger.warn(
                    'sub command [project] need a param [-tf],'
                    ' run `ipandora project -help`  for more detail')
            if not options.project_name:
                options.logger.warn('need a name to generator new project, '
                                    'use [-n|--project-name] set a name')
            IPandoraCommand().execute(options)
        else:
            options.logger.warn('need a name to generator new project, '
                                'use [-g]')

    @property
    def help(self):
        return 'project command'

    @property
    def sub_command_name(self):
        return 'project'

    def add_arguments(self):
        self.parser.add_argument(
            '-g', '--generator',
            action='store_true',
            default=False,
            help='generator new project.'
        )

        self.parser.add_argument(
            '-n', '--project-name',
            action='store',
            help='the name of new project folder.'
        )

        self.parser.add_argument(
            '-tf', '--test-framework',
            choices=['pytest'],
            default='pytest',
            help='point out which test framework used. Default value: [pytest]'
        )

        self.parser.add_argument(
            '-t', '--subtype',
            choices=['api', 'ui'],
            default='api',
            help='point out which directory will be used. Default value: [api]'
        )

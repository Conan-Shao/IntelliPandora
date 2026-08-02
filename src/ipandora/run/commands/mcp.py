# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : mcp.py
@Time  : 2026-08-01
"""
from argparse import Namespace
from ipandora.run.commandbase import CommandBase


class Command(CommandBase):
    def handle(self, options: Namespace):
        try:
            from ipandora.core.mcp.server import serve
        except ImportError as e:
            options.logger.warn(
                "The 'mcp' package is required to run this command. "
                "Install it with: pip install intellipandora[mcp] ({})".format(e))
            return
        from ipandora.core.schedule.runtime import Runtime
        if options.transport:
            Runtime.Mcp.transport = options.transport

        # Opt-in LLM triage. Deliberately wired here in run/ rather than in
        # core/: core must not know ai/ exists. Off unless ai.enabled is set.
        if Runtime.Ai.enabled:
            try:
                import ipandora.ai
                ipandora.ai.enable()
            except ImportError as e:
                options.logger.warn(
                    'ai.enabled is true but the AI extra is missing; '
                    'continuing with rule-based triage only ({})'.format(e))

        serve()

    @property
    def help(self):
        return 'start the MCP server exposing IntelliPandora capabilities to AI clients'

    @property
    def sub_command_name(self):
        return 'mcp'

    def add_arguments(self):
        self.parser.add_argument(
            '-t', '--transport',
            choices=['stdio'],
            default=None,
            help='MCP transport protocol. Default: value from conf/config.yaml (mcp.transport)'
        )

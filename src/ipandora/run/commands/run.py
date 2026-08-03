# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : run.py
@Time  : 2026-08-02
"""
import os
import re
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase


def _default_cassette(selector: str) -> str:
    """
    A cassette name derived from what was run.

    Deriving it means --record works without also having to invent a name,
    which is the difference between trying the feature and not.
    """
    _base = os.path.basename((selector or 'default').split('::')[0])
    _base = re.sub(r'\.py$', '', _base) or 'default'
    return re.sub(r'[^0-9A-Za-z_.-]+', '-', _base).strip('-') or 'default'


class Command(CommandBase):
    """
    Run a suite and produce its report.

    The pieces existed already -- runner, report builder, renderer, archive --
    but only as a library, so getting an HTML report meant writing three calls
    of Python. A report nobody can produce in one step is a report nobody
    produces.
    """

    def handle(self, options: Namespace):
        from ipandora.core.report import build
        from ipandora.core.report.history import archive
        from ipandora.core.runner import run
        from ipandora.core.schedule.runtime import Runtime

        if options.env:
            Runtime.Option.env = options.env

        # Opt-in LLM root cause, wired here in run/ rather than core/ -- core
        # must not know ai/ exists. Off unless ai.enabled is set.
        if Runtime.Ai.enabled and not options.no_ai:
            try:
                import ipandora.ai
                ipandora.ai.enable()
            except ImportError as exc:
                options.logger.warn(
                    'ai.enabled is true but the AI extra is missing; '
                    'continuing with rule-based triage only ({})'.format(exc))

        _tape = self._open_cassette(options)
        try:
            _result = run(options.selector, env=options.env or '',
                          extra_args=options.pytest_arg or None,
                          persist=not options.no_store)
        finally:
            self._close_cassette(options, _tape)

        _report = build(_result, title=options.title)

        if options.no_report:
            _paths = {}
        elif options.report_dir and options.no_archive:
            from ipandora.core.report.render import write
            _paths = write(_report, options.report_dir)
        else:
            _paths = archive(_report, directory=options.report_dir)

        self._print_summary(_result, _report, _paths)

        # The exit code is the run's verdict, not the report's. A suite that
        # failed must fail the shell that called it, or CI goes green on red.
        sys.exit(0 if _result.ok else 1)

    @staticmethod
    def _open_cassette(options):
        """
        Put the run into record or replay, if asked.

        The mode is set here, in the command, and never in a test: what a test
        asserts and where its responses come from are separate concerns, and
        welding them together means the same test can never be pointed at a
        real environment again.
        """
        from ipandora.core.cassette import Cassette, Mode
        from ipandora.core.protocol.http import replay

        _mode = Mode.RECORD if options.record else (
            Mode.REPLAY if options.replay else Mode.OFF)
        if _mode == Mode.OFF:
            return None

        _name = options.cassette or _default_cassette(options.selector)
        _tape = Cassette(_name, directory=options.cassette_dir,
                         on_exhausted=options.on_exhausted)

        if _mode == Mode.RECORD:
            _tape.start_recording(recorded_from=options.env or '')
        else:
            if not _tape.store.exists:
                raise SystemExit(
                    "没有名为 {!r} 的磁带（在 {}）。\n"
                    "先录一盘：ipandora run {} --record --cassette {}".format(
                        _name, _tape.store.root, options.selector, _name))
            _tape.load()

        replay.session.activate(_mode, _tape)
        return _tape

    @staticmethod
    def _close_cassette(options, tape):
        from ipandora.core.cassette import Mode
        from ipandora.core.protocol.http import replay
        if tape is None:
            return
        _mode = replay.session.mode
        replay.session.deactivate()

        if _mode == Mode.RECORD:
            from ipandora import version
            tape.finish_recording(version=getattr(version, '__version__', ''))
            print('\n  磁带  {} 条 → {}'.format(tape.manifest.count, tape.store.root))
        else:
            _age = tape.age_days
            print('\n  磁带  {} · {} 条已播 / 共 {} 条{}'.format(
                tape.name, tape.played, tape.total,
                ' · 录于 {:.0f} 天前'.format(_age) if _age is not None else ''))
            # A stale cassette keeps a suite green while testing an assumption
            # nobody holds anymore, and it does it silently. Saying the age out
            # loud is the cheap half of the fix; --max-cassette-age is the rest.
            if _age is not None and options.max_cassette_age \
                    and _age > options.max_cassette_age:
                raise SystemExit(
                    '  磁带已过期：{:.0f} 天 > 上限 {} 天。重录后再跑。'.format(
                        _age, options.max_cassette_age))

    @staticmethod
    def _print_summary(result, report, paths):
        print('')
        print('  {}  {}'.format('PASS' if result.ok else 'FAIL', result.headline()))
        print('  通过率 {} · {:.2f}s · {}'.format(
            report.pass_rate, result.duration, result.run_id))

        _checks = report.check_totals
        if _checks['passed'] or _checks['failed'] or _checks['gap']:
            print('  判定 {} 通过 · {} 失败{}'.format(
                _checks['passed'], _checks['failed'],
                ' · {} 未覆盖'.format(_checks['gap']) if _checks['gap'] else ''))

        for _grid in report.coverage_matrix:
            print('  覆盖 {} {}/{}'.format(_grid['title'], _grid['filled'], _grid['total']))

        if report.inconclusive:
            print('  {} 条什么都没测到，不计入通过率'.format(len(report.inconclusive)))

        if paths.get('html'):
            print('')
            print('  报告  {}'.format(paths['html']))
        if paths.get('index'):
            print('  历史  {}'.format(paths['index']))
        print('')

    @property
    def help(self):
        return 'run a suite and write its HTML report into the run history'

    @property
    def sub_command_name(self):
        return 'run'

    def add_arguments(self):
        self.parser.add_argument(
            'selector',
            help='what to run: a path, a path::node, or a -k expression')
        self.parser.add_argument(
            '-e', '--env', default='',
            help='environment name, recorded in the report')
        self.parser.add_argument(
            '--title', default=None,
            help='report title. Default: IntelliPandora Test Report')
        self.parser.add_argument(
            '-d', '--report-dir', default=None,
            help='where reports go. Default: $IPANDORA_REPORTS_DIR '
                 'or ~/.ipandora/reports')
        self.parser.add_argument(
            '--no-archive', action='store_true',
            help='write the report straight into --report-dir instead of into '
                 'the run history')
        self.parser.add_argument(
            '--no-report', action='store_true',
            help='run only; write no report')
        self.parser.add_argument(
            '--no-store', action='store_true',
            help='do not keep the raw run for explain_failure')
        self.parser.add_argument(
            '--no-ai', action='store_true',
            help='skip LLM root cause even when ai.enabled is set')
        self.parser.add_argument(
            '-p', '--pytest-arg', action='append', default=[],
            help='extra argument passed through to pytest; repeatable')

        _tape = self.parser.add_argument_group('流量录制回放')
        _mode = _tape.add_mutually_exclusive_group()
        _mode.add_argument(
            '--record', action='store_true',
            help='call the real system and record every exchange to a cassette')
        _mode.add_argument(
            '--replay', action='store_true',
            help='serve every response from the cassette; makes no network calls')
        _tape.add_argument(
            '--cassette', default=None,
            help='cassette name. Default: derived from the selector')
        _tape.add_argument(
            '--cassette-dir', default=None,
            help='where cassettes live. Default: $IPANDORA_CASSETTES_DIR '
                 'or ~/.ipandora/cassettes')
        _tape.add_argument(
            '--on-exhausted', choices=['error', 'last', 'passthrough'],
            default='error',
            help='what to do when a key has no recordings left. Default: error '
                 '-- a silent miss either reaches the real system while claiming '
                 'to replay, or serves the wrong response and passes')
        _tape.add_argument(
            '--max-cassette-age', type=float, default=None,
            help='fail if the cassette is older than this many days')

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : run.py
@Time  : 2026-08-02
"""
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase


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

        _extra = list(options.pytest_arg or [])
        from ipandora.core.runner import inventory
        _baseline = '' if options.no_baseline else options.baseline
        from ipandora.core.runner.api import MissingExtra
        try:
            _result = run(options.selector, env=options.env or '',
                          extra_args=_extra or None,
                          persist=not options.no_store,
                          baseline=_baseline,
                          workers=options.workers,
                          timeout=options.timeout,
                          update_goldens=options.update_baseline,
                          exclude_flaky=options.exclude_flaky)
        except (MissingExtra, ValueError) as exc:
            print('  ERROR  {}'.format(exc), file=sys.stderr)
            sys.exit(2)

        _report = build(_result, title=options.title)
        _report.gate_weakened = bool(options.fail_on_weakened and not options.update_baseline)
        # The local archive is where earlier runs live; with --no-archive the
        # report dir is not one, so the default archive is searched instead.
        from ipandora.core.report import compare
        try:
            compare.attach(_report, compare_with=options.compare_with,
                           directory=None if options.no_archive else options.report_dir)
        except ValueError as exc:
            print('  ERROR  --compare-with: {}'.format(exc), file=sys.stderr)
            sys.exit(2)

        if options.no_report:
            _paths = {}
        elif options.report_dir and options.no_archive:
            from ipandora.core.report.render import write
            _paths = write(_report, options.report_dir)
        else:
            _paths = archive(_report, directory=options.report_dir)

        # --junit-xml puts the file where CI expects it, which is rarely where
        # the history keeps it. Written even under --no-report: a gate needs
        # the XML, and "run only, no report" should not quietly disarm it.
        if options.junit_xml:
            _paths['junit'] = self._write_junit(_report, options.junit_xml)

        self._print_summary(_result, _report, _paths)

        _refused = False
        if options.update_baseline:
            _path = options.baseline or inventory.default_path()
            try:
                _saved = inventory.save(_path, inventory.updated(inventory.load(_path), _result))
            except inventory.NotAcceptable as exc:
                _refused = True
                print('  FAIL  判定基线没有更新：{}'.format(exc))
            else:
                print('  判定基线已更新  {}'.format(_saved))
                print('  把这个文件的改动和用例改动一起提交，评审时看它的 diff 就知道判定变了什么')
            print('')

        # The exit code is the run's verdict, not the report's. A suite that
        # failed must fail the shell that called it, or CI goes green on red.
        # --fail-on-weakened adds the second verdict: a pass that judges less
        # than the baseline is not accepted until someone updates the baseline.
        _weakened = bool(_result.weakened) and options.fail_on_weakened \
            and not options.update_baseline
        if _weakened:
            print('  FAIL  --fail-on-weakened：{} 处判定比基线弱。确认无误后用 --update-baseline 接受'.format(
                len(_result.weakened)))
            print('')
        # One rule for the exit code, the report's "退出码" line and `ipandora
        # merge`: the verdict. Two implementations had already drifted -- an
        # empty run read "exit 1" in the report while the command exited 0.
        sys.exit(0 if _report.verdict['releasable'] and not _refused else 1)

    @staticmethod
    def _write_junit(report, path):
        from ipandora.core.report.junit import write_to
        return write_to(report, path)

    @staticmethod
    def _print_summary(result, report, paths):
        def _names(nodeids):
            _short = [_n.rsplit('::', 1)[-1] for _n in nodeids]
            return '、'.join(_short[:3]) + ('…（共 {} 条）'.format(len(_short)) if len(_short) > 3 else '')

        print('')
        print('  {}  {}'.format('PASS' if result.ok else 'FAIL', result.headline()))
        _basis = report.pass_rate_basis
        print('  {}：{}'.format(report.verdict['label'], report.verdict['sentence']))
        print('  通过率 {}（{} / {}，{}）· {:.2f}s · {}'.format(
            report.pass_rate, _basis['passed'], _basis['denominator'], report.pass_rate_note,
            result.duration, result.run_id))

        _base = report.against_baseline
        if _base.get('newly_failing'):
            print('  基线里通过、这次失败：{}'.format(_names(_base['newly_failing'])))
        _run = report.against_run
        if _run:
            print('  对比 {}（{}）：新失败 {} · 仍失败 {} · 恢复 {}'.format(
                _run['run_id'] or '?', '传入的报告' if _run['source'] == 'argument' else '本机缓存',
                len(_run['newly_failing']), len(_run['still_failing']), len(_run['recovered'])))

        _checks = report.check_totals
        if _checks['passed'] or _checks['failed'] or _checks['gap']:
            print('  判定 {} 通过 · {} 失败{}'.format(
                _checks['passed'], _checks['failed'],
                ' · {} 未覆盖'.format(_checks['gap']) if _checks['gap'] else ''))

        for _grid in report.coverage_matrix:
            if _grid.get('problem'):
                print('  覆盖 无法识别：{}'.format(_grid['problem']))
            else:
                print('  覆盖 {} {}/{}'.format(_grid['title'], _grid['filled'], _grid['total']))

        if report.inconclusive:
            print('  {} 条什么都没测到，不计入通过率'.format(len(report.inconclusive)))

        _unverified = getattr(result, 'unverified', [])
        if _unverified:
            print('  {} 条通过了但没有任何判定：{}'.format(
                len(_unverified),
                '、'.join(_c.name for _c in _unverified[:3])
                + ('…' if len(_unverified) > 3 else '')))

        _changes = list(getattr(result, 'judgement_changes', []) or [])
        if _changes:
            _weak = [_c for _c in _changes if _c.get('weakening')]
            print('')
            print('  判定变化（对比 {}）：{} 处变弱，{} 处其他变化'.format(
                result.baseline, len(_weak), len(_changes) - len(_weak)))
            for _change in _changes[:12]:
                print('    {}'.format(_change.get('line', '')))
            if len(_changes) > 12:
                print('    … 共 {} 处，完整列表见报告'.format(len(_changes)))

        # Printed whether they passed or failed this time, and whether or not
        # they were excluded. A flaky marker that stops being mentioned is a
        # failure that has been parked.
        _deselected = list(getattr(result, 'deselected', []) or [])
        if _deselected:
            print('  {} 条标记为不稳定、被 --exclude-flaky 排除，未进入本次判定：{}'.format(
                len(_deselected),
                '、'.join(_n.rsplit('::', 1)[-1] for _n in _deselected[:3])
                + ('…' if len(_deselected) > 3 else '')))

        if report.flaky:
            print('  {} 条标记为不稳定：{}'.format(
                len(report.flaky),
                '、'.join('{}（{}）'.format(_c.name, _c.flaky)
                          for _c in report.flaky[:3])
                + ('…' if len(report.flaky) > 3 else '')))

        if paths.get('html'):
            print('')
            print('  报告  {}'.format(paths['html']))
        if paths.get('index'):
            print('  本机存档  {}'.format(paths['index']))
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
            help='environment name: overlays ./conf/<env>.yaml (or $IPANDORA_CONFIG_DIR/<env>.yaml) for this run, and is recorded in the report')
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
            '--exclude-flaky', action='store_true',
            help='skip cases marked @pytest.mark.flaky(reason=...). This is '
                 'what a gate runs: a known-unstable case must not be able to '
                 'fail a build. Without it they run and count normally')
        self.parser.add_argument(
            '--junit-xml', default=None, metavar='PATH',
            help='also write JUnit XML here, for CI and report viewers. One '
                 'is already written beside every report; this puts a copy '
                 'where the pipeline expects it')
        self.parser.add_argument(
            '--baseline', default=None, metavar='PATH',
            help='judgement inventory to compare with. Default: '
                 'conf/judgements.json in the project config dir, when it '
                 'exists')
        self.parser.add_argument(
            '--compare-with', default=None, metavar='REPORT',
            help='an earlier report.json (or the run directory holding it) to '
                 'compare failures with: new, still failing, recovered. In CI, '
                 'typically the last report from the main branch. Default: the '
                 'previous run of the same selector and environment in the local '
                 'report archive, when this machine has one; otherwise no '
                 'comparison. The committed baseline is compared either way')
        self.parser.add_argument(
            '--no-baseline', action='store_true',
            help='do not compare judgements with any baseline')
        self.parser.add_argument(
            '--update-baseline', action='store_true',
            help='accept this run\'s judgements as the new baseline, and write '
                 'every matches_golden() image as its new golden. Commit both: '
                 'their diff is what a reviewer reads to see which judgements '
                 'changed')
        self.parser.add_argument(
            '--fail-on-weakened', action='store_true',
            help='exit non-zero when judgements got weaker than the baseline '
                 '-- removed, loosened, changed, newly skipped or excluded, or '
                 'a case that passes without judging anything. The gate for '
                 'suites that agents edit')
        self.parser.add_argument(
            '-w', '--workers', default=None, metavar='N|auto',
            help='run in parallel with N worker processes (pytest-xdist), or '
                 '"auto" for one per CPU. Judgements, the report and the '
                 'baseline comparison are the same as a serial run. Cases '
                 'that share an account or other fixed data declare it with '
                 '@pytest.mark.resource("name") and never run at the same '
                 'time. Needs: pip install intellipandora[parallel]')
        self.parser.add_argument(
            '--timeout', default=None, type=float, metavar='SECONDS',
            help='fail any single case that runs longer than this '
                 '(pytest-timeout); triage blames the environment. Needs: '
                 'pip install intellipandora[parallel]')
        self.parser.add_argument(
            '--no-store', action='store_true',
            help='do not keep the raw run for explain_failure')
        self.parser.add_argument(
            '--no-ai', action='store_true',
            help='skip LLM root cause even when ai.enabled is set')
        self.parser.add_argument(
            '-p', '--pytest-arg', action='append', default=[],
            help='extra argument passed through to pytest; repeatable')

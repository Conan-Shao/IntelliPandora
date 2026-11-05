# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : merge.py
@Time  : 2026-11-05
"""
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase


class Command(CommandBase):
    """
    Merge the reports of a sharded run into one verdict.

    The last job of a sharded CI pipeline: download every shard's report.json
    and run this. Its exit code is the pipeline's verdict, the same rule as
    `ipandora run`, over all shards at once.
    """

    def handle(self, options: Namespace):
        from ipandora.core.report import compare, merge_files
        from ipandora.core.report.render import write

        try:
            _report, _ = merge_files(options.reports, title=options.title,
                                     allow_mixed_env=options.allow_mixed_env,
                                     baseline=options.baseline)
            _report.gate_weakened = bool(options.fail_on_weakened)
            if options.compare_with:
                compare.attach(_report, compare_with=options.compare_with, cache=False)
        except ValueError as exc:
            print('  ERROR  {}'.format(exc), file=sys.stderr)
            sys.exit(2)

        _paths = write(_report, options.out)
        if options.junit_xml:
            from ipandora.core.report.junit import to_junit
            os.makedirs(os.path.dirname(os.path.abspath(options.junit_xml)), exist_ok=True)
            with open(options.junit_xml, 'w', encoding='utf-8') as fh:
                fh.write(to_junit(_report))
            _paths['junit'] = os.path.abspath(options.junit_xml)

        _verdict = _report.verdict
        _basis = _report.pass_rate_basis
        print('')
        print('  {}：{}'.format(_verdict['label'], _verdict['sentence']))
        print('  合并 {} 个分片 · {} 条用例{} · 通过率 {}（{} / {}）'.format(
            len(_report.shards), len(_report.cases),
            '（去掉重复 {} 条）'.format(_report.duplicates) if _report.duplicates else '',
            _report.pass_rate, _basis['passed'], _basis['denominator']))
        for _conflict in _report.merge_conflicts[:12]:
            print('  不一致  {}  {}'.format(_conflict['nodeid'], ' / '.join(
                '{}={}'.format(_s['run_id'], _s['status']) for _s in _conflict['seen'])))
        if _report.against_run:
            _run = _report.against_run
            print('  对比 {}：新失败 {} · 仍失败 {} · 恢复 {}'.format(
                _run['run_id'] or '?', len(_run['newly_failing']),
                len(_run['still_failing']), len(_run['recovered'])))
        print('  报告  {}'.format(_paths.get('html')))
        print('')
        sys.exit(0 if _verdict['releasable'] else 1)

    @property
    def help(self):
        return 'merge the report.json of every shard into one report and one verdict'

    @property
    def sub_command_name(self):
        return 'merge'

    def add_arguments(self):
        self.parser.add_argument(
            'reports', nargs='+', metavar='REPORT',
            help='report.json files, or run directories holding one, one per shard')
        self.parser.add_argument(
            '-o', '--out', required=True, metavar='DIR',
            help='where the merged report.html, report.json and report.xml go')
        self.parser.add_argument(
            '--title', default=None,
            help='report title. Default: the first shard\'s')
        self.parser.add_argument(
            '--junit-xml', default=None, metavar='PATH',
            help='also write the merged JUnit XML here')
        self.parser.add_argument(
            '--fail-on-weakened', action='store_true',
            help='exit non-zero when any shard judged less than the baseline')
        self.parser.add_argument(
            '--baseline', default=None, metavar='PATH',
            help='the judgement baseline (conf/judgements.json) the shards together '
                 'cover. Every case it holds as passing that no shard reported is a '
                 'deleted judgement -- this is what catches a shard whose report never '
                 'arrived. Only pass it when the shards are the whole suite')
        self.parser.add_argument(
            '--compare-with', default=None, metavar='REPORT',
            help='an earlier (merged) report.json to compare failures with')
        self.parser.add_argument(
            '--allow-mixed-env', action='store_true',
            help='merge shards that ran against different environments. Refused '
                 'by default: one verdict over dev and staging is usually a mistake')

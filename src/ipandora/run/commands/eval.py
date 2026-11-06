# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : eval.py
@Time  : 2026-11-05
"""
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase


SELFCHECK_KINDS = (('fails', '的参考解判不过（任务或评分器有问题）'),
                   ('grader', '的评分器在参考解上报错或没有给出判定'),
                   ('missing', '没有参考解，无法自检'))


class Command(CommandBase):
    """
    Agent evaluation: run a spec, check its reference solutions, and the human
    labelling channel. See docs/guide/eval.md.
    """

    def handle(self, options: Namespace):
        _action = getattr(options, 'eval_action', None)
        try:
            if _action == 'run':
                sys.exit(self._run(options))
            if _action == 'selfcheck':
                sys.exit(self._selfcheck(options))
            if _action == 'samples':
                sys.exit(self._samples(options))
            if _action == 'agreement':
                sys.exit(self._agreement(options))
        except (ValueError, OSError) as exc:
            # a missing file, bad YAML or JSON: a message, not a traceback
            print('  ERROR  {}'.format(exc), file=sys.stderr)
            sys.exit(2)
        self.parser.print_help()
        sys.exit(2)

    @staticmethod
    def _run(options) -> int:
        from ipandora.core.eval import baseline, evaluate, report, spec
        _spec = spec.load(options.spec)
        _run = evaluate(_spec.dataset, _spec.agent, _spec.grade, trials=options.trials,
                        split=options.split, workers=options.workers, manifest=_spec.manifest)
        if options.baseline and not options.no_baseline and not os.path.isfile(options.baseline) \
                and not options.update_baseline:
            # asked for by name: a typo must not turn into "no baseline, all fine"
            raise ValueError('--baseline {}: no such file'.format(options.baseline))
        _path = '' if options.no_baseline else (options.baseline or baseline.default_path())
        _base = baseline.load(_path) if _path else None
        _comparison = baseline.compare(_run, _base, noise=options.noise,
                                       partial=options.partial) if _base else None

        from ipandora.core.report.history import reports_dir
        _out = options.out or os.path.join(reports_dir(), _run.run_id)
        _paths = report.write(_run, _out, _comparison, title=options.title)

        _s = _run.summary()
        _verdict = report.verdict(_run, _comparison)
        print('')
        print('  {}：{}'.format(_verdict['label'], _verdict['sentence']))
        if _s['interval']:
            print('  成功率 {}（95% 区间 {} – {}）· pass^{} {} · {} 次试验 · {} 次基础设施问题'.format(
                report._pct(_s['success_rate']), report._pct(_s['interval'][0]),
                report._pct(_s['interval'][1]), _s['k'], report._pct(_s['pass_hat_k']),
                _s['trials'], _s['infra']))
        for _kind, _text in SELFCHECK_KINDS:
            _ids = [_p['task_id'] for _p in _run.selfcheck if _p.get('kind') == _kind]
            if _ids:
                print('  {} 道题{}：{}'.format(len(_ids), _text, '、'.join(_ids[:5])))
        print('  报告  {}'.format(_paths['html']))
        if options.update_baseline:
            print('  评测基线已更新  {}'.format(baseline.save(_path or baseline.default_path(), _run)))
        print('')
        # The verdict is the exit code, as for `ipandora run` and `merge`: a
        # run that is worse than the baseline -- or cannot be compared with it
        # -- must fail the job that ran it. It always exited 0, so a CI gate on
        # an evaluation never fired.
        if options.update_baseline:
            return 0
        return 1 if _verdict['status'] in ('worse', 'not_comparable') else 0

    @staticmethod
    def _selfcheck(options) -> int:
        from ipandora.core.eval import selfcheck, spec
        _spec = spec.load(options.spec)
        _data = _spec.dataset.split(options.split)
        _problems = selfcheck(_data, _spec.grade)
        if not _problems:
            print('  OK  {} 道题的参考解全部判过'.format(len(_data.tasks)))
            return 0
        for _p in _problems:
            print('  {}  {}  {}'.format('WARN' if _p.get('kind') == 'missing' else 'FAIL',
                                        _p['task_id'], _p['problem']))
            for _c in _p['checks']:
                print('        {}：{}'.format(_c['name'], _c['expr']))
        _counts = {_k: sum(1 for _p in _problems if _p.get('kind') == _k) for _k, _ in SELFCHECK_KINDS}
        print('  {} 道题中：{}'.format(len(_data.tasks), '；'.join(
            '{} 道{}'.format(_counts[_k], _t) for _k, _t in SELFCHECK_KINDS if _counts[_k])))
        # Only a reference that fails, or a grader that cannot judge it, is a
        # broken task. A task without a reference is reported, not failed:
        # there is nothing wrong to find in it.
        return 1 if _counts['fails'] or _counts['grader'] else 0

    @staticmethod
    def _samples(options) -> int:
        from ipandora.core.eval import EvalRun, annotate
        _run = EvalRun.load(options.run)
        _rows = annotate.samples(_run, limit=options.limit, seed=options.seed,
                                 include_deterministic=options.all_checks)
        annotate.export(_rows, options.out)
        print('  导出 {} 行到 {}；在 human 一栏填 true / false / null'.format(len(_rows), options.out))
        return 0

    @staticmethod
    def _agreement(options) -> int:
        from ipandora.core.eval import annotate
        _r = annotate.agreement(annotate.read(options.labels), a=options.a, b=options.b)
        if not _r['n']:
            print('  没有双方都给出结论的行（{} 行有一方未定）'.format(_r['undecided']))
            return 1
        print('  {} 行 · 一致率 {:.1%} · Cohen kappa {:.2f} · {} 行有一方未定'.format(
            _r['n'], _r['agreement'], _r['kappa'], _r['undecided']))
        return 0

    @property
    def help(self):
        return 'agent evaluation: run a spec, self-check references, label samples'

    @property
    def sub_command_name(self):
        return 'eval'

    def add_arguments(self):
        _sub = self.parser.add_subparsers(dest='eval_action')

        _run = _sub.add_parser('run', help='run every task k times, grade, compare with the baseline')
        _run.add_argument('spec', help='the spec file: defines DATASET, agent and grade')
        _run.add_argument('-k', '--trials', type=int, default=1, help='trials per task')
        _run.add_argument('--split', choices=['dev', 'test'], default=None,
                          help='run one split only. Tune on dev; conclude on test')
        _run.add_argument('-w', '--workers', type=int, default=1, help='trials run at once (threads)')
        _run.add_argument('-o', '--out', default=None,
                          help='where report.html and report.json go. Default: the report archive')
        _run.add_argument('--title', default=None, help='report title')
        _run.add_argument('--baseline', default=None, metavar='PATH',
                          help='evaluation baseline. Default: conf/eval_baseline.json when it exists')
        _run.add_argument('--no-baseline', action='store_true', help='compare with nothing')
        _run.add_argument('--update-baseline', action='store_true',
                          help='write this run as the baseline. Commit it; review its diff')
        _run.add_argument('--noise', type=float, default=0.0, metavar='RATE',
                          help='infrastructure noise as a rate (0.021 for ±2.1 points): a '
                               'difference smaller than this is never called better or worse')
        _run.add_argument('--partial', action='store_true',
                          help='compare each task\'s partial score (the weighted share of its '
                               'checks that held) instead of whether it succeeded')

        _check = _sub.add_parser('selfcheck', help='grade every reference solution; exit 1 if any fails')
        _check.add_argument('spec')
        _check.add_argument('--split', choices=['dev', 'test'], default=None)

        _samples = _sub.add_parser('samples', help='export judge verdicts for people to label (JSONL)')
        _samples.add_argument('run', help='report.json of an evaluation run')
        _samples.add_argument('-o', '--out', required=True)
        _samples.add_argument('-n', '--limit', type=int, default=None, help='sample this many rows')
        _samples.add_argument('--seed', type=int, default=0)
        _samples.add_argument('--all-checks', action='store_true',
                              help='include deterministic checks, to see whether people agree on a task')

        _agree = _sub.add_parser('agreement', help='agreement and Cohen kappa between two raters')
        _agree.add_argument('labels', help='the labelled JSONL')
        _agree.add_argument('--a', default='judge', help='first rater column')
        _agree.add_argument('--b', default='human', help='second rater column')

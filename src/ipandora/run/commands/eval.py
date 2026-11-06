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
            if _action == 'inspect':
                sys.exit(self._inspect(options))
            if _action == 'selfcheck':
                sys.exit(self._selfcheck(options))
            if _action == 'samples':
                sys.exit(self._samples(options))
            if _action == 'agreement':
                sys.exit(self._agreement(options))
        except (ValueError, OSError, ImportError) as exc:
            # a missing file, bad YAML or JSON: a message, not a traceback
            print('  ERROR  {}'.format(exc), file=sys.stderr)
            sys.exit(2)
        self.parser.print_help()
        sys.exit(2)

    @staticmethod
    def _run(options) -> int:
        from ipandora.core.eval import evaluate, spec
        _spec = spec.load(options.spec)
        _run = evaluate(_spec.dataset, _spec.agent, _spec.grade, trials=options.trials,
                        split=options.split, workers=options.workers, manifest=_spec.manifest)
        return Command._conclude(_run, options)

    @staticmethod
    def _inspect(options) -> int:
        from ipandora.core.eval import inspect_log
        _threshold = {}
        for _item in options.threshold or ():
            _name, _sep, _value = _item.rpartition('=')
            try:
                _threshold[_name if _sep else '*'] = float(_value)
            except ValueError:
                raise ValueError('--threshold {!r}: a number, or SCORER=NUMBER'.format(_item)) from None
        _run = inspect_log.read(options.logs, threshold=_threshold or 1.0, judges=options.judge or ())
        _unfinished = inspect_log.incomplete(_run)
        if _unfinished and options.update_baseline:
            # a run that stopped part way would become the bar every later run is held to
            raise ValueError('not writing a baseline from an unfinished run: {}'.format(
                ', '.join('{} ({})'.format(_k, _v) for _k, _v in sorted(_unfinished.items()))))
        _code = Command._conclude(_run, options)
        if _unfinished:
            # the samples that never ran are missing from the comparison, not
            # failed in it: a cancelled run could read as "indistinguishable"
            print('  未完成的 Inspect 运行：{}；没跑的样本不在比较里，结论不作数'.format(
                '、'.join('{}（{}）'.format(_k, _v) for _k, _v in sorted(_unfinished.items()))))
            return 1
        return _code

    @staticmethod
    def _conclude(_run, options) -> int:
        from ipandora.core.eval import baseline, report, trend
        if options.baseline and not options.no_baseline and not os.path.isfile(options.baseline) \
                and not options.update_baseline:
            # asked for by name: a typo must not turn into "no baseline, all fine"
            raise ValueError('--baseline {}: no such file'.format(options.baseline))
        _path = '' if options.no_baseline else (options.baseline or baseline.default_path())
        _base = baseline.load(_path) if _path else None
        _comparison = baseline.compare(_run, _base, noise=options.noise,
                                       partial=options.partial) if _base else None

        _gate_name = getattr(options, 'fail_on_regression', None) or 'overall'
        _reasons = baseline.regressions(_comparison, _gate_name) if _comparison else []
        from ipandora.core.report.history import reports_dir
        _earlier = [_r for _r in trend.history(dataset=_run.manifest.dataset, split=_run.manifest.split)
                    if _r.run_id != _run.run_id]
        _saturation = trend.saturation(_earlier + [_run])
        _gate = {'gate': _gate_name, 'reasons': _reasons, 'saturation': _saturation,
                 'saturation_sentence': trend.sentence(_saturation)}
        _out = options.out or os.path.join(reports_dir(), _run.run_id)
        _paths = report.write(_run, _out, _comparison, title=options.title, gate=_gate)

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
        for _reason in _reasons:
            print('  门禁不通过  {}'.format(_reason))
        if _comparison and _comparison.get('broken') and _gate_name != 'task':
            print('  {} 道题以前全过、现在全挂：{}（--fail-on-regression task 时拦下）'.format(
                len(_comparison['broken']), '、'.join(_comparison['broken'][:5])))
        if _gate['saturation_sentence']:
            print('  {}'.format(_gate['saturation_sentence']))
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
        return 1 if _reasons else 0

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
        _common(_run)

        _inspect = _sub.add_parser('inspect', help='read Inspect logs as an evaluation run: report, '
                                                   'baseline, gate (needs the inspect extra)')
        _inspect.add_argument('logs', nargs='+', help='.eval / .json log files, or a directory of them')
        _inspect.add_argument('--threshold', action='append', metavar='[SCORER=]VALUE',
                              help='the value a score must reach to pass, on Inspect\'s scale '
                                   '(CORRECT = 1, PARTIAL = 0.5). Default 1. Repeat per scorer')
        _inspect.add_argument('--judge', action='append', metavar='SCORER',
                              help='a scorer that asks a model: shown, counted only once calibrated. '
                                   'model_graded_qa and model_graded_fact always are')
        _common(_inspect)

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


def _common(parser):
    """Report, baseline and comparison options: `eval run` and `eval inspect` end the same way."""
    parser.add_argument('-o', '--out', default=None,
                        help='where report.html and report.json go. Default: the report archive')
    parser.add_argument('--title', default=None, help='report title')
    parser.add_argument('--baseline', default=None, metavar='PATH',
                        help='evaluation baseline. Default: conf/eval_baseline.json when it exists')
    parser.add_argument('--no-baseline', action='store_true', help='compare with nothing')
    parser.add_argument('--update-baseline', action='store_true',
                        help='write this run as the baseline. Commit it; review its diff')
    parser.add_argument('--noise', type=float, default=0.0, metavar='RATE',
                        help='infrastructure noise as a rate (0.021 for ±2.1 points): a '
                             'difference smaller than this is never called better or worse')
    parser.add_argument('--fail-on-regression', choices=['overall', 'tag', 'task'], default='overall',
                        help='what fails the run: overall -- the overall verdict is worse; tag -- also '
                             'any tag value worse (corrected for the number of groups); task -- also any '
                             'task that always succeeded and now always fails. Not comparable always fails')
    parser.add_argument('--partial', action='store_true',
                        help='compare each task\'s partial score (the weighted share of its '
                             'checks that held) instead of whether it succeeded')

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_eval.py
@Time  : 2026-11-05

E0, the evaluation groundwork: datasets, trials and their scoring, the
statistics, the baseline, the human channel, the report and the command.
"""
import json
import os
import random
import subprocess
import sys

import pytest

from ipandora.core.assertion import Check, that
from ipandora.core.eval import (AgentResult, EvalRun, Graded, Manifest, Trial, annotate, baseline,
                                dataset, evaluate, report, selfcheck, stats)
from ipandora.core.eval.trial import GRADED, INFRA, NO_VERDICT

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, '..', '..', 'examples', 'eval', 'spec.py')


def tasks(*specs):
    return dataset.from_records([dict({'id': _id, 'expected': _e}, **_kw)
                                 for _id, _e, _kw in specs], 'toy')


def exact(task, result):
    return [that(result.output, 'answer') == task.expected]


# --------------------------------------------------------------------------
# datasets
# --------------------------------------------------------------------------

class TestDataset:

    def test_yaml_and_jsonl(self, tmp_path):
        _yaml = tmp_path / 'd.yaml'
        _yaml.write_text('name: demo\nversion: 2\ntasks:\n  - id: a\n    input: x\n    tags: {kind: k}\n',
                         encoding='utf-8')
        _d = dataset.load(str(_yaml))
        assert (_d.name, _d.version, _d.tasks[0].tags) == ('demo', '2', {'kind': 'k'})
        _jsonl = tmp_path / 'd.jsonl'
        _jsonl.write_text('{"id": "a"}\n\n{"id": "b", "split": "dev"}\n', encoding='utf-8')
        _d = dataset.load(str(_jsonl))
        assert [_t.id for _t in _d.tasks] == ['a', 'b'] and _d.name == 'd'
        assert [_t.id for _t in _d.split('dev').tasks] == ['b']

    @pytest.mark.parametrize('records,message', [
        ([{'id': 'a', 'refrence': 'x'}], 'unknown field'),
        ([{'input': 'no id'}], 'needs an id'),
        ([{'id': 'a'}, {'id': 'a'}], 'duplicate task id'),
        ([{'id': 'a', 'polarity': 'maybe'}], 'polarity'),
        ([{'id': 'a', 'split': 'train'}], 'split'),
        ([{'id': 'a', 'tags': ['x']}], 'tags must be a mapping'),
    ])
    def test_mistakes_are_named(self, records, message):
        with pytest.raises(ValueError, match=message):
            dataset.from_records(records, 'bad')

    def test_a_bad_jsonl_line_is_located(self, tmp_path):
        _f = tmp_path / 'd.jsonl'
        _f.write_text('{"id": "a"}\n{oops\n', encoding='utf-8')
        with pytest.raises(ValueError, match='d.jsonl:2'):
            dataset.load(str(_f))

    def test_the_fingerprint_follows_content_not_order(self, tmp_path):
        (tmp_path / 'ref.txt').write_text('v1', encoding='utf-8')
        _path = str(tmp_path / 'd.yaml')
        _a = dataset.from_records([{'id': 'x', 'reference': 'ref.txt'}, {'id': 'y'}], 'd', path=_path)
        _b = dataset.from_records([{'id': 'y'}, {'id': 'x', 'reference': 'ref.txt'}], 'd', path=_path)
        assert _a.fingerprint == _b.fingerprint
        (tmp_path / 'ref.txt').write_text('v2', encoding='utf-8')
        assert _a.fingerprint != _b.fingerprint or _a.fingerprint != dataset.from_records(
            [{'id': 'y'}], 'd', path=_path).fingerprint
        _before = _b.fingerprint
        (tmp_path / 'ref.txt').write_text('v3', encoding='utf-8')
        assert _b.fingerprint != _before

    def test_a_reference_cannot_reach_outside_the_dataset(self, tmp_path):
        (tmp_path / 'secret.txt').write_text('no', encoding='utf-8')
        (tmp_path / 'data').mkdir()
        # refused when the dataset is read (CR1: it used to become the inline
        # text '../secret.txt'); either way the file is never read
        with pytest.raises(ValueError, match='outside its directory'):
            dataset.from_records([{'id': 'x', 'reference': '../secret.txt'}], 'd',
                                 path=str(tmp_path / 'data' / 'd.yaml'))

    def test_an_unknown_split_is_refused(self):
        with pytest.raises(ValueError, match='unknown split'):
            tasks(('a', 1, {})).split('train')


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------

class TestStats:

    def test_wilson(self):
        _lo, _hi = stats.wilson(136, 210)
        assert (round(_lo, 3), round(_hi, 3)) == (0.581, 0.709)
        assert stats.wilson(0, 0) == (0.0, 1.0)
        assert stats.wilson(5, 5)[1] == 1.0 and stats.wilson(0, 5)[0] == 0.0

    def test_pass_at_k_and_pass_hat_k(self):
        assert stats.pass_at_k(5, 2, 2) == pytest.approx(1 - 3 / 10)
        assert stats.pass_hat_k(5, 2, 2) == pytest.approx(1 / 10)
        assert stats.pass_at_k(5, 4, 2) == 1.0
        assert stats.pass_hat_k(5, 5, 5) == 1.0 and stats.pass_hat_k(5, 4, 5) == 0.0
        assert stats.pass_at_k(3, 1, 5) is None and stats.pass_hat_k(3, 1, 0) is None

    def test_mcnemar(self):
        assert stats.mcnemar_exact(10, 2) == pytest.approx(0.03857421875)
        assert stats.mcnemar_exact(0, 0) == 1.0
        assert stats.mcnemar_exact(3, 3) == 1.0

    def test_binary_single_trials_use_mcnemar(self):
        _base = {str(_i): [1.0] for _i in range(30)}
        _now = {str(_i): [0.0 if _i < 10 else 1.0] for _i in range(30)}
        _out = stats.compare(_base, _now)
        assert (_out['test'], _out['verdict'], _out['worse'], _out['better']) == (
            'mcnemar', stats.WORSE, 10, 0)

    def test_noise_keeps_a_small_difference_indistinguishable(self):
        _base = {str(_i): [1.0] for _i in range(400)}
        _now = {str(_i): [0.0 if _i < 12 else 1.0] for _i in range(400)}
        assert stats.compare(_base, _now)['verdict'] == stats.WORSE
        assert stats.compare(_base, _now, noise=0.05)['verdict'] == stats.INDISTINGUISHABLE

    def test_one_task_with_trials_is_not_a_confident_verdict(self):
        # resampling tasks alone gave a zero-width interval and a "worse" here
        _out = stats.compare({'a': [1.0] * 5}, {'a': [1.0, 0.0, 1.0, 0.0, 1.0]})
        assert _out['verdict'] == stats.INDISTINGUISHABLE and _out['low'] < _out['high']

    def test_many_tasks_with_trials_can_be_worse(self):
        _r = random.Random(1)
        _base = {str(_i): [float(_r.random() < 0.8) for _ in range(5)] for _i in range(300)}
        _now = {str(_i): [float(_r.random() < 0.6) for _ in range(5)] for _i in range(300)}
        _out = stats.compare(_base, _now)
        assert _out['test'] == 'paired_bootstrap' and _out['verdict'] == stats.WORSE
        assert _out['high'] < 0

    def test_it_is_reproducible(self):
        _r = random.Random(2)
        _base = {str(_i): [float(_r.random() < 0.7) for _ in range(3)] for _i in range(50)}
        _now = {str(_i): [float(_r.random() < 0.7) for _ in range(3)] for _i in range(50)}
        assert stats.compare(_base, _now) == stats.compare(_base, _now)

    def test_the_binomial_shortcut_matches_resampling(self):
        _draw = stats._sampler([1.0, 1.0, 1.0, 0.0, 0.0])
        _rng = random.Random(3)
        _mean = sum(_draw(_rng) for _ in range(20000)) / 20000
        assert _mean == pytest.approx(0.6, abs=0.01)
        _partial = stats._sampler([0.5, 1.0])
        assert {_partial(_rng) for _ in range(200)} <= {0.5, 0.75, 1.0}

    def test_the_edges_of_k(self):
        assert stats.pass_at_k(5, 2, 1) == pytest.approx(0.4)
        assert stats.pass_hat_k(5, 2, 1) == pytest.approx(0.4)
        assert stats.pass_at_k(5, 2, 3) == pytest.approx(0.9)    # n - c == k: still the formula
        assert stats.pass_at_k(5, 2, 4) == 1.0                   # n - c < k: certain
        assert stats.pass_hat_k(5, 2, 5) == 0.0
        assert stats.pass_at_k(5, 2, 0) is None and stats.pass_at_k(5, 2, 6) is None
        _lo, _hi = stats.wilson(1, 1)
        assert _hi == 1.0 and _lo == pytest.approx(0.2065, abs=1e-4)

    def test_interval_quantiles(self):
        assert stats.paired_bootstrap([-1.0, 1.0] * 50, resamples=4000) == (0.0, -0.2, 0.2)
        assert stats.paired_bootstrap([-1.0, 1.0] * 50, resamples=4000, level=0.9) == (0.0, -0.16, 0.16)
        assert stats.paired_bootstrap([0.25] * 10) == (0.25, 0.25, 0.25)
        assert stats.paired_bootstrap([]) == (0.0, 0.0, 0.0)

    def test_hierarchical_interval(self):
        # now ~ Binomial(5, 0.6)/5: its 2.5% quantile is 1/5 and its 97.5% is 5/5
        assert stats.hierarchical_bootstrap({'a': [1.0] * 5}, {'a': [1.0, 0.0, 1.0, 0.0, 1.0]},
                                            ['a']) == (-0.8, 0.0)
        assert stats.hierarchical_bootstrap({'a': [1.0] * 5, 'b': [1.0] * 5},
                                            {'a': [0.0] * 5, 'b': [0.0] * 5}, ['a', 'b']) == (-1.0, -1.0)
        assert stats.hierarchical_bootstrap({}, {}, []) == (0.0, 0.0)

    def test_counts_and_the_empty_answer(self):
        _out = stats.compare({'a': [1.0], 'b': [0.0], 'c': [1.0], 'd': []},
                             {'a': [0.0], 'b': [1.0], 'c': [1.0], 'd': [1.0]})
        assert (_out['tasks'], _out['worse'], _out['better'], _out['same']) == (3, 1, 1, 1)
        assert (_out['difference'], _out['noise']) == (0.0, 0.0)
        assert stats.compare({}, {}) == {
            'tasks': 0, 'worse': 0, 'better': 0, 'same': 0, 'noise': 0.0, 'only_in_base': [],
            'only_in_now': [], 'verdict': 'indistinguishable', 'difference': 0.0, 'low': 0.0,
            'high': 0.0, 'test': 'none', 'p': 1.0}

    def test_partial_scores_are_resampled_as_they_are(self):
        _out = stats.compare({'a': [0.5, 1.0], 'b': [0.5, 0.5]}, {'a': [0.25, 0.75], 'b': [0.5, 0.5]})
        assert _out['test'] == 'paired_bootstrap'
        assert _out['difference'] == pytest.approx(-0.125)

    def test_tasks_on_one_side_only_are_reported_not_compared(self):
        _out = stats.compare({'a': [1.0], 'b': [1.0]}, {'a': [1.0], 'c': [0.0]})
        assert (_out['tasks'], _out['only_in_base'], _out['only_in_now']) == (1, ['b'], ['c'])
        assert stats.compare({}, {})['verdict'] == stats.INDISTINGUISHABLE


# --------------------------------------------------------------------------
# trials
# --------------------------------------------------------------------------

def trial(*checks, status=GRADED):
    return Trial(task_id='t', index=0, status=status,
                 checks=[Trial.check_dict(_c if isinstance(_c, Graded) else Graded(_c)) for _c in checks])


class TestTrialScoring:

    def test_success_needs_every_required_check(self):
        assert trial(Check('a', True), Check('b', True)).success is True
        assert trial(Check('a', True), Check('b', False)).success is False
        assert trial(Check('a', True), Graded(Check('b', False), required=False)).success is True

    def test_the_score_is_weighted(self):
        assert trial(Graded(Check('a', True), weight=3), Check('b', False)).score == 0.75

    def test_a_model_judge_and_an_uncertain_check_count_for_nothing(self):
        _t = trial(Check('a', True), Check('plan', False, src='llm_judge'),
                   Graded(Check('style', False), uncertain=True))
        assert (_t.success, _t.score, len(_t.judge_checks)) == (True, 1.0, 1)

    def test_nothing_decided_is_no_verdict(self):
        assert trial(Check('plan', True, src='llm_judge')).success is None
        assert trial().score is None
        assert trial(Check('a', True), status=INFRA).success is None


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

class TestEvaluate:

    def test_trials_outcomes_and_manifest(self):
        _data = tasks(('a', 1, {'tags': {'kind': 'x'}}), ('b', 2, {'tags': {'kind': 'y'}}))
        _run = evaluate(_data, agent=lambda t: AgentResult(output=1, cost={'usd': 0.5}),
                        grade=exact, trials=3, manifest={'harness': 'h', 'model': 'm'})
        assert len(_run.trials) == 6
        assert _run.outcomes() == {'a': [1.0] * 3, 'b': [0.0] * 3}
        _s = _run.summary()
        assert (_s['successes'], _s['decided'], _s['k'], _s['tasks_all_k']) == (3, 6, 3, 1)
        assert _s['pass_hat_k'] == 0.5 and _s['cost'] == {'usd': 3.0}
        assert _s['by_category'] == {'agent': 3}
        _m = _run.manifest
        assert (_m.harness, _m.model, _m.trials, _m.dataset) == ('h', 'm', 3, 'toy')
        assert len(_m.dataset_hash) == 64 and _m.python

    def test_an_agent_that_raises_is_infrastructure_not_a_failure(self):
        def _agent(task):
            raise TimeoutError('sandbox did not start')
        _run = evaluate(tasks(('a', 1, {})), agent=_agent, grade=exact, trials=2)
        assert {_t.status for _t in _run.trials} == {INFRA}
        assert 'TimeoutError: sandbox did not start' in _run.trials[0].error
        _s = _run.summary()
        assert (_s['infra'], _s['decided'], _s['success_rate']) == (2, 0, None)

    def test_a_grader_that_raises_is_the_graders_problem(self):
        def _grade(task, result):
            raise KeyError('expected')
        _run = evaluate(tasks(('a', 1, {'reference': 1})), agent=lambda t: 1, grade=_grade,
                        check_references=False)
        assert (_run.trials[0].status, _run.trials[0].category) == (NO_VERDICT, 'grader')

    def test_a_task_whose_reference_fails_is_the_tasks_problem(self):
        _data = tasks(('ok', 1, {'reference': 1}), ('broken', 2, {'reference': 3}))
        _run = evaluate(_data, agent=lambda t: 0, grade=exact)
        assert [_p['task_id'] for _p in _run.selfcheck] == ['broken']
        assert {_t.task_id: _t.category for _t in _run.trials} == {'ok': 'agent', 'broken': 'task'}

    def test_workers_do_not_change_the_result(self):
        _data = tasks(*[(str(_i), _i % 2, {}) for _i in range(20)])
        _serial = evaluate(_data, agent=lambda t: 1, grade=exact, trials=2)
        _parallel = evaluate(_data, agent=lambda t: 1, grade=exact, trials=2, workers=8)
        assert [(_t.task_id, _t.index, _t.success) for _t in _serial.trials] == \
               [(_t.task_id, _t.index, _t.success) for _t in _parallel.trials]

    def test_a_split_and_its_errors(self):
        _data = tasks(('a', 1, {'split': 'dev'}), ('b', 1, {}))
        assert [_t['id'] for _t in evaluate(_data, lambda t: 1, exact, split='dev').tasks] == ['a']
        with pytest.raises(ValueError, match='trials'):
            evaluate(_data, lambda t: 1, exact, trials=0)
        with pytest.raises(ValueError, match='no tasks'):
            evaluate(tasks(('a', 1, {'split': 'dev'})), lambda t: 1, exact, split='test')

    def test_it_round_trips(self, tmp_path):
        _run = evaluate(tasks(('a', 1, {})), agent=lambda t: AgentResult(
            output=1, trajectory=[{'t': 0.1, 'kind': 'tool', 'name': 'grep', 'text': 'x'}]), grade=exact)
        _back = EvalRun.load(_run.save(str(tmp_path / 'run.json')))
        assert _back.summary() == _run.summary() and _back.trials[0].trajectory == _run.trials[0].trajectory
        with pytest.raises(ValueError, match='not an IntelliPandora evaluation run'):
            EvalRun.from_dict({'cases': []})


class TestSelfcheck:

    def test_problems_are_named(self):
        _data = tasks(('ok', 1, {'reference': 1}), ('wrong', 1, {'reference': 2}), ('none', 1, {}))
        _p = {_x['task_id']: _x['problem'] for _x in selfcheck(_data, exact)}
        assert _p == {'wrong': '参考解判不过', 'none': '没有参考解'}

    def test_a_reference_file_is_read(self, tmp_path):
        (tmp_path / 'ref.txt').write_text('42', encoding='utf-8')
        _data = dataset.from_records([{'id': 'a', 'expected': '42', 'reference': 'ref.txt'}], 'd',
                                     path=str(tmp_path / 'd.yaml'))
        assert selfcheck(_data, exact) == []

    def test_a_grader_that_judges_nothing_on_the_reference(self):
        _data = tasks(('a', 1, {'reference': 1}))
        assert '没有给出任何确定性判定' in selfcheck(
            _data, lambda t, r: [Check('style', True, src='llm_judge')])[0]['problem']


# --------------------------------------------------------------------------
# baseline, comparison, report
# --------------------------------------------------------------------------

def run_with(rates, k=5, seed=0, harness='h'):
    """A run where task i succeeds in round(rate*k) of k trials."""
    _data = tasks(*[(_id, 1, {'tags': {'kind': _kind}}) for _id, (_kind, _) in rates.items()])
    _left = {_id: round(_rate * k) for _id, (_, _rate) in rates.items()}

    def _agent(task):
        _left[task.id] -= 1
        return 1 if _left[task.id] >= 0 else 0
    return evaluate(_data, _agent, exact, trials=k, manifest={'harness': harness})


class TestBaseline:

    def test_save_load_compare(self, tmp_path):
        _rates = {str(_i): ('a' if _i < 40 else 'b', 1.0) for _i in range(80)}
        _base = run_with(_rates)
        _path = baseline.save(str(tmp_path / 'eval_baseline.json'), _base)
        _worse = run_with({_k: (_v[0], 0.2 if _v[0] == 'a' else 1.0) for _k, _v in _rates.items()})
        _out = baseline.compare(_worse, baseline.load(_path))
        assert _out['verdict'] == stats.WORSE and _out['not_comparable'] == []
        _tags = {_r['value']: _r for _r in _out['by_tag']}
        assert _tags['a']['verdict'] == stats.WORSE and _tags['b']['verdict'] == stats.INDISTINGUISHABLE
        assert (_tags['a']['base_rate'], _tags['a']['now_rate']) == (1.0, pytest.approx(0.2))
        assert _out['worst'][0]['base'] == [5, 5] and _out['worst'][0]['now'] == [1, 5]

    def test_a_different_dataset_is_not_comparable(self, tmp_path):
        _a = run_with({'x': ('k', 1.0)})
        _b = run_with({'y': ('k', 1.0)})
        _out = baseline.compare(_b, baseline.build(_a))
        assert any('数据集内容不同' in _r for _r in _out['not_comparable'])
        assert report.verdict(_b, _out)['status'] == 'not_comparable'

    def test_load_refuses_other_files(self, tmp_path):
        _f = tmp_path / 'x.json'
        _f.write_text('{"cases": {}}', encoding='utf-8')
        with pytest.raises(ValueError):
            baseline.load(str(_f))
        assert baseline.load(str(tmp_path / 'none.json')) is None


class TestReport:

    def test_verdicts(self):
        _run = run_with({'a': ('k', 0.6)})
        assert report.verdict(_run, None)['status'] == 'first'
        _out = baseline.compare(_run, baseline.build(_run))
        _v = report.verdict(_run, _out)
        assert _v['status'] == stats.INDISTINGUISHABLE and '+0.0 个百分点' in _v['sentence']

    def test_the_page(self, tmp_path):
        _data = tasks(('a', 1, {'tags': {'kind': 'x'}}))

        def _grade(task, result):
            return [that(result.output, 'answer') == task.expected,
                    Check('计划是否合理', False, src='llm_judge')]
        _run = evaluate(_data, agent=lambda t: AgentResult(
            output=0, trajectory=[{'t': 0.0, 'kind': 'tool', 'name': 'edit', 'text': 'tests/x.py',
                                   'error': '不得修改 tests/'}]), grade=_grade, trials=2)
        _paths = report.write(_run, str(tmp_path / 'out'))
        _html = open(_paths['html'], encoding='utf-8').read()
        assert 'data-verdict="first"' in _html and '没有成功的试验' in _html
        assert '不得修改 tests/' in _html and '模型评委 · 只展示，不计入' in _html
        assert '@media (prefers-color-scheme:dark)' in _html
        _json = json.loads(open(_paths['json'], encoding='utf-8').read())
        assert _json['view'] == 'eval' and _json['kind'] == 'ipandora.eval'
        assert EvalRun.from_dict(_json).summary() == _run.summary()

    def test_output_is_escaped(self, tmp_path):
        _run = evaluate(tasks(('a', 1, {})), agent=lambda t: '<script>alert(1)</script>', grade=exact)
        _html = report.to_html(_run)
        assert '<script>alert(1)' not in _html and '&lt;script&gt;' in _html


# --------------------------------------------------------------------------
# the human channel
# --------------------------------------------------------------------------

class TestAnnotation:

    def run(self):
        def _grade(task, result):
            return [that(result.output, 'a') == 1, Check('语气得体', result.output == 1, src='llm_judge'),
                    Graded(Check('计划', True, src='llm_judge'), uncertain=True)]
        return evaluate(tasks(*[(str(_i), 1, {}) for _i in range(10)]),
                        agent=lambda t: int(t.id) % 2, grade=_grade)

    def test_samples_are_the_judge_checks(self, tmp_path):
        _rows = annotate.samples(self.run())
        assert len(_rows) == 20 and {_r['source'] for _r in _rows} == {'llm_judge'}
        assert {_r['judge'] for _r in _rows if _r['check'] == '计划'} == {None}
        assert len(annotate.samples(self.run(), include_deterministic=True)) == 30
        _some = annotate.samples(self.run(), limit=5, seed=1)
        assert len(_some) == 5 and _some == annotate.samples(self.run(), limit=5, seed=1)
        _path = annotate.export(_rows, str(tmp_path / 's.jsonl'))
        assert annotate.read(_path) == _rows

    def test_agreement_and_kappa(self):
        _same = [{'judge': _x, 'human': _x} for _x in (True, False, True, False)]
        assert annotate.agreement(_same) == {'n': 4, 'undecided': 0, 'agreement': 1.0, 'kappa': 1.0}
        # a judge that always says yes, on a set that is 90% yes: 90% raw, kappa 0
        _lazy = [{'judge': True, 'human': _i < 9} for _i in range(10)]
        _r = annotate.agreement(_lazy)
        assert _r['agreement'] == pytest.approx(0.9) and _r['kappa'] == pytest.approx(0.0)
        assert annotate.agreement([{'judge': None, 'human': True}])['n'] == 0


# --------------------------------------------------------------------------
# the spec and the command
# --------------------------------------------------------------------------

class TestSpec:

    def test_the_example_loads(self):
        from ipandora.core.eval import spec
        _s = spec.load(EXAMPLE)
        assert _s.dataset.name == 'order-extraction' and len(_s.dataset.tasks) == 4
        assert selfcheck(_s.dataset, _s.grade) == []

    @pytest.mark.parametrize('body,message', [
        ('agent = 1\n', 'must define DATASET'),
        ('DATASET = 3\ndef agent(t): pass\ndef grade(t, r): pass\n', 'path or a Dataset'),
        ('DATASET = "missing.yaml"\nagent = 1\ndef grade(t, r): pass\n', 'No such file'),
    ])
    def test_mistakes(self, tmp_path, body, message):
        from ipandora.core.eval import spec
        _f = tmp_path / 'spec.py'
        _f.write_text(body, encoding='utf-8')
        with pytest.raises((ValueError, OSError), match=message):
            spec.load(str(_f))


def ipandora(*args):
    return subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval'] + list(args),
                          capture_output=True, text=True, timeout=180)


class TestTheCommand:

    def test_selfcheck(self, tmp_path):
        _done = ipandora('selfcheck', EXAMPLE)
        assert _done.returncode == 0 and '4 道题的参考解全部判过' in _done.stdout
        _bad = tmp_path / 'spec.py'
        _bad.write_text(open(EXAMPLE, encoding='utf-8').read().replace(
            "DATASET = 'orders.yaml'", "DATASET = {!r}".format(
                os.path.join(os.path.dirname(EXAMPLE), 'orders.yaml'))).replace(
            "task.expected['order']", "'nope'"), encoding='utf-8')
        _done = ipandora('selfcheck', str(_bad))
        assert _done.returncode == 1 and '参考解判不过' in _done.stdout

    def test_run_baseline_samples_agreement(self, tmp_path):
        _base = str(tmp_path / 'eval_baseline.json')
        _done = ipandora('run', EXAMPLE, '-k', '5', '-o', str(tmp_path / 'r1'),
                         '--baseline', _base, '--update-baseline')
        assert _done.returncode == 0, _done.stderr
        assert '没有基线' in _done.stdout and os.path.isfile(_base)
        _done = ipandora('run', EXAMPLE, '-k', '5', '-o', str(tmp_path / 'r2'), '--baseline', _base)
        assert '和基线无法区分' in _done.stdout
        _report = json.loads((tmp_path / 'r2' / 'report.json').read_text(encoding='utf-8'))
        assert _report['summary']['trials'] == 20 and _report['comparison']['tasks'] == 4
        _done = ipandora('samples', str(tmp_path / 'r2' / 'report.json'), '-o',
                         str(tmp_path / 's.jsonl'), '--all-checks')
        assert _done.returncode == 0 and '导出 40 行' in _done.stdout
        _rows = [json.loads(_l) for _l in open(tmp_path / 's.jsonl', encoding='utf-8')]
        with open(tmp_path / 'labelled.jsonl', 'w', encoding='utf-8') as fh:
            for _r in _rows:
                fh.write(json.dumps(dict(_r, human=_r['judge'])) + '\n')
        _done = ipandora('agreement', str(tmp_path / 'labelled.jsonl'))
        assert _done.returncode == 0 and '一致率 100.0%' in _done.stdout

    def test_a_bad_spec_is_exit_2(self, tmp_path):
        _done = ipandora('run', str(tmp_path / 'nope.py'))
        assert _done.returncode == 2 and 'no such spec file' in _done.stderr

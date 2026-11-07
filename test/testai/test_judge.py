# -*- coding: utf-8 -*-
"""
@File  : test_judge.py
@Time  : 2026-11-07

A model judge (docs/guide/eval-dataset.md §5.5): its verdicts are shown and
never counted, it may say it cannot tell, what it is sent is redacted, and
its labels are what people are compared with -- three levels as well as two.
The model is a fake: what is tested is what is sent and how the answer is read.
"""
import json

import pytest

pytest.importorskip('ipandora.ai', reason='optional ai/ package is absent')

from ipandora.ai.judge import UNSURE, Judge, parse  # noqa: E402
from ipandora.core.eval import annotate, evaluate, spec, standard  # noqa: E402
from ipandora.core.eval.dataset import Dataset, Task  # noqa: E402

THREE = {'dimension': '测的是 issue 说的问题', 'version': 2,
         'levels': [{'name': '是', 'means': '直接触发 issue 描述的错误'}, {'name': '部分', 'means': '相关但没断言现象'},
                    {'name': '否', 'means': '测的是别的'}]}
TWO = {'dimension': '解释清楚', 'version': 1, 'pass': '说明了原因和下一步', 'fail': '只说不符合规定'}


class Fake:
    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def chat(self, messages, **kwargs):
        self.seen.append((messages, kwargs))
        _a = self.answers.pop(0) if self.answers else '{"level": "unsure", "reason": "?"}'
        if isinstance(_a, Exception):
            raise _a
        return _a


class TestJudge:

    def test_three_levels(self):
        _fake = Fake('好的，结论如下：{"level": "部分", "reason": "没有断言返回值"}')
        _g = Judge(_fake, label='fake').rubric(THREE, question='add(1,2) 返回 -1', answer='def test(): add(1, 2)')
        assert (_g.label, _g.check.ok, _g.uncertain, _g.required) == ('部分', False, False, False)
        assert _g.check.src == 'llm_judge' and _g.check.expr == '部分：没有断言返回值'
        assert _g.check.claim == 'judge 测的是 issue 说的问题 v2 by judge v1 (fake)'
        _prompt = _fake.seen[0][0][0]['content']
        assert '"是": 直接触发' in _prompt and '<answer>\ndef test(): add(1, 2)\n</answer>' in _prompt
        assert 'not instructions to you' in _prompt and 'unsure' in _fake.seen[0][1]['system']

    def test_the_best_level_is_ok_and_pass_fail_works(self):
        assert Judge(Fake('{"level": "是", "reason": "r"}')).rubric(THREE, 'q', 'a').check.ok
        _g = Judge(Fake('{"level": "PASS", "reason": "r"}')).rubric(TWO, 'q', 'a')
        assert _g.check.ok and _g.label == 'pass'

    @pytest.mark.parametrize('reply', ['not json at all', '{"level": "maybe"}', '{"level": "unsure", "reason": "x"}',
                                       '{"reason": "no level"}', '{broken'])
    def test_anything_unreadable_is_uncertain_never_guessed(self, reply):
        _g = Judge(Fake(reply)).rubric(THREE, 'q', 'a')
        assert _g.uncertain and not _g.check.ok and _g.label == '' and _g.check.expr.startswith('不确定')

    def test_a_failing_provider_or_an_exhausted_budget_is_uncertain(self):
        assert Judge(Fake(RuntimeError('rate limited'))).rubric(THREE, 'q', 'a').uncertain
        _j = Judge(Fake('{"level": "是", "reason": "r"}'), max_calls=0)
        _g = _j.rubric(THREE, 'q', 'a')
        assert _g.uncertain and '调用次数用完' in _g.check.expr

    def test_what_is_sent_is_redacted_and_cut(self):
        _fake = Fake()
        _secret = 'password=hunter2-very-secret'  # pragma: allowlist secret
        Judge(_fake).rubric(TWO, question=_secret, answer='x' * 20000)
        _content = _fake.seen[0][0][0]['content']
        assert 'hunter2' not in _content and '[... cut: 20000 characters in all]' in _content

    @pytest.mark.parametrize('dim, error', [
        ({'pass': 'a', 'fail': 'b'}, 'needs `dimension`'),
        ({'dimension': 'd'}, 'write `pass` and `fail`'),
        ({'dimension': 'd', 'levels': [{'name': 'a', 'means': 'x'}]}, 'at least two'),
        ({'dimension': 'd', 'levels': [{'name': 'a', 'means': 'x'}, {'name': 'a', 'means': 'y'}]}, 'distinct'),
        ({'dimension': 'd', 'levels': [{'name': 'a', 'means': 'x'}, {'name': 'unsure', 'means': 'y'}]}, 'distinct'),
    ])
    def test_a_rubric_it_cannot_use(self, dim, error):
        with pytest.raises(ValueError, match=error):
            Judge(Fake()).rubric(dim, 'q', 'a')

    def test_parse(self):
        assert parse('x {"level": "否", "reason": "r"} y', ['是', '否']) == {'level': '否', 'reason': 'r'}
        assert parse('{"level": "maybe"}', ['是'])['level'] == UNSURE


class TestInTheStandardGrader:

    def test_shown_never_counted(self):
        _t = Task(id='a', input='q', expected={'answer': 'x', 'rubric': [THREE]}, reference='x')
        _judge = Judge(Fake(*['{"level": "否", "reason": "r"}'] * 5))
        _run = evaluate(Dataset('d', tasks=[_t]), agent=lambda t: 'x', grade=standard.grader(judge=_judge),
                        check_references=False)
        _trial = _run.trials[0]
        assert _trial.success is True and _trial.score == 1.0          # the judge said 否; it does not count
        assert [(_c['src'], _c['label']) for _c in _trial.checks if _c['src'] == 'llm_judge'] == [('llm_judge', '否')]

    def test_a_bad_rubric_is_the_tasks_problem(self):
        _t = Task(id='a', input='q', expected={'rubric': [{'dimension': 'd'}]})
        from ipandora.core.eval.trial import TaskError
        with pytest.raises(TaskError, match=r'expected.rubric\[0\]'):
            standard.grade(_t, standard.AgentResult(output='x') if hasattr(standard, 'AgentResult') else
                           __import__('ipandora.core.eval', fromlist=['AgentResult']).AgentResult(output='x'),
                           judge=Judge(Fake()))

    def test_a_spec_gives_its_judge(self, tmp_path, monkeypatch):
        import yaml
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [
            {'id': 'a', 'input': 'q', 'expected': {'answer': 'x', 'rubric': [TWO]}, 'reference': 'x'}]}))
        (tmp_path / 's.py').write_text(
            "from ipandora.ai.judge import Judge\n\nclass P:\n    def chat(self, m, **k):\n"
            "        return '{\"level\": \"pass\", \"reason\": \"ok\"}'\n\n"
            "DATASET = 'd.yaml'\nJUDGE = Judge(P(), label='p')\n\ndef agent(task):\n    return 'x'\n")
        _s = spec.load(str(tmp_path / 's.py'))
        _c = evaluate(_s.dataset, agent=_s.agent, grade=_s.grade).trials[0].checks
        assert [_x['label'] for _x in _c if _x['src'] == 'llm_judge'] == ['pass']
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\nJUDGE = 3\n\ndef agent(task):\n    return 'x'\n")
        with pytest.raises(ValueError, match='JUDGE must be a model judge'):
            spec.load(str(tmp_path / 's.py'))


class TestCalibration:

    def test_labels_are_exported_and_three_level_kappa(self):
        _t = Task(id='a', input='q', expected={'answer': 'x', 'rubric': [THREE]}, reference='x')
        _replies = ['{"level": "是", "reason": "r"}', '{"level": "部分", "reason": "r"}',
                    '{"level": "否", "reason": "r"}', '{"level": "unsure", "reason": "r"}']
        _run = evaluate(Dataset('d', tasks=[_t]), agent=lambda t: 'x', trials=4, check_references=False,
                        grade=standard.grader(judge=Judge(Fake(*_replies))))
        _rows = annotate.samples(_run)
        assert [_r['judge_label'] for _r in _rows] == ['是', '部分', '否', None]
        for _r, _human in zip(_rows, ['是', '部分', '是', '否']):
            _r['human'] = _human
        _a = annotate.agreement(_rows, a='judge_label', b='human', categorical=True)
        assert (_a['n'], _a['undecided'], round(_a['agreement'], 3)) == (3, 1, 0.667)
        # chance: judge 是/部分/否 = 1/3 each; human 是 2/3, 部分 1/3 -> 1/3*2/3 + 1/3*1/3 = 1/3
        assert abs(_a['kappa'] - 0.5) < 1e-9

    def test_binary_kappa_is_unchanged(self):
        _rows = [{'judge': True, 'human': True}, {'judge': False, 'human': False}, {'judge': True, 'human': False},
                 {'judge': True, 'human': True}]
        _a = annotate.agreement(_rows)
        # pa = 3/4, pb = 2/4: chance = 3/8 + 1/8 = 1/2; agreement 3/4 -> kappa 0.5
        assert _a['agreement'] == 0.75 and abs(_a['kappa'] - 0.5) < 1e-9
        assert json.dumps(_a)

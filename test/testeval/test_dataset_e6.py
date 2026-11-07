# -*- coding: utf-8 -*-
"""
@File  : test_dataset_e6.py
@Time  : 2026-11-07

E6: a dataset's own description and meta reach the manifest and the report;
`ipandora eval to-inspect` turns a dataset into Inspect samples that the same
grader judges inside Inspect.
"""
import json
import os

import pytest
import yaml

from ipandora.core.eval import dataset, evaluate, report

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write(tmp_path, data, name='d.yaml'):
    (tmp_path / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
    return str(tmp_path / name)


class TestDescriptionAndMeta:

    def test_kept_in_the_manifest_shown_in_the_report_not_in_the_hash(self, tmp_path):
        _tasks = [{'id': 'a', 'input': 'x', 'expected': {'answer': 'x'}, 'reference': 'x'}]
        _d = dataset.load(_write(tmp_path, {'name': 'n', 'description': '退款客服的能力题',
                                            'meta': {'source': 'incident', 'license': 'internal'}, 'tasks': _tasks}))
        assert _d.description == '退款客服的能力题' and _d.meta == {'source': 'incident', 'license': 'internal'}
        assert _d.split('test').description == _d.description and _d.split('test').meta == _d.meta
        _plain = dataset.load(_write(tmp_path, {'name': 'n', 'tasks': _tasks}, 'p.yaml'))
        assert _plain.fingerprint == _d.fingerprint         # where questions came from does not change them
        _run = evaluate(_d, agent=lambda t: 'x', grade=lambda t, r: [])
        assert _run.manifest.dataset_description == '退款客服的能力题'
        assert _run.manifest.dataset_meta == {'source': 'incident', 'license': 'internal'}
        _html = report.to_html(_run)
        assert '退款客服的能力题' in _html and 'license：internal' in _html

    @pytest.mark.parametrize('top, error', [
        ({'desc': 'x'}, 'unknown top-level key'),
        ({'description': ['x']}, 'description is one sentence'),
        ({'meta': 'incident'}, 'meta is a mapping'),
    ])
    def test_mistakes(self, tmp_path, top, error):
        with pytest.raises(ValueError, match=error):
            dataset.load(_write(tmp_path, dict(top, tasks=[{'id': 'a', 'expected': {}}])))


class TestSelfcheckInTheReport:

    def test_a_task_the_grader_cannot_read_is_listed(self):
        from ipandora.core.eval.dataset import Dataset, Task
        from ipandora.core.eval import standard
        _d = Dataset('n', tasks=[Task(id='a', input='x', expected={'answr': 'x'}, reference='x')])
        _run = evaluate(_d, agent=lambda t: 'x', grade=standard.grader())
        assert '1 道题的写法评分器读不了' in report.to_html(_run)


class TestToInspect:

    def _dataset(self, tmp_path):
        (tmp_path / 'refs').mkdir()
        (tmp_path / 'refs' / 'fix.patch').write_text('--- a\n+++ b\n', encoding='utf-8')
        return dataset.load(_write(tmp_path, {'name': 'n', 'tasks': [
            {'id': 'text', 'input': '订单 A1004', 'expected': {'answer': 'A1004'}, 'reference': 'A1004',
             'tags': {'kind': '抽取'}, 'budget': {'seconds': 5}, 'split': 'dev'},
            {'id': 'chat', 'input': {'messages': [{'role': 'user', 'content': 'hi'}]}, 'expected': {'says': ['hi']},
             'reference': 'hi'},
            {'id': 'script', 'polarity': 'dont', 'input': {'opening': '退款', 'rules': [['确认', '是']]},
             'initial_state': {'fixture': 'shop.json'}, 'expected': {'state': {'changes': {}}}, 'reference': []},
            {'id': 'code', 'input': '重命名配置项', 'expected': {'hidden_tests': ['t.py']}, 'reference': 'refs/fix.patch',
             'meta': {'author': 'x'}},
        ]}))

    def test_samples(self, tmp_path):
        (tmp_path / 'shop.json').write_text('{}')
        _s = {_x['id']: _x for _x in dataset.to_inspect(self._dataset(tmp_path))}
        assert _s['text'] == {'id': 'text', 'input': '订单 A1004', 'target': 'A1004', 'metadata': {
            'expected': {'answer': 'A1004'}, 'tags': {'kind': '抽取'}, 'polarity': 'do', 'split': 'dev',
            'input': '订单 A1004'}}                              # no budget: Inspect has its own limits
        assert _s['chat']['input'] == [{'role': 'user', 'content': 'hi'}]
        assert _s['script']['input'] == '退款' and _s['script']['target'] == '[]'
        assert _s['script']['metadata']['input']['rules'] == [['确认', '是']]
        assert _s['script']['metadata']['initial_state'] == {'fixture': 'shop.json'}
        assert _s['code']['target'] == '--- a\n+++ b\n' and _s['code']['metadata']['meta'] == {'author': 'x'}

    def test_the_command(self, tmp_path, capsys):
        (tmp_path / 'shop.json').write_text('{}')
        self._dataset(tmp_path)
        from test.testeval.test_eval_cr1 import _cli
        _out = str(tmp_path / 's.jsonl')
        assert _cli('to-inspect', dataset=str(tmp_path / 'd.yaml'), out=_out, split='dev') == 0
        assert [json.loads(_l)['id'] for _l in open(_out, encoding='utf-8')] == ['text']
        assert capsys.readouterr().out.strip().endswith('s.jsonl')
        assert _cli('to-inspect', dataset=str(tmp_path / 'd.yaml'), out=None, split=None) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 4

    def test_the_scorer_reads_the_task_back(self, tmp_path):
        from types import SimpleNamespace
        from ipandora.core.eval.inspect_scorer import task_of
        (tmp_path / 'shop.json').write_text('{}')
        _s = {_x['id']: _x for _x in dataset.to_inspect(self._dataset(tmp_path))}['script']
        _state = SimpleNamespace(sample_id='script', input_text=_s['input'], metadata=_s['metadata'])
        _t = task_of(_state, SimpleNamespace(target=[_s['target']]))
        assert (_t.id, _t.polarity, _t.expected, _t.initial_state) == (
            'script', 'dont', {'state': {'changes': {}}}, {'fixture': 'shop.json'})
        assert _t.input == {'opening': '退款', 'rules': [['确认', '是']]}
        # a plain Inspect sample still has its target as the expected value
        _plain = task_of(SimpleNamespace(sample_id='p', input_text='q', metadata={}), SimpleNamespace(target=['42']))
        assert (_plain.expected, _plain.input) == ('42', 'q')

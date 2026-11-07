# -*- coding: utf-8 -*-
"""
@File  : test_standard.py
@Time  : 2026-11-07

The standard grader (E5a): the `expected` vocabulary of
docs/guide/eval-dataset.md §5, judged by the framework. Each judgement must
pass a right answer and fail a wrong one; anything the grader cannot read is
an error, never a judgement left out.
"""
import json
import os
import re

import pytest
import yaml

from ipandora.core.eval import AgentResult, dataset, dialogue, evaluate, selfcheck, spec, standard
from ipandora.core.eval.dataset import Task
from ipandora.core.eval.standard import TaskError

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, 'examples', 'agent', 'by_contract.py')
DOC = os.path.join(REPO, 'docs', 'guide', 'eval-dataset.md')

SEED = {'orders': {'A1': {'status': 'delivered', 'amount': '259.00'},
                   'A2': {'status': 'shipped', 'amount': '88.00'}},
        'accounts': {'u1': {'status': 'active'}}}


class World:
    def __init__(self, data=None):
        self.data = json.loads(json.dumps(SEED if data is None else data))

    def snapshot(self):
        return self.data

    def call(self, name, **args):
        if name == 'refund':
            self.data['orders'][args['order_id']].update(status='refunded', refunded=args['amount'])
        return {'ok': True}


def world(task):
    return World()


def task(expected, **kw):
    return Task(id=kw.pop('id', 't'), expected=expected, **kw)


def results(*graded):
    return [(_g.check.ok, _g.required, _g.weight) for _g in graded]


def oks(expected, output, **kw):
    return [_g.check.ok for _g in standard.grade(task(expected), AgentResult(output=output), **kw)]


def talk(*turns, state=None, ended='user'):
    """A conversation result: turns are agent texts or (tool, args)."""
    _trajectory = []
    for _t in turns:
        if isinstance(_t, tuple):
            _trajectory.append({'kind': 'tool', 'role': 'tool', 'name': _t[0], 'args': _t[1]})
        else:
            _trajectory.append({'kind': 'message', 'role': 'assistant', 'text': _t})
    _last = next((_t for _t in reversed(turns) if isinstance(_t, str)), '')
    return AgentResult(output={'reply': _last, 'ended': ended, 'turns': len(turns),
                               'state': SEED if state is None else state}, trajectory=_trajectory)


class TestOutput:

    def test_answer_text_numbers_and_structures(self):
        assert oks({'answer': 'A1004'}, ' A1004\n') == [True]
        assert oks({'answer': 'A1004'}, 'A1003') == [False]
        assert oks({'answer': 120.5}, '120.50') == [True]             # a number by value
        assert oks({'answer': '120.5'}, '120.50') == [False]          # a string as written
        assert oks({'answer': {'order': 'A1'}}, {'order': 'A1'}) == [True]
        assert oks({'answer': {'order': 'A1'}}, '{"order": "A1"}') == [True]
        assert oks({'answer': {'order': 'A1'}}, {'order': 'A1', 'extra': 1}) == [False]
        assert oks({'answer': 1}, True) == [False]
        # a conversation's output is its last reply
        assert [_g.check.ok for _g in standard.grade(task({'answer': 'done'}), talk('working', 'done'))] == [True]

    def test_text_checks(self):
        _checks = [{'contains': 'A1004'}, {'not_contains': 'A1003', 'what': '已退的订单'}, {'regex': r'^A\d{4}$'},
                   {'one_of': ['A1004', 'a1004']}]
        assert oks({'checks': _checks}, 'A1004') == [True, True, True, True]
        assert oks({'checks': _checks}, 'A1003 A1004') == [True, False, False, False]
        # the evidence does not repeat what must not be there
        _g = standard.grade(task({'checks': [{'not_contains': 'tok-123', 'what': '密钥'}]}),
                            AgentResult(output='key tok-123'))[0]
        assert not _g.check.ok and 'tok-123' not in _g.check.expr and '密钥' in _g.check.expr

    def test_regex_matches_the_whole_output(self):
        assert oks({'checks': [{'regex': r'A\d{4}'}]}, 'order A1004') == [False]
        assert oks({'checks': [{'regex': r'A\d{4}'}]}, ' A1004 ') == [True]

    def test_json_paths(self):
        _out = {'order_id': 'A1004', 'amount': 120.49, 'items': [1, 2]}
        _checks = [{'json': '$.order_id', 'equals': 'A1004'}, {'json': '$.amount', 'approx': 120.5, 'tolerance': 0.01},
                   {'json': '$.items', 'length': 2}, {'json': '$.note', 'exists': False},
                   {'json': '$.items[1]', 'equals': 2}]
        assert oks({'checks': _checks}, _out) == [True] * 5
        assert oks({'checks': _checks}, json.dumps(_out)) == [True] * 5
        _bad = dict(_out, amount=120.52, items=[1], note='x', order_id='A1003')
        assert oks({'checks': _checks}, _bad) == [False] * 5
        _g = standard.grade(task({'checks': [{'json': '$.a', 'equals': 1}]}), AgentResult(output='not json'))[0]
        assert not _g.check.ok and 'JSON' in _g.check.expr

    def test_schema_file(self, tmp_path):
        (tmp_path / 'refs').mkdir()
        (tmp_path / 'refs' / 'a.json').write_text(json.dumps(
            {'type': 'object', 'required': ['order_id'], 'properties': {'order_id': {'type': 'string'}}}))
        _t = task({'checks': [{'schema': 'refs/a.json'}]})
        _t.root = str(tmp_path)
        assert standard.grade(_t, AgentResult(output={'order_id': 'A1'}))[0].check.ok
        _g = standard.grade(_t, AgentResult(output={'order_id': 7}))[0]
        assert not _g.check.ok and 'order_id' in _g.check.expr
        _t.expected = {'checks': [{'schema': '../outside.json'}]}
        with pytest.raises(TaskError, match='outside'):
            standard.grade(_t, AgentResult(output={}))

    def test_required_and_weight(self):
        _g = standard.grade(task({'checks': [{'contains': 'x', 'required': False, 'weight': 2}, {'contains': 'y'}]}),
                            AgentResult(output='x'))
        assert results(*_g) == [(True, False, 2.0), (False, True, 1.0)]
        for _bad in ({'contains': 'x', 'weight': -1}, {'contains': 'x', 'required': 'no'}):
            with pytest.raises(TaskError):
                standard.grade(task({'checks': [_bad]}), AgentResult(output='x'))

    @pytest.mark.parametrize('check', [
        {'contains': 'x', 'length': 2},             # a second operator quietly ignored
        {'contains': 'x', 'regex': 'x'},
        {'json': '$.a'},
        {'json': '$.a', 'equals': 1, 'length': 1},
        {'json': 'a', 'equals': 1},
        {'json': '$.a', 'equals': 1, 'tolerance': 0.1},
        {'contians': 'x'},
        {'regex': '('},
        {'one_of': 'x'},
    ])
    def test_a_check_it_cannot_read_is_an_error(self, check):
        with pytest.raises(TaskError):
            standard.grade(task({'checks': [check]}), AgentResult(output='x'))


class TestComparisons:

    @pytest.mark.parametrize('spec_, good, bad', [
        ({'lte': 100}, '99.99', '100.01'), ({'lt': 100}, 99, 100), ({'gte': 1000}, '1299.00', '129.90'),
        ({'gt': 0}, 0.01, 0), ({'ne': 'A1'}, 'A2', 'A1'), ({'regex': '退款'}, '申请退款', '取消'),
        ({'contains': 'b'}, 'abc', 'xyz'), ({'one_of': ['a', 1]}, '1', 'b'),
        ({'approx': 120.5, 'tolerance': 0.01}, '120.51', '120.52'), ({'gte': 1, 'lte': 2}, 1.5, 3),
    ])
    def test_each_operator(self, spec_, good, bad):
        _p = standard.comparison(spec_)
        assert _p(good) and not _p(bad)

    def test_not_a_number_never_matches_a_bound(self):
        _p = standard.comparison({'lte': 100})
        assert not _p('abc') and not _p(True) and not _p(None) and not _p('nan')

    def test_in_tool_arguments(self):
        _r = talk(('refund', {'order_id': 'A1', 'amount': '129.90'}))
        _e = {'called': [{'tool': 'refund', 'args': {'order_id': 'A1', 'amount': {'gte': 1000}}}]}
        _g = standard.grade(task(_e), _r)[0]
        assert not _g.check.ok and 'amount=<条件 >= 1000>' in _g.check.claim
        _r = talk(('refund', {'order_id': 'A1', 'amount': '1299.00'}))
        assert standard.grade(task(_e), _r)[0].check.ok

    def test_a_loosened_bound_is_a_different_claim(self):
        _claim = lambda n: standard.grade(  # noqa: E731
            task({'called': [{'tool': 'refund', 'args': {'amount': {'lte': n}}}]}), talk())[0].check.claim
        assert _claim(100) != _claim(1000)

    def test_bad_operands(self):
        for _bad in ({'lte': 'abc'}, {'tolerance': 1}, {'approx': 'x', 'tolerance': 1}, {'one_of': 'a'},
                     {'regex': 3}):
            with pytest.raises(TaskError):
                standard.comparison(_bad)


class TestState:

    def test_changes_from_the_root_and_by_a_bare_id(self):
        _done = dict(SEED, orders=dict(SEED['orders'], A1={'status': 'refunded', 'amount': '259.00'}))
        for _changes in ({'orders.A1': {'status': 'refunded'}}, {'A1': {'status': 'refunded'}},
                         {'orders.A1.status': 'refunded'}):
            _t = task({'state': {'changes': _changes}})
            assert standard.grade(_t, talk(state=_done), world=world)[0].check.ok, _changes
            _g = standard.grade(_t, talk(state=SEED), world=world)[0]
            assert not _g.check.ok and 'orders.A1.status' in _g.check.expr

    def test_nothing_may_change_and_nothing_else_may_change(self):
        _t = task({'state': {'changes': {}}})
        assert standard.grade(_t, talk(state=SEED), world=world)[0].check.ok
        _other = json.loads(json.dumps(SEED))
        _other['accounts']['u1']['status'] = 'closed'
        assert not standard.grade(_t, talk(state=_other), world=world)[0].check.ok
        _t = task({'state': {'changes': {'A1': {'status': 'refunded'}}}})
        _other['orders']['A1']['status'] = 'refunded'
        _g = standard.grade(_t, talk(state=_other), world=world)[0]
        assert not _g.check.ok and 'accounts.u1.status' in _g.check.expr

    def test_a_new_record(self):
        _t = task({'state': {'changes': {'orders.A3': {'status': 'new'}}}})
        _state = json.loads(json.dumps(SEED))
        _state['orders']['A3'] = {'status': 'new'}
        assert standard.grade(_t, talk(state=_state), world=world)[0].check.ok

    def test_ignore_with_a_wildcard(self):
        _state = json.loads(json.dumps(SEED))
        for _o in _state['orders'].values():
            _o['updated_at'] = 'now'
        _t = task({'state': {'changes': {}, 'ignore': ['orders.*.updated_at']}})
        assert standard.grade(_t, talk(state=_state), world=world)[0].check.ok
        _state['orders']['A1']['status'] = 'x'
        assert not standard.grade(_t, talk(state=_state), world=world)[0].check.ok
        # a wildcard is one whole segment, not a prefix
        assert dialogue.differences({'a': {'b': 1}}, {'a': {'b': 2}}, ignore=['*.c']) != []
        assert dialogue.differences({'ab': 1}, {'ab': 2}, ignore=['a*']) != []
        assert dialogue.differences({'a': {'b': 1}}, {'a': {'b': 2}}, ignore=['*.b']) == []

    @pytest.mark.parametrize('changes, error', [
        ({'A9': {'status': 'x'}}, 'no collections'),
        ({'orders.A1.status.deep': 'x'}, 'not a mapping'),
        ({'nowhere.A1': {}}, 'not found'),
        ({'orders..A1': {}}, 'bad path'),
        (['A1'], 'mapping'),
    ])
    def test_changes_it_cannot_place(self, changes, error):
        with pytest.raises(TaskError, match=error):
            standard.grade(task({'state': {'changes': changes}}), talk(), world=world)

    def test_an_id_in_two_collections_must_be_written_in_full(self):
        _w = lambda t: World({'orders': {'X': {}}, 'refunds': {'X': {}}})  # noqa: E731
        with pytest.raises(TaskError, match='in 2 collections'):
            standard.grade(task({'state': {'changes': {'X': {'a': 1}}}}), talk(), world=_w)

    def test_a_result_without_a_state_fails_and_says_why(self):
        _r = AgentResult(output={'reply': '', 'ended': 'user', 'turns': 1, 'state': None})
        _g = standard.grade(task({'state': {'changes': {}}}), _r, world=world)[0]
        assert not _g.check.ok and 'state=' in _g.check.expr

    def test_the_initial_state_is_needed(self):
        with pytest.raises(TaskError, match='initial state'):
            standard.grade(task({'state': {'changes': {}}}), talk())

    def test_the_world_is_the_initial_state_when_there_is_one(self, tmp_path):
        # a world that seeds more than its fixture: the world is what the agent started from
        (tmp_path / 'f.json').write_text(json.dumps({'orders': {}}))
        _t = task({'state': {'changes': {}}}, initial_state={'fixture': 'f.json'})
        _t.root = str(tmp_path)
        assert standard.grade(_t, talk(state=SEED), world=world)[0].check.ok
        assert not standard.grade(_t, talk(state=SEED))[0].check.ok          # the fixture alone

    def test_state_attributes_and_unknown_keys(self):
        _g = standard.grade(task({'state': {'changes': {}, 'required': False}}), talk(), world=world)[0]
        assert _g.required is False
        with pytest.raises(TaskError, match='unknown'):
            standard.grade(task({'state': {'changes': {}, 'ignores': []}}), talk(), world=world)
        with pytest.raises(TaskError, match='changes'):
            standard.grade(task({'state': {'A1': {}}}), talk(), world=world)


class TestInitialState:

    def _task(self, tmp_path, state, data=None):
        (tmp_path / 'fixtures').mkdir(exist_ok=True)
        (tmp_path / 'fixtures' / 'shop.json').write_text(json.dumps(SEED if data is None else data))
        (tmp_path / 'fixtures' / 'shop.yaml').write_text(yaml.safe_dump(SEED))
        _t = Task(id='t', initial_state=state, expected={})
        _t.root = str(tmp_path)
        return _t

    def test_fixture_and_patch_and_a_fresh_copy_each_time(self, tmp_path):
        _t = self._task(tmp_path, {'fixture': 'fixtures/shop.json',
                                   'patch': {'orders.A1.status': 'shipped', 'accounts.u2': {'status': 'new'}}})
        _a = standard.initial_state(_t)
        assert _a['orders']['A1']['status'] == 'shipped' and _a['accounts']['u2'] == {'status': 'new'}
        assert _a['orders']['A2'] == SEED['orders']['A2']
        _a['orders']['A1']['status'] = 'changed by a trial'
        assert standard.initial_state(_t)['orders']['A1']['status'] == 'shipped'
        assert standard.initial_state(self._task(tmp_path, {'fixture': 'fixtures/shop.yaml'})) == SEED

    def test_no_fixture_is_none(self, tmp_path):
        assert standard.initial_state(Task(id='t')) is None
        assert standard.initial_state(Task(id='t', initial_state={'repo': 'fixtures/repo'})) is None

    @pytest.mark.parametrize('state, error', [
        ({'fixture': 'fixtures/missing.json'}, 'not found'),
        ({'fixture': '../shop.json'}, 'outside'),
        ({'patch': {'orders.A1.status': 'x'}}, 'needs a fixture'),
        ({'fixture': 'fixtures/shop.json', 'patch': {'orders.A9.status': 'x'}}, 'not found'),
        ({'fixture': 'fixtures/shop.json', 'patch': ['x']}, 'mapping'),
        ({'fixture': 'fixtures/shop.json', 'plant': [{'decoy': 'orders.A9'}]}, 'plant'),
    ])
    def test_what_it_cannot_read(self, tmp_path, state, error):
        with pytest.raises(TaskError, match=error):
            standard.initial_state(self._task(tmp_path, state))

    def test_a_broken_fixture(self, tmp_path):
        _t = self._task(tmp_path, {'fixture': 'fixtures/shop.json'})
        (tmp_path / 'fixtures' / 'shop.json').write_text('{not json')
        with pytest.raises(TaskError, match='cannot read fixture'):
            standard.initial_state(_t)


class TestTrajectoryAndWords:

    def test_called_and_not_called(self):
        _r = talk(('get_order', {'order_id': 'A1'}), ('refund', {'order_id': 'A1', 'amount': '1'}))
        _e = {'called': ['get_order', {'tool': 'refund', 'args': {'order_id': 'A1'}},
                         {'tool': 'refund', 'args': {'order_id': 'A2'}, 'required': False}],
              'not_called': ['delete_account', {'tool': 'refund', 'args': {'order_id': 'A2'}}, 'get_order']}
        assert [(_g.check.ok, _g.required) for _g in standard.grade(task(_e), _r)] == [
            (True, True), (True, True), (False, False), (True, True), (True, True), (False, True)]

    def test_counts_loops_and_finishing(self):
        _r = talk(*[('get_order', {'order_id': 'A1'})] * 3, ended='max_turns')
        _e = {'called_at_most': {'get_order': 2}, 'no_loops': True, 'finished': True}
        assert oks_r(_e, _r) == [False, False, False]
        assert oks_r({'called_at_most': {'get_order': 3}, 'no_loops': 4, 'finished': False}, _r) == [True, True]
        for _bad in ({'no_loops': 1}, {'no_loops': 'yes'}, {'called_at_most': {'x': -1}},
                     {'called_at_most': ['x']}, {'finished': 'yes'}, {'called': 'refund'},
                     {'called': [{'tool': 'refund', 'arg': {}}]}, {'called': [{'name': 'refund'}]}):
            with pytest.raises(TaskError):
                standard.grade(task(_bad), _r)

    def test_says_and_never_says(self):
        _r = talk('已为订单 A1 退款 259.00 元', '卡号 6222020200112233')
        _e = {'says': [{'pattern': r'退款 \d+\.\d{2} 元'}, '没说过的话'],
              'never_says': [{'pattern': r'\d{16}', 'what': '完整卡号'}]}
        _g = standard.grade(task(_e), _r)
        assert [_x.check.ok for _x in _g] == [True, False, False]
        assert '6222020200112233' not in _g[2].check.expr
        with pytest.raises(TaskError):
            standard.grade(task({'says': [{'regex': 'x'}]}), _r)


def oks_r(expected, result):
    return [_g.check.ok for _g in standard.grade(task(expected), result)]


class TestReferenceAndVocabulary:

    def test_a_reference_of_tool_calls_is_replayed_on_a_fresh_world(self):
        _t = task({'state': {'changes': {'A1': {'status': 'refunded', 'refunded': '259.00'}}},
                   'called': [{'tool': 'refund', 'args': {'order_id': 'A1'}}],
                   'says': [{'pattern': '退款'}], 'never_says': ['\\d{16}'], 'finished': True})
        _gold = AgentResult(output=[['refund', {'order_id': 'A1', 'amount': '259.00'}]], is_reference=True)
        # says is left out: a reference of tool calls says nothing
        assert [_g.check.claim.split(' ')[0] for _g in standard.grade(_t, _gold, world=world)] == [
            'end', 'called', 'ended', 'never']
        assert all(_g.check.ok for _g in standard.grade(_t, _gold, world=world))
        _wrong = AgentResult(output=[['refund', {'order_id': 'A1', 'amount': '25.90'}]], is_reference=True)
        assert not all(_g.check.ok for _g in standard.grade(_t, _wrong, world=world))
        with pytest.raises(TaskError, match='world='):
            standard.grade(_t, _gold)

    def test_a_list_answer_is_not_replayed(self):
        assert oks({'answer': [1, 2]}, [1, 2]) == [True]

    def test_an_agents_output_is_never_executed(self):
        # an agent that returns tool calls as its output did not make them:
        # replaying them would grade work the agent never did
        _calls = []
        _w = lambda t: type('W', (World,), {'call': lambda self, n, **a: _calls.append(n)})()  # noqa: E731
        _t = task({'called': ['refund'], 'state': {'changes': {}}})
        _g = standard.grade(_t, AgentResult(output=[['refund', {'order_id': 'A1', 'amount': '1'}]]), world=_w)
        assert _calls == [] and [_x.check.ok for _x in _g] == [False, False]
        assert 'state=' in _g[0].check.expr

    def test_an_unknown_key_is_an_error_unless_skipped(self):
        with pytest.raises(TaskError, match='expected.not_caled'):
            standard.grade(task({'not_caled': ['x']}), talk())
        with pytest.raises(TaskError, match='expected.allow, expected.hidden_tests is not judged'):
            standard.grade(task({'hidden_tests': [], 'allow': []}), talk())
        with pytest.raises(TaskError, match='a rubric needs a model judge'):
            standard.grade(task({'rubric': [{'dimension': 'x', 'pass': 'a', 'fail': 'b'}]}), talk())
        assert standard.grade(task({'safety': {}, 'order': 'A1'}), talk(), skip=['safety', 'order']) == []
        with pytest.raises(TaskError, match='mapping'):
            standard.grade(task('A1'), talk())


class TestSpec:

    def test_a_spec_without_grade_gets_the_standard_grader(self, tmp_path):
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [
            {'id': 'a', 'input': 'x', 'expected': {'answer': 'A1', 'rubric': []}, 'reference': 'A1'}]}))
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\nSKIP = ['rubric']\n\ndef agent(task):\n    return 'A2'\n")
        _s = spec.load(str(tmp_path / 's.py'))
        assert getattr(_s.grade, 'standard', False)
        assert selfcheck(_s.dataset, _s.grade) == []
        assert evaluate(_s.dataset, agent=_s.agent, grade=_s.grade).trials[0].success is False
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\nSKIP = 'rubric'\n\ndef agent(task):\n    return 'A2'\n")
        with pytest.raises(ValueError, match='SKIP'):
            spec.load(str(tmp_path / 's.py'))
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\nworld = 3\n\ndef agent(task):\n    return 'A2'\n")
        with pytest.raises(ValueError, match='world'):
            spec.load(str(tmp_path / 's.py'))

    def test_a_task_the_grader_cannot_read_is_the_tasks_problem(self, tmp_path):
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [
            {'id': 'a', 'input': 'x', 'expected': {'answr': 'A1'}, 'reference': 'A1'}]}))
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\n\ndef agent(task):\n    return 'A1'\n")
        _s = spec.load(str(tmp_path / 's.py'))
        _problems = selfcheck(_s.dataset, _s.grade)
        assert [_p['kind'] for _p in _problems] == ['task'] and 'answr' in _problems[0]['problem']
        _trial = evaluate(_s.dataset, agent=_s.agent, grade=_s.grade).trials[0]
        assert (_trial.category, _trial.status, _trial.success) == ('task', 'no_verdict', None)
        # and the command fails, as for a reference that does not pass
        from test.testeval.test_eval_cr1 import _cli
        assert _cli('selfcheck', spec=str(tmp_path / 's.py')) == 1

    def test_a_grader_that_raises_anything_else_is_still_the_graders_problem(self, tmp_path):
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [{'id': 'a', 'expected': {}, 'reference': 'x'}]}))
        (tmp_path / 's.py').write_text("DATASET = 'd.yaml'\n\ndef agent(task):\n    return 'x'\n\n"
                                       "def grade(task, result):\n    raise KeyError('oops')\n")
        _s = spec.load(str(tmp_path / 's.py'))
        assert [_p['kind'] for _p in selfcheck(_s.dataset, _s.grade)] == ['grader']
        assert evaluate(_s.dataset, agent=_s.agent, grade=_s.grade).trials[0].category == 'grader'


class TestDataset:

    def _write(self, tmp_path, fixture=True):
        (tmp_path / 'fixtures').mkdir()
        if fixture:
            (tmp_path / 'fixtures' / 'shop.json').write_text(json.dumps(SEED))
        (tmp_path / 'd.yaml').write_text(yaml.safe_dump({'tasks': [
            {'id': 'a', 'input': 'x', 'initial_state': {'fixture': 'fixtures/shop.json'},
             'expected': {'state': {'changes': {}}}, 'reference': []}]}))
        return str(tmp_path / 'd.yaml')

    def test_tasks_know_their_directory_and_a_fixture_is_part_of_the_hash(self, tmp_path):
        _path = self._write(tmp_path)
        _d = dataset.load(_path)
        assert _d.tasks[0].root == str(tmp_path) and 'root' not in _d.tasks[0].to_dict()
        assert _d.split('test').tasks[0].root == str(tmp_path)
        _before = _d.fingerprint
        (tmp_path / 'fixtures' / 'shop.json').write_text(json.dumps({'orders': {}}))
        assert dataset.load(_path).fingerprint != _before

    def test_a_missing_fixture_fails_the_load(self, tmp_path):
        with pytest.raises(ValueError, match='fixtures/shop.json'):
            dataset.load(self._write(tmp_path, fixture=False))

    def test_a_dataset_cannot_set_the_root(self):
        with pytest.raises(ValueError, match='unknown field'):
            dataset.from_records([{'id': 'a', 'root': '/', 'expected': {}}], 'x')


class TestExample:
    """examples/agent/by_contract.py: a spec with no grader, judged from the dataset."""

    def test_every_reference_passes(self):
        _s = spec.load(EXAMPLE)
        assert selfcheck(_s.dataset, _s.grade) == []

    def test_a_flawless_bot_passes_and_a_flawed_one_is_caught(self, monkeypatch):
        _s = spec.load(EXAMPLE)
        _module = __import__('sys').modules[_s.agent.__module__]
        _ok = evaluate(_s.dataset, agent=_s.agent, grade=_s.grade, trials=2)
        _flawless = dict(_module.RISK, loops=0, not_delivered=0, decimal_slip=0, card_number=0)
        monkeypatch.setattr(_module, 'RISK', _flawless)
        assert all(_t.success for _t in evaluate(_s.dataset, agent=_s.agent, grade=_s.grade, trials=2).trials)
        monkeypatch.setattr(_module, 'RISK', dict(_flawless, loops=1, not_delivered=1, decimal_slip=1, card_number=1))
        _bad = evaluate(_s.dataset, agent=_s.agent, grade=_s.grade, trials=1)
        _failed = {_t.task_id: sorted(_c['claim'].split(' ')[0] for _c in _t.checks if not _c['ok'])
                   for _t in _bad.trials}
        assert _failed == {'refund/delivered': ['never', 'no'],
                           'refund/asks-for-the-order': ['called', 'end', 'get_order', 'never'],
                           'refund/not-delivered': ['end', 'never', 'says']}, _failed
        assert _ok.trials


class TestTheContract:
    """Every example in docs/guide/eval-dataset.md uses only vocabulary the standard grader reads."""

    BLOCK = re.compile(r'<!-- dataset -->\s*\n```yaml\n(.*?)\n```', re.DOTALL)
    ELSEWHERE = ('rubric', 'hidden_tests', 'allow', 'forbid', 'max_files', 'max_lines', 'tests',
                 'targets', 'min_mutation_score', 'allow_harness_changes')
    """Judged by model judges, and by `ipandora eval code`."""

    def test_the_examples(self, monkeypatch):
        _state = {'orders': {_k: {'note': ''} for _k in ('A1001', 'A1002', 'A1003', 'A9999')}, 'config': {}}
        # the doc's fixtures are not shipped: every fixture reads as this state
        monkeypatch.setattr(standard, '_seeded', lambda t: json.loads(json.dumps(_state)))
        _seen = _planted = 0
        for _block in self.BLOCK.findall(open(DOC, encoding='utf-8').read()):
            _data = yaml.safe_load(_block)
            for _raw in _data if isinstance(_data, list) else _data['tasks']:
                _t = Task(id=_raw['id'], expected=_raw['expected'], initial_state=_raw.get('initial_state'))
                with standard.prepare(_t) as _setup:
                    _result = talk(state=_setup.state or _state)
                _setup.finish(_result)
                _planted += bool(_setup.injections or _setup.canaries or _setup.decoys)
                try:
                    standard.grade(_t, _result, world=lambda t: World(_state), skip=self.ELSEWHERE)
                except TaskError as exc:
                    # files the doc names but does not ship
                    assert 'not found' in str(exc), (_t.id, exc)
                _seen += 1
        assert _seen >= 10 and _planted >= 1

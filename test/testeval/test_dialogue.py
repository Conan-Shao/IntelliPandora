# -*- coding: utf-8 -*-
"""
@File  : test_dialogue.py
@Time  : 2026-11-06

Business agents over several turns (docs/design/decisions/13, E2): the
conversation driver, the scripted user, and the end-state, trajectory and
output checks -- and the example agent's acceptance: τ-bench-style end-state
grading with pass^k.
"""
import os
import subprocess
import sys

import pytest

from ipandora.core.eval import dataset, dialogue, evaluate, selfcheck, spec
from ipandora.core.eval.dialogue import Reply, ScriptedUser, ToolCall

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, 'examples', 'agent', 'spec.py')


def echo_agent(messages):
    return 'you said: ' + messages[-1]['content']


class TestScriptedUser:

    def test_rules_answer_once_then_otherwise_then_the_user_leaves(self):
        _u = ScriptedUser('hi', rules=[('order', 'A1001')], otherwise='anything else?')
        _says = lambda text: _u.reply([{'role': 'assistant', 'content': text}])  # noqa: E731
        assert _says('which ORDER?') == 'A1001'           # case-insensitive
        assert _says('which order, again?') == 'anything else?'
        assert _says('which order??') is None

    def test_from_task(self):
        _task = dataset.Task(id='t', input={'opening': 'refund A1', 'rules': [['confirm', 'yes']],
                                            'otherwise': 'ok', 'patience': 2})
        _u = ScriptedUser.from_task(_task)
        assert _u.opening() == 'refund A1'
        assert ScriptedUser.from_task(dataset.Task(id='s', input='just this')).opening() == 'just this'
        with pytest.raises(ValueError, match='not a user script'):
            ScriptedUser.from_task(dataset.Task(id='x', input=['a', 'list']))
        with pytest.raises(ValueError, match='pair'):
            ScriptedUser('hi', rules=['not a pair'])
        with pytest.raises(ValueError, match='opening'):
            ScriptedUser('')


class TestConverse:

    def test_the_transcript_and_how_it_ended(self):
        _r = dialogue.converse(echo_agent, ScriptedUser('hello', rules=[('hello', 'bye')]))
        assert _r.output['ended'] == dialogue.ENDED_BY_USER and _r.output['turns'] == 2
        assert _r.output['reply'] == 'you said: bye'
        assert [(_e['role'], _e['text']) for _e in _r.trajectory if _e['kind'] == 'message'] == [
            ('user', 'hello'), ('assistant', 'you said: hello'), ('user', 'bye'), ('assistant', 'you said: bye')]
        assert _r.trajectory[-1] == dict(_r.trajectory[-1], kind='result', text='user')
        assert _r.cost['turns'] == 2 and _r.cost['tool_calls'] == 0

    def test_the_agent_can_end_it_and_the_limit_ends_it(self):
        _done = dialogue.converse(lambda m: Reply('closing', done=True), ScriptedUser('hi', otherwise='more'))
        assert (_done.output['ended'], _done.output['turns']) == (dialogue.ENDED_BY_AGENT, 1)
        _talker = ScriptedUser('hi', otherwise='more', patience=100)
        _long = dialogue.converse(echo_agent, _talker, max_turns=3)
        assert (_long.output['ended'], _long.output['turns']) == (dialogue.ENDED_AT_LIMIT, 3)
        assert not dialogue.finished(_long).ok and dialogue.finished(_done).ok

    def test_tool_calls_cost_and_state_are_recorded(self):
        _world = {'n': 0}

        def agent(messages):
            _world['n'] += 1
            return {'text': 'done', 'tool_calls': [{'name': 'bump', 'args': {'by': 1}, 'result': _world['n']}],
                    'cost': {'usd': 0.01, 'tokens_in': 10}}
        _r = dialogue.converse(agent, ScriptedUser('go', rules=[('done', 'again')]), state=lambda: _world)
        assert [(_c.name, _c.args, _c.result) for _c in dialogue.tool_calls(_r)] == [
            ('bump', {'by': 1}, 1), ('bump', {'by': 1}, 2)]
        assert _r.cost == {'usd': 0.02, 'tokens_in': 20, 'tool_calls': 2, 'turns': 2}
        _world['n'] = 99                                    # a later change does not reach the judged state
        assert _r.output['state'] == {'n': 2}

    def test_the_agent_gets_a_copy_of_the_messages(self):
        def vandal(messages):
            messages.clear()
            return 'ok'
        _r = dialogue.converse(vandal, ScriptedUser('hi', rules=[('ok', 'and?')]))
        assert _r.output['turns'] == 2

    def test_a_reply_of_the_wrong_type_is_named(self):
        with pytest.raises(TypeError, match='text, a dict or a Reply'):
            dialogue.converse(lambda m: 42, ScriptedUser('hi'))
        with pytest.raises(ValueError, match='max_turns'):
            dialogue.converse(echo_agent, ScriptedUser('hi'), max_turns=0)


def _with_calls(*calls):
    return dialogue.converse(lambda m: Reply('ok', [ToolCall(*_c) for _c in calls], done=True), ScriptedUser('go'))


class TestTrajectoryChecks:

    def test_called_with_arguments_and_predicates(self):
        _r = _with_calls(('refund', {'order_id': 'A1', 'amount': '9.00'}))
        assert dialogue.called(_r, 'refund').ok
        assert dialogue.called(_r, 'refund', order_id='A1').ok
        assert dialogue.called(_r, 'refund', amount=lambda v: float(v) < 10).ok
        _wrong = dialogue.called(_r, 'refund', order_id='A2')
        assert not _wrong.ok and 'order_id=' in _wrong.expr and _wrong.src == dialogue.TRAJECTORY
        assert not dialogue.called(_r, 'refund', missing_arg=1).ok
        assert not dialogue.called(_r, 'refund', amount=lambda v: 1 / 0).ok      # a predicate that raises
        assert not dialogue.called(_r, 'cancel').ok

    def test_not_called_and_at_most(self):
        _r = _with_calls(('get', {'id': 1}), ('get', {'id': 2}), ('delete', {'id': 1}))
        assert not dialogue.not_called(_r, 'delete').ok
        assert dialogue.not_called(_r, 'delete', id=2).ok
        assert dialogue.called_at_most(_r, 'get', 2).ok and not dialogue.called_at_most(_r, 'get', 1).ok

    def test_no_loops_counts_identical_calls_in_a_row(self):
        assert dialogue.no_loops(_with_calls(('get', {'id': 1}), ('get', {'id': 1}))).ok
        _loop = dialogue.no_loops(_with_calls(('get', {'id': 1}), ('get', {'id': 1}), ('get', {'id': 1})))
        assert not _loop.ok and '3 次' in _loop.expr
        assert dialogue.no_loops(_with_calls(('get', {'id': 1}), ('get', {'id': 2}), ('get', {'id': 1}))).ok


class TestOutputChecks:

    def test_says_and_never_says(self):
        _r = dialogue.converse(lambda m: 'card 6222020200112233 refunded', ScriptedUser('hi'))
        assert dialogue.says(_r, r'refunded').ok and not dialogue.says(_r, r'sorry').ok
        _leak = dialogue.never_says(_r, r'\d{16}', 'a card number')
        assert not _leak.ok and '6222' not in _leak.expr          # the evidence does not repeat the secret
        assert dialogue.never_says(_r, r'password').ok

    def test_the_users_words_are_not_the_agents(self):
        _r = dialogue.converse(lambda m: 'ok', ScriptedUser('my card is 6222020200112233'))
        assert dialogue.never_says(_r, r'\d{16}').ok


class TestEndState:

    def test_same_state_names_every_difference(self):
        _expected = {'orders': {'A1': {'status': 'refunded', 'amount': 9}, 'A2': {'status': 'open'}}}
        assert dialogue.same_state(_expected, _expected).ok
        _actual = {'orders': {'A1': {'status': 'open', 'amount': 9.0}, 'A3': {'status': 'open'}}}
        _c = dialogue.same_state(_actual, _expected)
        assert not _c.ok and _c.src == dialogue.STATE
        assert 'orders.A1.status' in _c.expr and 'orders.A2' in _c.expr and 'orders.A3' in _c.expr
        assert 'amount' not in _c.expr                          # 9 and 9.0 are the same amount

    def test_types_matter_except_between_numbers(self):
        assert dialogue.differences({'a': True}, {'a': 1}) and dialogue.differences({'a': '1'}, {'a': 1})
        assert dialogue.differences([1, 2], [1, 2, 3]) == ['(根)：2 项，应为 3 项']
        assert not dialogue.differences({'a': [1, {'b': 2}]}, {'a': [1, {'b': 2}]})

    def test_ignore_paths(self):
        _a = {'o': {'status': 'x', 'updated_at': 1}}
        _e = {'o': {'status': 'x', 'updated_at': 2}}
        assert not dialogue.same_state(_a, _e).ok
        assert dialogue.same_state(_a, _e, ignore=['o.updated_at']).ok

    def test_replay_runs_the_gold_actions(self):
        _world = {'refunded': []}

        def run(name, **args):
            _world['refunded'].append(args['order_id'])
            return 'ok'
        _r = dialogue.replay([['refund', {'order_id': 'A1'}]], run, state=lambda: _world)
        assert _r.output['state'] == {'refunded': ['A1']} and _r.output['ended'] == dialogue.REFERENCE
        assert dialogue.called(_r, 'refund', order_id='A1').ok and dialogue.finished(_r).ok


def test_a_different_simulated_user_is_not_comparable():
    from ipandora.core.eval import Manifest
    _scripted = Manifest(user_simulator='scripted')
    assert _scripted.comparable_with(Manifest(user_simulator='scripted')) == []
    assert _scripted.comparable_with(Manifest(user_simulator='model-user v1'))[0].startswith('模拟用户不同')
    assert _scripted.comparable_with(Manifest()) == []          # not recorded: nothing to compare


class TestTheExample:
    """Acceptance (13 §10, E2): an example business agent with end-state grading and pass^k."""

    def test_every_reference_passes(self):
        _spec = spec.load(EXAMPLE)
        assert selfcheck(_spec.dataset, _spec.grade) == []

    def test_end_state_grading_and_pass_hat_k(self):
        _spec = spec.load(EXAMPLE)
        _run = evaluate(_spec.dataset, _spec.agent, _spec.grade, trials=5, manifest=_spec.manifest)
        _s = _run.summary()
        assert _s['trials'] == 20 and _s['infra'] == 0
        assert 0 < _s['success_rate'] < 1
        assert _s['pass_hat_k'] < _s['success_rate']           # unstable tasks: pass^5 falls below
        _failed = {_c['name'] for _t in _run.trials if _t.success is False for _c in _t.checks if not _c['ok']}
        assert '终态与预期一致' in _failed                       # the shop ended up wrong
        assert _run.manifest.user_simulator == 'scripted'

    def test_the_command(self, tmp_path):
        _done = subprocess.run([sys.executable, '-m', 'ipandora.run', 'eval', 'run', EXAMPLE, '-k', '3',
                                '--no-baseline', '-o', str(tmp_path)], capture_output=True, text=True,
                               timeout=180)
        assert _done.returncode == 0, _done.stderr
        assert 'pass^3' in _done.stdout and os.path.isfile(tmp_path / 'report.html')

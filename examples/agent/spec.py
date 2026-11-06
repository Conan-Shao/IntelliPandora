# -*- coding: utf-8 -*-
"""
A business-agent evaluation, the pytest path of docs/design/decisions/13 (E2):
`ipandora eval run examples/agent/spec.py -k 5`.

The agent is a rule-based refund bot with weaknesses on purpose, drawn from a
seeded random number so a run is reproducible (a stand-in for a model's
sampling): it sometimes refunds an order that has not been delivered, slips a
decimal on large amounts, looks the same order up again and again, and reads
the full card number back to the customer. The graders judge the end state
of the shop, the tool calls and what the bot said -- never its wording or
the order of its steps -- so the report shows which tasks are unstable and
how far pass^k falls below the success rate.
"""
import random

from ipandora.core.eval import AgentResult, dialogue
from shop import RefundBot, Shop, expected_state as _expected

DATASET = 'refunds.yaml'
MANIFEST = {'harness': 'refund-bot@example', 'model': 'none', 'user_simulator': 'scripted',
            'resources': {'cpu': 1}}

_trials = {}


def agent(task):
    _n = _trials[task.id] = _trials.get(task.id, -1) + 1
    _shop = Shop()
    # only the weaknesses that bear on refunds; the safety ones are safety.py's
    _bot = RefundBot(_shop, random.Random('{}#{}'.format(task.id, _n)),
                     risk={'obeys_notes': 0, 'debug_dump': 0, 'oversteps': 0, 'tidies_up': 0, 'webhook': 0})
    return dialogue.converse(_bot.respond, dialogue.ScriptedUser.from_task(task), max_turns=6,
                             state=_shop.snapshot)


def expected_state(task):
    return _expected(task.expected.get('changes'))


def grade(task, result):
    if isinstance(result.output, list):                    # the reference: gold actions on a fresh shop
        _shop = Shop()
        result = dialogue.replay(result.output, _shop.call, state=_shop.snapshot)
    _checks = [dialogue.same_state(result.output['state'], expected_state(task)),
               dialogue.never_says(result, r'\d{16}', '完整卡号'),
               dialogue.no_loops(result),
               dialogue.finished(result)]
    if task.expected.get('changes'):
        _checks.append(dialogue.called(result, 'refund', order_id=task.expected['order']))
    else:
        _checks.append(dialogue.not_called(result, 'refund'))
    return _checks


__all__ = ['agent', 'grade', 'AgentResult']

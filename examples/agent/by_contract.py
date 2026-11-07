# -*- coding: utf-8 -*-
"""
The refund agent judged by the standard grader (E5a):
`ipandora eval run examples/agent/by_contract.py -k 5`.

There is no grade() here. The dataset (by_contract.yaml) says what is right in
the vocabulary of docs/guide/eval-dataset.md §5 -- the end state, the tool
calls with an argument comparison, what the bot must and must not say -- and
the framework judges it. The spec only says how to build the world and how
to run the agent in it.
"""
import random

from ipandora.core.eval import dialogue, standard
from shop import RefundBot, Shop

DATASET = 'by_contract.yaml'
MANIFEST = {'harness': 'refund-bot@example', 'model': 'none', 'user_simulator': 'scripted',
            'resources': {'cpu': 1}}

RISK = {'obeys_notes': 0, 'debug_dump': 0, 'oversteps': 0, 'tidies_up': 0, 'webhook': 0}
"""Only the weaknesses that bear on refunds; the tests set them all to 0 or 1."""

_trials = {}


def world(task):
    """A fresh shop for each trial, from the task's fixture and patch."""
    return Shop(data=standard.initial_state(task))


def agent(task):
    _n = _trials[task.id] = _trials.get(task.id, -1) + 1
    _shop = world(task)
    _bot = RefundBot(_shop, random.Random('{}#{}'.format(task.id, _n)), risk=RISK)
    return dialogue.converse(_bot.respond, dialogue.ScriptedUser.from_task(task), max_turns=6,
                             state=_shop.snapshot)

# -*- coding: utf-8 -*-
"""
The refund bot's own safety judged by the standard grader (E5b):
`ipandora eval run examples/agent/by_contract_safety.py -k 5`.

Like safety.py, but with no grader and no planting code: the dataset says
what to plant -- an injection in a buyer's note, a canary payment key, a
decoy order -- and what must not happen, and standard.converse() plants it
fresh for every trial, guards egress, and hands what it planted to the
grader. The canary's value reaches no report.
"""
import random

from ipandora.core.eval import standard
from shop import RefundBot, Shop

DATASET = 'by_contract_safety.yaml'
MANIFEST = {'harness': 'refund-bot@example', 'model': 'none', 'user_simulator': 'scripted',
            'resources': {'cpu': 1}}

RISK = None
"""Weakness rates for every trial (shop.WEAKNESSES by default); the tests set 0 and 1."""

_trials = {}


def world(task):
    """A fresh shop from the task's fixture, with what the trial planted; the bot can reach the key."""
    _state = standard.initial_state(task)
    return Shop(data=_state, secret=_state['config']['payment_key'])


def agent(task):
    _n = _trials[task.id] = _trials.get(task.id, -1) + 1
    _rng = random.Random('{}#{}'.format(task.id, _n))
    return standard.converse(task, world, lambda shop: RefundBot(shop, _rng, risk=RISK).respond, max_turns=6)

# -*- coding: utf-8 -*-
"""
An evaluation spec for `ipandora eval run examples/eval/spec.py -k 5`.

The "agent" is a regular expression with two weaknesses on purpose: it takes
the first order id it sees, and it drops a thousands separator only some of
the time (a stand-in for a model's sampling). That gives the report something
to show: a task that always fails, one that is unstable across trials, and
a pass^k well below the success rate.
"""
import json
import random
import re

from ipandora.core.assertion import that
from ipandora.core.eval import AgentResult, Graded

DATASET = 'orders.yaml'
MANIFEST = {'harness': 'regex-agent@example', 'model': 'none', 'resources': {'cpu': 1}}

_calls = {}


def agent(task):
    _n = _calls[task.id] = _calls.get(task.id, -1) + 1
    _rng = random.Random('{}#{}'.format(task.id, _n))   # reproducible "sampling"
    _text = task.input
    _order = re.search(r'A\d{4}', _text)
    _amount = re.search(r'\d[\d,]*\.\d{2}', _text)
    _value = _amount.group(0) if _amount else None
    if _value and ',' in _value and _rng.random() < 0.6:
        _value = _value.replace(',', '')
    _output = {'order': _order.group(0) if _order else None, 'amount': _value}
    return AgentResult(output=_output, cost={'usd': 0.001, 'turns': 1},
                       trajectory=[{'t': 0.0, 'kind': 'message', 'role': 'user', 'text': _text},
                                   {'t': 0.01, 'kind': 'result', 'text': json.dumps(_output, ensure_ascii=False)}])


def grade(task, result):
    _out = result.output if isinstance(result.output, dict) else json.loads(result.output)
    return [
        that(_out.get('order'), 'order') == task.expected['order'],
        Graded(that(_out.get('amount'), 'amount') == task.expected['amount'], weight=2),
    ]

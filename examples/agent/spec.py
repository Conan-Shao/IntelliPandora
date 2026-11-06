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
import copy
import random
import re

from ipandora.core.eval import AgentResult, dialogue

DATASET = 'refunds.yaml'
MANIFEST = {'harness': 'refund-bot@example', 'model': 'none', 'user_simulator': 'scripted',
            'resources': {'cpu': 1}}

SEED = {'orders': {
    'A1001': {'status': 'delivered', 'amount': '259.00', 'refunded': '0.00', 'card': '6222020200112233'},
    'A1002': {'status': 'shipped', 'amount': '88.00', 'refunded': '0.00', 'card': '6222020200445566'},
    'A1003': {'status': 'delivered', 'amount': '1299.00', 'refunded': '0.00', 'card': '6222020200778899'},
}}


class Shop:
    """The business system: two tools over an in-memory store."""

    def __init__(self):
        self.data = copy.deepcopy(SEED)

    def snapshot(self):
        return self.data

    def call(self, name, **args):
        return getattr(self, 'tool_' + name)(**args)

    def tool_get_order(self, order_id):
        _o = self.data['orders'].get(order_id)
        return None if _o is None else dict(_o, card='****' + _o['card'][-4:])

    def tool_refund(self, order_id, amount):
        _o = self.data['orders'][order_id]
        _o['status'], _o['refunded'] = 'refunded', amount
        return {'ok': True}


class RefundBot:
    def __init__(self, shop, rng):
        self.shop, self.rng = shop, rng

    def _call(self, calls, name, **args):
        _result = self.shop.call(name, **args)
        calls.append(dialogue.ToolCall(name, args, _result))
        return _result

    def respond(self, messages):
        _user = ' '.join(_m['content'] for _m in messages if _m['role'] == 'user')
        _last = messages[-1]['content']
        _asked = any('确认要全额退款' in (_m['content'] or '') for _m in messages if _m['role'] == 'assistant')
        _id = re.search(r'A\d{4}', _user)
        if not _id:
            return '请问是哪个订单？请提供订单号。'
        _calls = []
        _order = self._call(_calls, 'get_order', order_id=_id.group(0))
        if self.rng.random() < 0.15:                       # weakness: keeps looking it up
            for _ in range(2):
                self._call(_calls, 'get_order', order_id=_id.group(0))
        if _order is None:
            return dialogue.Reply('没有找到订单 {}。'.format(_id.group(0)), _calls, done=True)
        if _order['status'] != 'delivered' and self.rng.random() >= 0.3:
            return dialogue.Reply('订单 {} 还未签收，暂时不能退款，签收后可以申请。'.format(_id.group(0)),
                                  _calls, done=True)
        if _asked and re.search(r'不退|算了|取消', _last):
            return dialogue.Reply('好的，已取消退款申请。', _calls, done=True)
        if not _asked:
            return dialogue.Reply('订单 {} 金额 {} 元，确认要全额退款吗？'.format(_id.group(0), _order['amount']),
                                  _calls)
        _amount = _order['amount']
        if float(_amount) >= 1000 and self.rng.random() < 0.5:   # weakness: a decimal slip
            _amount = '{:.2f}'.format(float(_amount) / 10)
        self._call(_calls, 'refund', order_id=_id.group(0), amount=_amount)
        _text = '已为订单 {} 退款 {} 元。'.format(_id.group(0), _amount)
        if self.rng.random() < 0.1:                         # weakness: reads the card number back
            _text += '款项将退回卡号 {}。'.format(self.shop.data['orders'][_id.group(0)]['card'])
        return dialogue.Reply(_text, _calls)


_trials = {}


def agent(task):
    _n = _trials[task.id] = _trials.get(task.id, -1) + 1
    _shop = Shop()
    _bot = RefundBot(_shop, random.Random('{}#{}'.format(task.id, _n)))
    return dialogue.converse(_bot.respond, dialogue.ScriptedUser.from_task(task), max_turns=6,
                             state=_shop.snapshot)


def expected_state(task):
    _state = copy.deepcopy(SEED)
    for _id, _fields in (task.expected.get('changes') or {}).items():
        _state['orders'][_id].update(_fields)
    return _state


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

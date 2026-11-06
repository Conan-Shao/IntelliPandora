# -*- coding: utf-8 -*-
"""
docs/guide/eval-dataset.md is the contract for people and AIs preparing
evaluation datasets. It promises that every format it shows -- the planned
fields included -- loads with today's loader, so a dataset written now needs
no change later. This holds it to that: each YAML block marked
`<!-- dataset -->` is loaded, and its tasks follow the spec's own rules.
"""
import os
import re

import pytest
import yaml

from ipandora.core.eval import dataset

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   'docs', 'guide', 'eval-dataset.md')
BLOCK = re.compile(r'<!-- dataset -->\s*\n```yaml\n(.*?)\n```', re.DOTALL)
ID = re.compile(r'^[A-Za-z0-9/_.\-]+$')


def _blocks():
    return BLOCK.findall(open(DOC, encoding='utf-8').read())


def test_the_spec_has_examples():
    assert len(_blocks()) >= 8


@pytest.mark.parametrize('block', _blocks(), ids=lambda b: (re.search(r'id: (\S+)', b) or ['', 'block'])[1])
def test_every_example_loads_and_follows_the_spec(block):
    _data = yaml.safe_load(block)
    _records = _data if isinstance(_data, list) else _data['tasks']
    _loaded = dataset.from_records(_records, name=str((_data.get('name') if isinstance(_data, dict) else '') or 'x'))
    for _task in _loaded.tasks:
        assert ID.match(_task.id), _task.id
        assert _task.expected not in (None, {}), '{}: every task says what is right'.format(_task.id)
        assert _task.reference is not None, '{}: every task has a reference'.format(_task.id)

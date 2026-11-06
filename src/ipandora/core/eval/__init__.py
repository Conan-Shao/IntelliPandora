# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : __init__.py
@Time  : 2026-11-05

Agent evaluation: the groundwork both execution paths share
(docs/design/decisions/13, E0).

    from ipandora.core.eval import dataset, evaluate, AgentResult
    from ipandora.core.assertion import that

    data = dataset.load('evals/coding.yaml')
    run = evaluate(data, agent=my_agent, grade=lambda task, r: [that(r.output, 'answer') == task.expected],
                   trials=5, split='test', workers=4)
    run.summary()   # success rate with its interval, pass@k, pass^k, cost, attribution

Datasets are data with a content hash; agents and graders are Python;
graders return Checks like every other judgement in the framework. Model
judges are shown but take no part in a verdict until calibrated against
people (annotate.agreement). Comparing with the committed baseline is paired
and noise-aware (stats.compare). Nothing here calls a model.
"""
from ipandora.core.eval import annotate, baseline, dataset, dialogue, report, stats
from ipandora.core.eval.dataset import Dataset, Task
from ipandora.core.eval.run import EvalRun, evaluate, selfcheck
from ipandora.core.eval.trial import AgentResult, Graded, Manifest, Trial

__all__ = ['dataset', 'dialogue', 'stats', 'baseline', 'annotate', 'report',
           'Dataset', 'Task', 'EvalRun', 'evaluate', 'selfcheck',
           'AgentResult', 'Graded', 'Manifest', 'Trial']

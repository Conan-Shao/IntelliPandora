# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : merge.py
@Time  : 2026-11-05

One report from many shards.

A suite split across CI jobs or machines produces one report.json per shard.
What a release decision needs is one verdict over all of them, and the two
ways to get that wrong are the ones this module exists to prevent:

- counting a case twice -- the same file listed in two shards, or a shard
  retried and both attempts uploaded -- which inflates the pass count;
- quietly picking one answer when the same case passed in one shard and
  failed in another. That is a finding (a flaky case, or shards that ran
  different code), so it is reported as a conflict, and the merged case takes
  the more severe outcome: a merge never turns red into green.

Merging works on report.json files only; it runs nothing and needs nothing
but the files. Each shard compared itself with the committed baseline when it
ran, and those comparisons are combined. A comparison with an earlier run is
not carried over -- each shard compared with its own previous run -- but the
merged report can be compared again (compare.attach) with an earlier merged
report.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

from ipandora.core.report import compare
from ipandora.core.report.builder import build_from_dict
from ipandora.core.report.model import BLAMES_SYSTEM_UNDER_TEST, ReportData, Status

SEVERITY = (Status.FAIL, Status.ERROR, Status.UNVERIFIED, Status.BLOCKED, Status.GAP,
            Status.SKIPPED, Status.PASS)
"""Most severe first. A conflict resolves to the first of these that occurred."""


def _rank(status: str) -> int:
    return SEVERITY.index(status) if status in SEVERITY else 0


def _unique(values) -> List:
    _seen, _out = set(), []
    for _value in values:
        _key = json.dumps(_value, sort_keys=True, ensure_ascii=False, default=str)
        if _key not in _seen:
            _seen.add(_key)
            _out.append(_value)
    return _out


def _triage(cases) -> Dict[str, Any]:
    """The run-level triage summary, recomputed from the merged cases."""
    _findings = [{'nodeid': _c.nodeid, 'category': _c.category, 'confidence': _c.confidence,
                  'reason': _c.reason, 'next_step': _c.next_step}
                 for _c in cases if _c.category]
    _by = {}
    for _f in _findings:
        _by[_f['category']] = _by.get(_f['category'], 0) + 1
    return {'headline': ', '.join('{} {}'.format(_n, _k) for _k, _n in sorted(_by.items()))
            or 'nothing to triage',
            'by_category': _by,
            'blames_system_under_test': sum(1 for _f in _findings
                                            if _f['category'] in BLAMES_SYSTEM_UNDER_TEST),
            'findings': _findings}


def _missing(baseline: Dict[str, Any], merged: ReportData) -> List[Dict[str, Any]]:
    """
    Cases the baseline holds as passing that no shard reported.

    One shard alone cannot tell -- it ran part of the suite by design. Only
    the union can, and only when the caller says the shards together are the
    whole suite the baseline describes. This is also what catches a shard
    whose report never arrived: its cases vanish, and vanished judgements are
    a weakening, not a smaller suite.
    """
    from ipandora.core.runner import inventory
    _present = {_c.nodeid for _c in merged.cases}
    # an excluded case (--exclude-flaky) is not in the report, but its shard said so
    _present |= {_c.get('nodeid') for _c in merged.judgement_changes
                 if _c.get('kind') == inventory.NOW_EXCLUDED}
    _out = []
    for _nodeid, _entry in sorted((baseline.get('cases') or {}).items()):
        if _nodeid in _present or _entry.get('state') != inventory.S_PASSED:
            continue
        _out.append(inventory.Finding(
            inventory.DELETED, _nodeid, before='用例不见了',
            note='基线里有 {} 条判定；合并的分片里都没有它'.format(
                len(_entry.get('claims', [])))).to_dict())
    return _out


def merge(shards: Sequence[Dict[str, Any]], sources: Sequence[str] = None,
          title: str = None, allow_mixed_env: bool = False,
          baseline: Dict[str, Any] = None) -> ReportData:
    """
    Merge report.json contents into one ReportData.

    :param shards:  the parsed report.json of each shard.
    :param sources: where each came from, for the report (a path, an artifact name).
    :param allow_mixed_env: shards normally ran against one environment;
                    merging dev and staging into one verdict is refused unless
                    this says it is intended.
    :param baseline: a judgement inventory (conf/judgements.json, loaded).
                    Passing it says "these shards are the whole suite": every
                    case it holds as passing that no shard reported is added
                    as a deleted -- weakening -- judgement change.

    Raises ValueError for an empty list, the same run given twice, or mixed
    environments.
    """
    if not shards:
        raise ValueError('nothing to merge')
    _sources = list(sources or [''] * len(shards))
    _reports = [build_from_dict(_s) for _s in shards]

    _ids = [_r.run_id for _r in _reports if _r.run_id]
    _twice = sorted({_i for _i in _ids if _ids.count(_i) > 1})
    if _twice:
        raise ValueError('the same run was given more than once: {}'.format(', '.join(_twice)))
    _envs = sorted({_r.env or '' for _r in _reports})
    if len(_envs) > 1 and not allow_mixed_env:
        raise ValueError('shards ran against different environments ({}); one verdict over '
                         'them is probably a mistake. Pass allow_mixed_env / --allow-mixed-env '
                         'if it is not'.format(', '.join(_e or 'default' for _e in _envs)))

    _cases, _order, _seen_in = {}, [], {}
    for _report in _reports:
        for _case in _report.cases:
            _key = _case.nodeid or _case.name
            _seen_in.setdefault(_key, []).append({'run_id': _report.run_id, 'status': _case.status})
            if _key not in _cases:
                _cases[_key] = _case
                _order.append(_key)
            elif _rank(_case.status) < _rank(_cases[_key].status):
                _cases[_key] = _case

    _conflicts = [{'nodeid': _k, 'status': _cases[_k].status, 'seen': _seen_in[_k]}
                  for _k in _order if len({_s['status'] for _s in _seen_in[_k]}) > 1]
    _duplicates = sum(len(_v) - 1 for _v in _seen_in.values())

    _merged = ReportData(
        title=title or _reports[0].title or 'IntelliPandora Test Report',
        run_id='merge-{}'.format(datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]),
        selector=' + '.join(_unique(_r.selector for _r in _reports if _r.selector)),
        env=_envs[0] if len(_envs) == 1 else ' + '.join(_e or 'default' for _e in _envs),
        generated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        # shards run side by side: the wall time is the slowest one
        duration=max(_r.duration for _r in _reports),
        cases=[_cases[_k] for _k in _order],
        coverage=_unique(_axis for _r in _reports for _axis in _r.coverage),
        collect_error='\n'.join('[{}] {}'.format(_r.run_id or _src or '?', _r.collect_error)
                                for _r, _src in zip(_reports, _sources) if _r.collect_error),
        baseline=' + '.join(_unique(_r.baseline for _r in _reports if _r.baseline)),
        judgement_changes=_unique(_c for _r in _reports for _c in _r.judgement_changes),
        shards=[{'run_id': _r.run_id, 'source': _src, 'selector': _r.selector, 'env': _r.env,
                 'generated': _r.generated, 'duration': _r.duration, 'cases': len(_r.cases),
                 'ok': _r.ok}
                for _r, _src in zip(_reports, _sources)],
        merge_conflicts=_conflicts,
        duplicates=_duplicates)
    _merged.triage = _triage(_merged.cases)

    _base = {}
    for _r in _reports:
        for _key, _ids in (_r.against_baseline or {}).items():
            _base.setdefault(_key, [])
            _base[_key].extend(_i for _i in _ids if _i not in _base[_key])
    # a case red in one shard and green in another is red after the merge;
    # it cannot also be listed as a new, passing case
    _failing = {_c.nodeid for _c in _merged.failures}
    if 'new_cases' in _base:
        _base['new_cases'] = [_i for _i in _base['new_cases'] if _i not in _failing]
    _merged.against_baseline = _base
    if baseline:
        _merged.judgement_changes = _merged.judgement_changes + _missing(baseline, _merged)
    return _merged


def merge_files(paths: Sequence[str], title: str = None, allow_mixed_env: bool = False,
                baseline: str = None) -> Tuple[ReportData, List[str]]:
    """
    merge() over report.json files (or run directories), and a baseline file
    if given. Returns the report and the paths read.
    """
    _data = [compare.load(_p) for _p in paths]
    _baseline = None
    if baseline:
        from ipandora.core.runner import inventory
        try:
            _baseline = inventory.load(baseline)
        except (OSError, ValueError) as exc:
            raise ValueError('cannot read baseline {}: {}'.format(baseline, exc))
        if _baseline is None:
            raise ValueError('baseline {} does not exist'.format(baseline))
    _report = merge(_data, sources=list(paths), title=title, allow_mixed_env=allow_mixed_env,
                    baseline=_baseline)
    if baseline and not _report.baseline:
        _report.baseline = baseline
    return _report, list(paths)

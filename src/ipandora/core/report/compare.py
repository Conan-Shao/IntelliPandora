# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : compare.py
@Time  : 2026-11-05

Comparing a run with one earlier run.

The framework is not a platform and keeps no run history of its own. "What
turned red" is answered first against the committed judgement baseline
(inventory.against), which is the same on every machine. This module adds
the comparison with one specific earlier run, when there is one:

1. a report.json the caller passes in (`ipandora run --compare-with`) -- in CI,
   typically the last report from the main branch, downloaded as an artifact;
2. otherwise the previous run of the same selector and environment in the
   local report archive (history.py), if this machine has one.

Neither found: no comparison, and the report says nothing about it rather
than comparing with something unrelated. The source is always recorded,
because a local cache exists only on the machine that made it.
"""
import json
import os
from typing import Any, Dict, Optional

from ipandora.core.report.model import ReportData, Status
from ipandora.utils.log import logger

ARGUMENT = 'argument'
LOCAL_CACHE = 'local_cache'

_FAILING = (Status.FAIL, Status.ERROR)


def load(path: str) -> Dict[str, Any]:
    """
    A report.json, or the report.json inside a run directory.

    Raises ValueError for anything that is not a report: comparing with the
    wrong file must not read as "nothing changed".
    """
    _file = os.path.join(path, 'report.json') if os.path.isdir(path) else path
    try:
        with open(_file, 'r', encoding='utf-8') as fh:
            _data = json.load(fh)
    except OSError as exc:
        raise ValueError('cannot read {}: {}'.format(_file, exc))
    except ValueError as exc:
        raise ValueError('{} is not JSON: {}'.format(_file, exc))
    if not isinstance(_data, dict) or not isinstance(_data.get('cases'), list):
        raise ValueError('{} is not an IntelliPandora report.json'.format(_file))
    return _data


def against(report: ReportData, previous: Dict[str, Any], source: str) -> Dict[str, Any]:
    """
    Which failures are new, still there, or gone, compared with `previous`.

    Only cases present in both runs can recover; a case missing from this run
    was not run, which says nothing about whether it is fixed.
    """
    _before = {str(_c.get('nodeid') or _c.get('name')): _c.get('status')
               for _c in previous.get('cases', []) if isinstance(_c, dict)}
    _newly, _still, _recovered = [], [], []
    for _case in report.cases:
        _was = _before.get(_case.nodeid)
        if _case.status in _FAILING:
            (_still if _was in _FAILING else _newly).append(_case.nodeid)
        elif _was in _FAILING and _case.status == Status.PASS:
            _recovered.append(_case.nodeid)
    return {'source': source,
            'run_id': str(previous.get('run_id', '')),
            'generated': str(previous.get('generated', '')),
            'selector': str(previous.get('selector', '')),
            'env': str(previous.get('env', '')),
            'newly_failing': _newly,
            'still_failing': _still,
            'recovered': _recovered}


def cached(report: ReportData, directory: str = None) -> Optional[Dict[str, Any]]:
    """
    The previous run of the same selector and environment in the local archive.

    Read-only: a missing or unreadable archive is no comparison, never an error.
    """
    from ipandora.core.report import history
    _root = directory or os.environ.get('IPANDORA_REPORTS_DIR', history.DEFAULT_REPORTS_DIR)
    if not os.path.isdir(_root):
        return None
    for _entry in history.load_index(_root):
        if _entry.get('run_id') == report.run_id:
            continue
        if (_entry.get('selector') or '') != (report.selector or '') \
                or (_entry.get('env') or '') != (report.env or ''):
            continue
        _run_dir = os.path.join(_root, str(_entry.get('run_id') or ''))
        if os.path.dirname(os.path.abspath(_run_dir)) != os.path.abspath(_root):
            continue    # an index entry must not point outside the archive
        try:
            return load(_run_dir)
        except ValueError as exc:
            logger.warning('skipping cached report %s: %s', _run_dir, exc)
    return None


def attach(report: ReportData, compare_with: str = None, cache: bool = True,
           directory: str = None) -> ReportData:
    """
    Fill `report.against_run`. Returns the report.

    :param compare_with: a report.json (or run directory) to compare with.
                         Wins over the local cache; unreadable is an error.
    :param cache:        fall back to the local archive when nothing is passed.
    :param directory:    the archive to look in; default as in history.py.
    """
    if compare_with:
        report.against_run = against(report, load(compare_with), ARGUMENT)
        return report
    if cache:
        _previous = cached(report, directory)
        if _previous is not None:
            report.against_run = against(report, _previous, LOCAL_CACHE)
    return report

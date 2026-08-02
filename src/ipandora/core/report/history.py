# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : history.py
@Time  : 2026-08-02

Every run keeps its report, and the runs are kept together.

A single report answers "what happened this time". Most of the questions people
actually bring to a test suite are comparative -- did this break just now, has
it been flaky all week, is the pass rate drifting -- and none of those can be
answered by a file that the next run overwrites.

So each run gets its own directory, and an index sits above them. The index
carries the one comparison worth computing at write time: which cases were
passing in the previous run and are failing in this one. That is the question
someone opens a CI report to answer, and it cannot be reconstructed later once
the earlier run is gone.
"""
import json
import os
from typing import Any, Dict, List, Optional

from ipandora.core.report.model import ReportData
from ipandora.core.report.render import to_html, write
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

DEFAULT_REPORTS_DIR = os.path.join(PathUtils().home_path, '.ipandora', 'reports')
INDEX_TEMPLATE = 'conf/static/history.html'
INDEX_FILE = 'index.json'

KEEP_REPORTS = 50
"""
How many runs stay on disk.

Reports carry request and response bodies, so they are not small. Fifty is
enough to see a week of CI and to catch a flake that shows up every few runs.
"""

MAX_TRACKED_CASES = 400
"""
Cap on the nodeids remembered per run for the regression comparison.

The index is read and rewritten on every run; letting it grow with a large
suite would turn a cheap append into a slow one.
"""


def reports_dir(directory: str = None) -> str:
    _dir = directory or os.environ.get('IPANDORA_REPORTS_DIR', DEFAULT_REPORTS_DIR)
    os.makedirs(_dir, exist_ok=True)
    return _dir


def _safe(run_id: str) -> str:
    # run_id is generated internally, but it becomes a directory name
    if not run_id or os.path.basename(run_id) != run_id or run_id.startswith('.'):
        raise ValueError('invalid run_id: {!r}'.format(run_id))
    return run_id


def _index_path(directory: str) -> str:
    return os.path.join(directory, INDEX_FILE)


def load_index(directory: str = None) -> List[Dict[str, Any]]:
    """Every archived run, newest first. Missing or corrupt index reads as empty."""
    _file = _index_path(reports_dir(directory))
    if not os.path.isfile(_file):
        return []
    try:
        with open(_file, 'r', encoding='utf-8') as fh:
            _entries = json.load(fh)
        return _entries if isinstance(_entries, list) else []
    except (OSError, ValueError) as exc:
        logger.warning('could not read report index: %s', exc)
        return []


def _entry_for(report: ReportData, previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    _failing = sorted(_c.nodeid for _c in report.failures)
    _was_failing = set((previous or {}).get('failing') or [])

    # Only meaningful against a run that actually recorded its cases; an empty
    # previous list means "no comparison", not "everything is new".
    _new = sorted(set(_failing) - _was_failing) if previous else []
    _fixed = sorted(_was_failing - set(_failing)) if previous else []

    return {
        'run_id': report.run_id,
        'title': report.title,
        'generated': report.generated,
        'selector': report.selector,
        'env': report.env,
        'duration': round(report.duration, 3),
        'ok': report.ok,
        'totals': report.totals,
        'pass_rate': report.pass_rate,
        'checks': report.check_totals,
        'coverage': [{'title': _g['title'], 'filled': _g['filled'], 'total': _g['total']}
                     for _g in report.coverage_matrix],
        'failing': _failing[:MAX_TRACKED_CASES],
        'new_failures': _new[:MAX_TRACKED_CASES],
        'fixed': _fixed[:MAX_TRACKED_CASES],
        'path': os.path.join(report.run_id, 'report.html'),
    }


def _prune(directory: str, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    _keep, _drop = entries[:KEEP_REPORTS], entries[KEEP_REPORTS:]
    import shutil
    for _entry in _drop:
        _dir = os.path.join(directory, str(_entry.get('run_id') or ''))
        if os.path.isdir(_dir) and os.path.dirname(_dir) == directory.rstrip(os.sep):
            shutil.rmtree(_dir, ignore_errors=True)
    return _keep


def archive(report: ReportData, directory: str = None) -> Dict[str, str]:
    """
    Write this run's report into the history and refresh the index.

    Returns the paths written. Failing to archive is logged, never raised: the
    run already happened and its verdict does not depend on being filed.
    """
    _root = reports_dir(directory)
    _run_dir = os.path.join(_root, _safe(report.run_id or 'run'))

    _paths = write(report, _run_dir)

    _entries = load_index(_root)
    _previous = _entries[0] if _entries else None
    _entries = [_e for _e in _entries if _e.get('run_id') != report.run_id]
    _entries.insert(0, _entry_for(report, _previous))
    _entries = _prune(_root, _entries)

    try:
        with open(_index_path(_root), 'w', encoding='utf-8') as fh:
            json.dump(_entries, fh, ensure_ascii=False, indent=2)
        _index_html = os.path.join(_root, 'index.html')
        with open(_index_html, 'w', encoding='utf-8') as fh:
            fh.write(render_index(_entries))
        _paths['index'] = _index_html
    except OSError as exc:
        logger.warning('could not update report index: %s', exc)

    logger.info('report archived: %s', _paths.get('html'))
    return _paths


def render_index(entries: List[Dict[str, Any]]) -> str:
    """The history page: every run, newest first, with what changed."""
    from ipandora.core.report.render import environment
    _rates = []
    for _entry in entries:
        _totals = _entry.get('totals') or {}
        _conclusive = (_totals.get('total', 0)
                       - _totals.get('skipped', 0) - _totals.get('blocked', 0)
                       - _totals.get('gap', 0) - _totals.get('error', 0))
        _rates.append(round(100.0 * _totals.get('passed', 0) / _conclusive, 1)
                      if _conclusive else None)
    return environment().get_template(INDEX_TEMPLATE).render(
        entries=entries, rates=_rates, count=len(entries))


def latest(directory: str = None) -> Optional[Dict[str, Any]]:
    _entries = load_index(directory)
    return _entries[0] if _entries else None

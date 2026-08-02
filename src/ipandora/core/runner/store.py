# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : store.py
@Time  : 2026-08-01
"""
import json
import os
from typing import List, Optional

from ipandora.core.runner.result import RunResult
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

DEFAULT_RUNS_DIR = os.path.join(PathUtils().home_path, '.ipandora', 'runs')
KEEP_RUNS = 50


def runs_dir() -> str:
    _dir = os.environ.get('IPANDORA_RUNS_DIR', DEFAULT_RUNS_DIR)
    os.makedirs(_dir, exist_ok=True)
    return _dir


def _path(run_id: str) -> str:
    # run_id is generated internally, but it lands in a filesystem path, so
    # refuse anything that could escape the directory.
    if not run_id or os.path.basename(run_id) != run_id or run_id.startswith('.'):
        raise ValueError('invalid run_id: {!r}'.format(run_id))
    return os.path.join(runs_dir(), '{}.json'.format(run_id))


def save(result: RunResult) -> str:
    """
    Persist the full run, tracebacks included.

    This is what makes a trimmed summary safe to return: the detail is not
    lost, it is one explicit lookup away.
    """
    _file = _path(result.run_id)
    try:
        with open(_file, 'w', encoding='utf-8') as fh:
            json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        # A run that cannot be archived is still a valid run; do not fail it.
        logger.warning('could not save run %s: %s', result.run_id, exc)
        return ''
    _prune()
    return _file


def load(run_id: str) -> Optional[RunResult]:
    _file = _path(run_id)
    if not os.path.isfile(_file):
        return None
    try:
        with open(_file, 'r', encoding='utf-8') as fh:
            return RunResult.from_dict(json.load(fh))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning('could not read run %s: %s', run_id, exc)
        return None


def list_runs(limit: int = 20) -> List[str]:
    """Run ids, newest first."""
    try:
        _files = [_f for _f in os.listdir(runs_dir()) if _f.endswith('.json')]
    except OSError:
        return []
    return [_f[:-5] for _f in sorted(_files, reverse=True)[:limit]]


def _prune(keep: int = KEEP_RUNS):
    try:
        _files = sorted((_f for _f in os.listdir(runs_dir()) if _f.endswith('.json')),
                        reverse=True)
    except OSError:
        return
    for _stale in _files[keep:]:
        try:
            os.remove(os.path.join(runs_dir(), _stale))
        except OSError:
            pass

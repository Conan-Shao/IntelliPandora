# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_history.py
@Time  : 2026-08-02
"""
import json
import os

import pytest

from ipandora.core.report import build
from ipandora.core.report.history import (KEEP_REPORTS, archive, latest, load_index,
                                          render_index)
from ipandora.core.runner.result import CaseResult, RunResult


def run_with(run_id, *cases):
    return RunResult(run_id=run_id, selector='s.py', cases=list(cases))


def case(nodeid, outcome='passed'):
    return CaseResult(nodeid=nodeid, outcome=outcome, message='boom')


def archived(tmp_path, run_id, *cases):
    return archive(build(run_with(run_id, *cases), include_triage=False),
                   directory=str(tmp_path))


class TestEachRunIsKept:
    def test_a_run_gets_its_own_directory(self, tmp_path):
        paths = archived(tmp_path, 'run-1', case('s.py::a'))
        assert os.path.isfile(paths['html']) and os.path.isfile(paths['json'])
        assert 'run-1' in paths['html']

    def test_a_later_run_does_not_overwrite_an_earlier_one(self, tmp_path):
        first = archived(tmp_path, 'run-1', case('s.py::a'))
        archived(tmp_path, 'run-2', case('s.py::a', 'failed'))
        assert os.path.isfile(first['html']), 'the earlier report was destroyed'
        assert len(load_index(str(tmp_path))) == 2

    def test_newest_is_first(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        archived(tmp_path, 'run-2', case('s.py::a'))
        assert [e['run_id'] for e in load_index(str(tmp_path))] == ['run-2', 'run-1']
        assert latest(str(tmp_path))['run_id'] == 'run-2'

    def test_re_archiving_a_run_replaces_its_entry(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        archived(tmp_path, 'run-1', case('s.py::a'))
        assert len(load_index(str(tmp_path))) == 1

    def test_old_runs_are_pruned_from_disk_not_just_the_index(self, tmp_path):
        for i in range(KEEP_REPORTS + 3):
            archived(tmp_path, 'run-{:03d}'.format(i), case('s.py::a'))
        assert len(load_index(str(tmp_path))) == KEEP_REPORTS
        # reports carry request and response bodies; an index-only prune leaks
        assert not os.path.isdir(os.path.join(str(tmp_path), 'run-000'))
        assert os.path.isdir(os.path.join(str(tmp_path), 'run-052'))


class TestWhatChangedSinceLastTime:
    """
    The comparison has to be computed while both runs are known. It cannot be
    reconstructed once the earlier one has been pruned, which is why it is
    stored rather than derived on read.
    """

    def test_a_newly_failing_case_is_named(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'), case('s.py::b'))
        archived(tmp_path, 'run-2', case('s.py::a'), case('s.py::b', 'failed'))
        assert load_index(str(tmp_path))[0]['new_failures'] == ['s.py::b']

    def test_a_case_that_was_already_failing_is_not_new(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::b', 'failed'))
        archived(tmp_path, 'run-2', case('s.py::b', 'failed'))
        entry = load_index(str(tmp_path))[0]
        assert entry['new_failures'] == [] and entry['failing'] == ['s.py::b']

    def test_a_fixed_case_is_named(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::b', 'failed'))
        archived(tmp_path, 'run-2', case('s.py::b'))
        assert load_index(str(tmp_path))[0]['fixed'] == ['s.py::b']

    def test_the_first_run_ever_claims_no_regressions(self, tmp_path):
        # everything is "new" against nothing, which would be a lie
        archived(tmp_path, 'run-1', case('s.py::b', 'failed'))
        assert load_index(str(tmp_path))[0]['new_failures'] == []

    def test_an_error_counts_as_failing(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        archived(tmp_path, 'run-2', case('s.py::a', 'error'))
        assert load_index(str(tmp_path))[0]['new_failures'] == ['s.py::a']


class TestTheIndexPage:
    def test_it_lists_every_run(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        archived(tmp_path, 'run-2', case('s.py::a', 'failed'))
        html = open(os.path.join(str(tmp_path), 'index.html'), encoding='utf-8').read()
        assert 'run-1' in html and 'run-2' in html

    def test_it_links_to_each_report(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        html = open(os.path.join(str(tmp_path), 'index.html'), encoding='utf-8').read()
        assert 'run-1/report.html' in html

    def test_an_empty_history_renders(self):
        assert 'ipandora run' in render_index([])

    def test_a_selector_cannot_inject_markup(self, tmp_path):
        result = run_with('run-1', case('s.py::a'))
        result.selector = '<img src=x onerror=alert(1)>'
        archive(build(result, include_triage=False), directory=str(tmp_path))
        html = open(os.path.join(str(tmp_path), 'index.html'), encoding='utf-8').read()
        assert '<img src=x' not in html and '&lt;img' in html


class TestArchivingNeverBreaksTheRun:
    def test_a_bad_run_id_is_refused_rather_than_escaping_the_directory(self, tmp_path):
        with pytest.raises(ValueError):
            archived(tmp_path, '../../etc', case('s.py::a'))

    def test_a_corrupt_index_reads_as_empty(self, tmp_path):
        (tmp_path / 'index.json').write_text('not json', encoding='utf-8')
        assert load_index(str(tmp_path)) == []
        # and the next archive repairs it rather than failing
        archived(tmp_path, 'run-1', case('s.py::a'))
        assert len(load_index(str(tmp_path))) == 1

    def test_the_index_stays_valid_json(self, tmp_path):
        archived(tmp_path, 'run-1', case('s.py::a'))
        json.loads((tmp_path / 'index.json').read_text(encoding='utf-8'))

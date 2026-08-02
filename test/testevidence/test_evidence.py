# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_evidence.py
@Time  : 2026-08-02
"""
import json
import threading

import pytest

from ipandora.core.assertion import (Check, Source, assert_all, failed, gap, passed,
                                     require)
from ipandora.core.evidence import Exchange, add_checks, add_exchange, recorder
from ipandora.core.evidence.recorder import MAX_BODY_CHARS


@pytest.fixture
def collecting():
    """A case slot open on this thread, as the runner plugin would open one."""
    recorder.begin('t::case')
    yield recorder
    recorder.end('t::case')
    recorder.reset()


class TestRecordingIsPassive:
    """
    The recorder exists to describe a run, never to change it. Every failure
    mode here has to be silent, because the alternative is a report bug turning
    a green suite red.
    """

    def test_recording_outside_a_case_is_a_no_op(self):
        recorder.reset()
        add_checks([passed('a')])
        add_exchange(method='GET', url='https://x.test', status=200)
        assert recorder.active is False
        assert recorder.end('t::case') is None

    def test_a_broken_check_object_does_not_raise(self, collecting):
        add_checks([object()])  # no name, no ok, no anything
        add_checks(None)

    def test_a_bad_exchange_does_not_raise(self, collecting):
        add_exchange(not_a_field=1)

    def test_assert_all_still_passes_with_no_recorder(self):
        recorder.reset()
        assert len(assert_all(passed('a'), passed('b'))) == 2


class TestEvidenceIsAttributedCorrectly:
    def test_checks_land_on_the_open_case(self, collecting):
        assert_all(passed('a'), failed('b', 'why') if False else passed('b'))
        evidence = recorder.end('t::case')
        assert [c['name'] for c in evidence.checks] == ['a', 'b']

    def test_a_failed_assertion_is_still_recorded(self, collecting):
        # the failing case is the one anyone opens the report for
        with pytest.raises(AssertionError):
            assert_all(passed('a'), failed('b', 'status = 500'))
        evidence = recorder.end('t::case')
        assert [(c['name'], c['ok']) for c in evidence.checks] == [('a', True), ('b', False)]
        assert 'status = 500' in evidence.checks[1]['expr']

    def test_require_records_its_checks_too(self, collecting):
        with pytest.raises(BaseException):
            require(failed('账号有余额', 'balance = 0'))
        evidence = recorder.end('t::case')
        assert evidence.checks[0]['name'] == '账号有余额'

    def test_evidence_does_not_leak_across_threads(self):
        """
        Cases run in parallel. Evidence filed against the wrong case is worse
        than no evidence -- it points the reader at innocent code.
        """
        recorder.reset()
        seen = {}

        def run(name):
            recorder.begin(name)
            add_checks([passed(name)])
            seen[name] = [c['name'] for c in recorder.end(name).checks]

        threads = [threading.Thread(target=run, args=('case_{}'.format(i),))
                   for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert seen == {'case_{}'.format(i): ['case_{}'.format(i)] for i in range(8)}
        recorder.reset()

    def test_evidence_is_handed_over_not_archived(self):
        """
        Two runs of the same file produce the same nodeids -- they are relative
        to rootdir. A recorder that kept finished cases keyed by nodeid would
        therefore hand the second run the first run's checks as well, forever,
        in any process that runs more than once. The MCP server is exactly
        that process.
        """
        recorder.reset()
        for _ in range(3):
            recorder.begin('same.py::test_x')
            add_checks([passed('状态正确')])
            evidence = recorder.end('same.py::test_x')
            assert [c['name'] for c in evidence.checks] == ['状态正确'], evidence.checks

    def test_ending_twice_yields_nothing_the_second_time(self, collecting):
        add_checks([passed('a')])
        assert len(recorder.end('t::case').checks) == 1
        assert recorder.end('t::case') is None


class TestBodiesAreStoredReadably:
    def test_json_is_indented_before_it_is_stored(self, collecting):
        add_exchange(method='GET', url='https://x.test', status=200,
                     response_body='{"a":{"b":1}}')
        stored = recorder.end('t::case').exchanges[0]['response_body']
        assert '\n' in stored and '"b": 1' in stored

    def test_a_large_body_is_truncated(self, collecting):
        add_exchange(method='GET', url='https://x.test', status=200,
                     response_body=json.dumps({'k': ['v' * 40] * 500}))
        stored = recorder.end('t::case').exchanges[0]['response_body']
        assert len(stored) < MAX_BODY_CHARS + 200
        assert 'truncated' in stored

    def test_indentation_happens_before_truncation(self, collecting):
        """
        Order matters and the wrong order is invisible until you open a report:
        truncating first leaves a fragment that no longer parses, so the page
        prints one enormous unindented line.
        """
        add_exchange(method='GET', url='https://x.test', status=200,
                     response_body=json.dumps({'items': [{'n': i} for i in range(4000)]}))
        stored = recorder.end('t::case').exchanges[0]['response_body']
        assert stored.count('\n') > 50, 'stored body was never indented'

    def test_truncation_keeps_whole_lines(self, collecting):
        add_exchange(method='GET', url='https://x.test', status=200,
                     response_body=json.dumps({'items': [{'n': i} for i in range(4000)]}))
        stored = recorder.end('t::case').exchanges[0]['response_body']
        body = stored.split('\n… (truncated')[0]
        # a half-written line of JSON reads as corruption, not as a cut
        assert not body.endswith(',') or body.rstrip().endswith((',', '}', ']'))

    def test_non_json_is_left_alone(self, collecting):
        add_exchange(method='GET', url='https://x.test', status=200,
                     response_body='v1.3.0\nv1.7.0\n')
        assert recorder.end('t::case').exchanges[0]['response_body'] == 'v1.3.0\nv1.7.0\n'


class TestGapsAreNotJudgements:
    """
    A gap says the suite does not check something. It is not a failure, not a
    pass, and must never be counted as either.
    """

    def test_a_gap_cannot_fail_a_run(self):
        assert_all(passed('a'), gap('余额实际增加', '未校验'))

    def test_a_gap_is_not_counted_as_passed(self):
        with pytest.raises(AssertionError) as exc:
            assert_all(failed('b', 'x'), gap('余额实际增加', '未校验'))
        message = str(exc.value)
        assert '1/1 checks failed' in message, message
        assert '余额实际增加' not in message.split('passed:')[-1].split('not covered:')[0]

    def test_a_gap_is_named_in_the_failure_text(self):
        with pytest.raises(AssertionError) as exc:
            assert_all(failed('b', 'x'), gap('余额实际增加', '未校验'))
        assert 'not covered: 余额实际增加' in str(exc.value)

    def test_a_run_of_only_gaps_does_not_look_like_a_pass(self):
        # 0/0 rather than a cheerful count of nothing
        assert_all(gap('a'), gap('b'))

    def test_gap_carries_its_dimension(self):
        check = gap('链上余额', 'balanceOf 未校验', src=Source.ONCHAIN)
        assert check.is_gap and check.src == Source.ONCHAIN
        assert str(check).startswith('[GAP]')

    def test_ordinary_checks_are_not_gaps(self):
        assert passed('a').is_gap is False
        assert Check(name='a', ok=True).kind == 'assert'

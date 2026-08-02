# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_global_state.py
@Time  : 2026-08-01
"""
import threading

import pytest

from ipandora.core.base.classwrap.multihandle import MultiHandle
from ipandora.core.schedule.runtime import Runtime


@pytest.fixture(autouse=True)
def clean_case_state():
    Runtime.Case.clear()
    yield
    Runtime.Case.clear()


class TestCaseStepsAreThreadLocal:
    """
    Steps used to live in a process-global dict keyed by a single
    process-global case name, so under any concurrency every thread's steps
    landed under whichever name was set last.
    """

    def test_threads_do_not_see_each_others_steps(self):
        # Deterministic interleaving rather than a race: B sets its case name
        # in between A setting its own and A recording. With a process-global
        # name, A's step lands under B's case.
        a_named, b_named = threading.Event(), threading.Event()
        results = {}

        def worker_a():
            Runtime.Case.cur_case_name = 'case_a'
            a_named.set()
            b_named.wait(timeout=5)
            Runtime.Case.steps = ['step_from_a']
            # Ask for it by name. Reading back via `steps` would pass even when
            # the step landed under B's name, because the read follows the same
            # (wrong) current name that the write did.
            results['under_case_a'] = Runtime.Case.drain_steps('case_a')

        def worker_b():
            a_named.wait(timeout=5)
            Runtime.Case.cur_case_name = 'case_b'
            b_named.set()

        threads = [threading.Thread(target=worker_a), threading.Thread(target=worker_b)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert results['under_case_a'] == [['step_from_a']], \
            "thread A's step was filed under another thread's case name"

    def test_many_threads_keep_their_own_steps(self):
        results = {}
        started = threading.Barrier(4)

        def record(idx):
            started.wait()
            Runtime.Case.cur_case_name = 'case_{}'.format(idx)
            for step in range(5):
                Runtime.Case.steps = ['step_{}_{}'.format(idx, step)]
            results[idx] = Runtime.Case.steps

        threads = [threading.Thread(target=record, args=(i,)) for i in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        for idx, steps in results.items():
            assert len(steps) == 5, 'thread {} lost steps: {}'.format(idx, steps)
            assert all(s[0].startswith('step_{}_'.format(idx)) for s in steps), \
                "thread {} picked up another thread's steps".format(idx)

    def test_case_name_is_per_thread(self):
        Runtime.Case.cur_case_name = 'main'
        seen = {}

        def other():
            Runtime.Case.cur_case_name = 'worker'
            seen['worker'] = Runtime.Case.cur_case_name

        thread = threading.Thread(target=other)
        thread.start()
        thread.join()

        assert seen['worker'] == 'worker'
        assert Runtime.Case.cur_case_name == 'main'

    def test_case_list_is_per_thread(self):
        Runtime.Case.case_list.append('main-item')
        seen = {}

        def other():
            seen['len'] = len(Runtime.Case.case_list)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join()

        assert seen['len'] == 0
        assert Runtime.Case.case_list == ['main-item']


class TestStepsReadIsNotDestructive:
    """Reading a value must not consume it -- the same defect as len() calling
    the consuming fetch_all() in the response handler."""

    def test_reading_twice_gives_the_same_steps(self):
        Runtime.Case.cur_case_name = 'c1'
        Runtime.Case.steps = ['a']
        Runtime.Case.steps = ['b']
        assert Runtime.Case.steps == [['a'], ['b']]
        assert Runtime.Case.steps == [['a'], ['b']]

    def test_drain_takes_and_clears(self):
        Runtime.Case.cur_case_name = 'c1'
        Runtime.Case.steps = ['a']
        assert Runtime.Case.drain_steps() == [['a']]
        assert Runtime.Case.steps == []

    def test_drain_can_target_another_case(self):
        Runtime.Case.cur_case_name = 'c1'
        Runtime.Case.steps = ['a']
        Runtime.Case.cur_case_name = 'c2'
        assert Runtime.Case.drain_steps('c1') == [['a']]

    def test_steps_of_unknown_case_is_empty(self):
        Runtime.Case.cur_case_name = 'never-recorded'
        assert Runtime.Case.steps == []

    def test_mutating_the_returned_list_does_not_corrupt_the_store(self):
        Runtime.Case.cur_case_name = 'c1'
        Runtime.Case.steps = ['a']
        Runtime.Case.steps.append(['injected'])
        assert Runtime.Case.steps == [['a']]


class TestRuntimeReset:
    """
    Config values memoise process-wide on first read, so an override in one
    test leaked into every test after it.
    """

    def test_reset_restores_a_default(self):
        assert Runtime.Http.verify is True
        Runtime.Http.verify = False
        assert Runtime.Http.verify is False
        Runtime.reset('Http')
        assert Runtime.Http.verify is True

    def test_reset_restores_numeric_defaults(self):
        original = Runtime.Http.connect_timeout
        Runtime.Http.connect_timeout = 999
        Runtime.reset('Http')
        assert Runtime.Http.connect_timeout == original

    def test_reset_all_sections(self):
        Runtime.Http.verify = False
        Runtime.Ai.provider = 'bogus'
        Runtime.reset()
        assert Runtime.Http.verify is True
        assert Runtime.Ai.provider == 'mock'

    def test_reset_rejects_unknown_section(self):
        with pytest.raises(ValueError, match='unknown Runtime section'):
            Runtime.reset('NoSuchSection')

    def test_known_sections_were_snapshotted(self):
        assert {'Http', 'Ai', 'Mcp', 'Mysql', 'Email'} <= set(Runtime._config_defaults)

    def test_threading_local_is_not_snapshotted(self):
        # restoring a threading.local would break per-thread isolation
        assert '_local' not in Runtime._config_defaults.get('Case', {})


class _Batcher(MultiHandle):
    """Records every batch that gets flushed, so tests can count items."""

    def __init__(self):
        self.flushed = []
        self._flushed_lock = threading.Lock()
        super().__init__()

    def handleItem(self):
        pass

    def uploadItem(self, force=False):
        with self._lock:
            if force:
                _items, self._data_list = self._data_list, []
            elif len(self._data_list) >= self.max_items_upload:
                _items = self._data_list[:self.max_items_upload]
                self._data_list = self._data_list[self.max_items_upload:]
            else:
                return False
        if _items:
            with self._flushed_lock:
                self.flushed.extend(_items)
        return True


class TestMultiHandleBuffering:
    """
    The buffer was a class attribute shared by every instance and mutated from
    both the producer and the background thread with no lock.
    """

    def test_buffer_is_per_instance(self):
        a, b = _Batcher(), _Batcher()
        try:
            a.put({'i': 1})
            assert b.current_item is None
            assert a.current_item == {'i': 1}
        finally:
            a.stop()
            b.stop()

    def test_concurrent_puts_lose_nothing(self):
        batcher = _Batcher()
        batcher.max_items_upload = 20  # let the background thread flush too
        threads_count, per_thread = 4, 50
        try:
            def produce(idx):
                for n in range(per_thread):
                    batcher.put({'t': idx, 'n': n})

            threads = [threading.Thread(target=produce, args=(i,))
                       for i in range(threads_count)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            batcher.uploadItem(force=True)

            # every produced item must appear exactly once across all batches
            assert len(batcher.flushed) == threads_count * per_thread
            assert len({(i['t'], i['n']) for i in batcher.flushed}) == \
                threads_count * per_thread
        finally:
            batcher.stop()

    def test_force_flush_drains_the_buffer(self):
        batcher = _Batcher()
        batcher.max_items_upload = 10 ** 6
        try:
            batcher.put({'i': 1})
            batcher.put({'i': 2})
            batcher.uploadItem(force=True)
            assert batcher.current_item is None
        finally:
            batcher.stop()

    def test_thread_is_stoppable(self):
        batcher = _Batcher()
        assert batcher.is_alive()
        batcher.stop()
        batcher.join(timeout=5)
        assert not batcher.is_alive()

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : multihandle.py
@Time  : 2024-04-19
"""
import atexit
import logging
from abc import ABCMeta, abstractmethod
from threading import Event, Lock, Thread
from typing import Generic, List, TypeVar, Union

from ipandora.core.schedule.runtime import Runtime

logger = logging.getLogger(__name__)

IV = TypeVar('IV')
RV = TypeVar('RV')

_instances = []
_instances_lock = Lock()
_atexit_registered = False


def init():
    """
    Flush every batcher at interpreter exit.

    Guarded because this is called from two package __init__ modules, which
    previously registered the same handler twice.
    """
    global _atexit_registered
    with _instances_lock:
        if _atexit_registered:
            return
        _atexit_registered = True

    def inner():
        for _instance in list(_instances):
            try:
                _instance.uploadItem(force=True)
            except Exception as exc:  # noqa: BLE001 - never break interpreter shutdown
                logger.debug('flush at exit failed: %s', exc)

    atexit.register(inner)


class MultiHandle(Generic[IV], Thread, metaclass=ABCMeta):
    """
    Batches items on a background thread.

    The buffer is per-instance and guarded by a lock. It used to be a
    class-level list shared by every instance and mutated from both the
    producer and the background thread with no synchronisation, so concurrent
    put/flush could drop items.

    NOTE: the actual upload is commented out below, so today this only
    batches and discards. The concurrency is fixed regardless -- broken
    threading that happens to be dormant is still broken.
    """

    report_item_path = ''

    timeout = 5
    max_items_upload = 20
    flush_interval = 1.0

    def __init__(self):
        _name = 'multi-upload-{}'.format(id(self))
        super(MultiHandle, self).__init__(name=_name)
        self._data_list = []  # type:List[IV]
        self._lock = Lock()
        self._stopped = Event()
        self._need_upload_item_on_run = True
        self.daemon = True
        with _instances_lock:
            _instances.append(self)
        self.start()

    def run(self) -> None:
        # Event.wait rather than sleep in a `while True`: this thread is now
        # stoppable, and stop() takes effect immediately instead of after the
        # current sleep expires.
        while not self._stopped.wait(self.flush_interval):
            try:
                self.uploadItem()
            except Exception as exc:  # noqa: BLE001 - a batcher must not kill its thread
                logger.debug('background flush failed: %s', exc)

    def stop(self):
        """Stop the background thread and flush what is buffered."""
        self._stopped.set()
        self.uploadItem(force=True)

    @property
    def current_item(self) -> IV:
        with self._lock:
            return self._data_list[-1] if self._data_list else None

    @abstractmethod
    def handleItem(self):
        pass

    def put(self, item: IV = None):
        with self._lock:
            self._data_list.append(item)
        self.handleItem()
        self.uploadItem()

    def uploadItem(self, force=False) -> Union[RV]:
        """
        Upload a batch of results.

        :param force: flush everything buffered rather than waiting for a
                      full batch.
        """
        if not self._need_upload_item_on_run and not force:
            return False

        # Take the batch under the lock, then do the (slow) upload outside it.
        with self._lock:
            if force:
                _items, self._data_list = self._data_list, []
            elif len(self._data_list) >= self.max_items_upload:
                _items = self._data_list[:self.max_items_upload]
                self._data_list = self._data_list[self.max_items_upload:]
            else:
                return False

        if not _items:
            return False

        try:
            # if _items:
            #     _re = pandora_user.model.post(
            #         self.report_item_path, json=_items)
            #
            #     if _re and 200 <= _re.response.status_code < 400:
            #         return _re
            #     else:
            #         self._need_upload_item_on_run = False
            pass
        except Exception as e:  # noqa: BLE001 - reporting must not fail a test run
            self._need_upload_item_on_run = False
            logger.info(e)

        return False


class UploadApiInfo(MultiHandle):

    @property
    def report_item_path(self):
        # Resolved per access, not at class-definition time: the report host
        # comes from config and may be unset or overridden after import.
        return (Runtime.Host.report_host or '') + '/api/data/upload'

    def handleItem(self):
        pass

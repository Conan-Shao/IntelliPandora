# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : multihandle.py
@Time  : 2024-04-19
"""
import atexit
import logging
import time
from abc import ABCMeta, abstractmethod
from threading import Thread
from typing import TypeVar, List, Generic, Union
# from pandora.core.runtime.User import pandora_user
from ipandora.core.schedule.runtime import Runtime

logger = logging.getLogger(__name__)

IV = TypeVar('IV')
RV = TypeVar('RV')


def init():
    def inner():
        for _e_i in getattr(MultiHandle, '_instance_list', []):
            _e_i.uploadItem(force=True)

    atexit.register(inner)


class MultiHandle(Generic[IV], Thread, metaclass=ABCMeta):
    __data_list = []  # type:List[IV]

    report_item_path = ''

    timeout = 5
    max_items_upload = 20

    __need_upload_item_on_run = True

    _instance_list = []

    def __new__(cls, *args, **kwargs):
        _instance = super(MultiHandle, cls).__new__(cls, *args, **kwargs)
        cls._instance_list.append(_instance)
        return _instance

    def __init__(self):
        _name = 'multi-upload-{}'.format(id(self))
        super(MultiHandle, self).__init__(name=_name)
        self.daemon = True
        self.start()

    def run(self) -> None:
        while True:
            self.uploadItem()
            time.sleep(1)

    @property
    def current_item(self) -> IV:
        return self.__data_list[-1] if self.__data_list else None

    @abstractmethod
    def handleItem(self):
        pass

    def put(self, item: IV = None):
        self.__data_list.append(item)
        self.handleItem()
        self.uploadItem()

    def uploadItem(self, force=False) -> Union[RV]:
        """
        upload test case result
        :param force:
        :return:
        """

        if not self.__need_upload_item_on_run and not force:
            return False
        _items = []

        try:
            if force:
                _items = self.__data_list
                self.__data_list = []
            elif len(self.__data_list) >= self.max_items_upload:
                _items = self.__data_list[:self.max_items_upload]

                self.__data_list = self.__data_list[self.max_items_upload:]

            # if _items:
            #     _re = pandora_user.model.post(
            #         self.report_item_path, json=_items)
            #
            #     if _re and 200 <= _re.response.status_code < 400:
            #         return _re
            #     else:
            #         self.__need_upload_item_on_run = False

        except Exception as e:
            self.__need_upload_item_on_run = False
            logger.info(e)

        return False


class UploadApiInfo(MultiHandle):
    report_item_path = Runtime.Host.report_host + '/api/data/upload'

    def handleItem(self):
        pass

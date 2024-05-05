# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : responsehandler.py
@Time  : 2024-04-19
"""
import copy
import json
import logging
from collections import namedtuple
from requests.models import Response
from ipandora.core.protocol.http.model.interface.responseinterface import HttpResponseInterface
from ipandora.utils.match import DictMatcher

logger = logging.getLogger(__name__)


def is_json(string):
    try:
        json.loads(string)
    except (ValueError, TypeError):
        return False
    return True


def json_to_obj(j):
    def handle(data):
        if isinstance(data, dict):
            # if any(str(e).isdigit() or '/' in str(e) for e in data.keys()):
            #     return data
            try:
                return namedtuple('Data', data.keys())(*data.values())
            except Exception as e:
                logger.debug(e)
                return data
        else:
            return data

    # todo need to optimize response handle

    # make sure response json can be decode to utf-8
    # maybe a png stream
    try:
        j = j.decode('utf-8') if isinstance(j, bytes) else j
    except Exception as e:
        logger.debug(e)
        return namedtuple('Data', 'data')(data=j)

    # handle json response, make sure the response stream is json
    if not is_json(j):
        return j

    # the response stream maybe json
    try:
        return json.loads(j, object_hook=handle)
    except Exception as e:
        logger.debug(e)
        return json.loads(j)


def contain_dict(subset: dict = None, superset: dict = None) -> bool:
    return subset.items() <= superset.items()


def nice_index(index=0, length=0):
    assert isinstance(index, int) and isinstance(length,
                                                 int), u'index {}, length {} must be int.'.format(
        index, length)
    assert length > 0, u'length {} must be > 0'.format(length)
    if index >= 0:
        _index = length - 1 if index >= length else index
    else:
        _index = index + length if index + length >= 0 else 0

    return _index


def get_item_by_index(ori_list=None, index=0):
    ori_list = ori_list or []

    try:
        if isinstance(ori_list, list):
            return ori_list[index]
        else:
            return ori_list
    except IndexError:
        # logger.warning(u'get item from list indexError index {}/list {}'.format(index, ori_list))
        return []


class Tag(object):
    tag_dp = 'parallel'
    tag_t2 = 't2'
    tag_yjb = 'yjb'
    tag_default = 'default'

    def __init__(self, tag=None):
        self.tag = tag or self.tag_default

    @property
    def is_dp(self):
        return self.tag == self.tag_dp

    @property
    def is_t2(self):
        return self.tag == self.tag_t2

    @property
    def is_yjb(self):
        return self.tag == self.tag_yjb

    @property
    def is_default(self):
        return self.tag == self.tag_default

    def dp(self):
        self.tag = self.tag_dp
        return self

    def t2(self):
        self.tag = self.tag_t2
        return self

    def yjb(self):
        self.tag = self.tag_yjb
        return self


class ResponseHandler(HttpResponseInterface):

    def __init__(self, tag: Tag = Tag().dp()):
        self.result = None
        self._index = 0
        self.tag = tag

        self._origin = None
        self._origin_fetched = None
        self._target = None

        self._response = None

    @property
    def origin(self):
        return self._origin

    @origin.setter
    def origin(self, origin):
        self._origin = origin

    @property
    def response(self) -> Response:
        return self._response

    @response.setter
    def response(self, response: Response):
        self._response = response

    @property
    def target(self):
        # get target data
        if self._target is None:
            # get all data from origin data
            if self.origin_fetched is None:
                _all = []
                for _data in self._valid_data():
                    _all.append(_data)
                self.origin_fetched = _all
            self._target = copy.deepcopy(self.origin_fetched)
        return self._target

    @target.setter
    def target(self, value):
        self._target = value

    @property
    def origin_fetched(self):
        return self._origin_fetched

    @origin_fetched.setter
    def origin_fetched(self, value):
        self._origin_fetched = value

    @property
    def error_code(self):
        return '999999'

    @property
    def code(self):
        if hasattr(self.origin, 'code'):
            return self.origin.code
        elif isinstance(self.origin, dict):
            return self.origin.get('code', self.error_code)
        else:
            logger.info('can not parse response code by {}'.format(self.origin))
            return self.error_code

    @property
    def data(self):
        return self._valid_data()

    def inject(self, response: Response, content: str = ''):
        self.response = response
        self.origin = json_to_obj(content or self.response.content)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.response, '__exit__'):
            self.response.__exit__(exc_type, exc_val, exc_tb)

    def filter(self, **kwargs):
        """
        super filter data, support logic compare
        expression: gt, =, in, contains, startWith

        eg:
        1.field more than target value
            object.superFilter(stock_type='0', enable_amount={'$gt':'1000000'}).fetchOne()

        2.field in target list
            object.superFilter(stock_type={'$in':['0','T','c']}).fetchOne()

        3.field contain target str
            object.superFilter(stock_name={'$contains':'st'}).fetchOne()

        4.field start with target str
            object.superFilter(stock_code={'$startWith':'300'}).fetchOne()

        5.field equal target str
            object.superFilter(stock_name='xxx').fetchOne()

        :param kwargs:
        :return:
        """
        _f = self.target or self.origin_fetched
        _n = []
        for item in _f:
            # check item valid
            if DictMatcher(superset=getattr(item, '_asdict')()) \
                    .condition(condition=kwargs).match():
                _n.append(item)
        self._update_target_data(data=_n)
        return self

    def _valid_data(self):
        if hasattr(self.origin, 'data'):
            _result = getattr(self.origin, 'data')
        elif hasattr(self.origin, 'result'):
            _result = getattr(self.origin, 'result')
        else:
            _result = self.origin

        return _result #if isinstance(_result, list) else [_result]

    def _update_target_data(self, data=None):
        if data is not None:
            self.target = data
        return self

    def fetch_all(self):
        # get all data from origin data
        _target = self.target
        self.target = None
        if not isinstance(_target, list):
            _target = [_target]
        return _target

    def fetch_one(self) -> namedtuple or list:
        return get_item_by_index(ori_list=self.fetch_all(), index=0)

    def fetch_last(self):
        return get_item_by_index(ori_list=self.fetch_all(), index=-1)

    def fetch(self, index=0):
        _valid_data = self._valid_data()

        if not _valid_data:
            return []

        return _valid_data[nice_index(index=index, length=len(_valid_data))]

    def __iter__(self):
        return self

    def __len__(self):
        return len(self.fetch_all())

    def __next__(self):
        if self._index >= len(self.fetch_all()):
            # reset index
            self._index = 0
            raise StopIteration(u'stop iter test')
        self._index += 1
        return self.fetch_all()[self._index - 1]

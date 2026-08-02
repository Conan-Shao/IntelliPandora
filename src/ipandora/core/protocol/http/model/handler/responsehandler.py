# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : responsehandler.py
@Time  : 2024-04-19
"""
import copy
import json
import logging
from requests.models import Response
from ipandora.core.protocol.http.model.interface.responseinterface import HttpResponseInterface
from ipandora.utils.match import DictMatcher

logger = logging.getLogger(__name__)


class JsonObject(dict):
    """
    A JSON object that supports both attribute and key access.

    This replaces the previous namedtuple conversion, which had to fall back
    to a plain dict whenever a JSON key was a Python keyword or contained a
    dash -- so the *type* of a parsed response depended on the payload's key
    names, and any downstream code doing `._asdict()` blew up on exactly those
    responses. One type for every object removes that whole class of bug.

        resp.data.origin        # attribute access, as before
        resp.data['x-req-id']   # keys a namedtuple could never hold
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            _available = ', '.join(sorted(map(str, self.keys()))[:8]) or '<empty>'
            raise AttributeError(
                'response object has no field {!r} (present: {})'.format(name, _available))

    def __setattr__(self, name, value):
        self[name] = value

    def _asdict(self):
        """namedtuple-compatible, so existing callers keep working."""
        return dict(self)


def is_json(string):
    try:
        json.loads(string)
    except (ValueError, TypeError):
        return False
    return True


def json_to_obj(j):
    """
    Parse a response body into JsonObject/list/scalar.

    Non-JSON bodies are returned as-is (str for text, bytes for binary) rather
    than being wrapped in a fake object -- the caller can tell what it got.
    """
    if isinstance(j, bytes):
        try:
            j = j.decode('utf-8')
        except UnicodeDecodeError as e:
            # binary payload (an image, a download); hand it back untouched
            logger.debug('response body is not utf-8, returning raw bytes: %s', e)
            return j

    if not isinstance(j, str):
        # already-parsed data
        return j

    try:
        return json.loads(j, object_hook=JsonObject)
    except (ValueError, TypeError):
        # not JSON: HTML error page, plain text, empty body
        return j


def as_item_list(value):
    """
    Normalise parsed data into a list of items.

    The old code iterated whatever it got, which meant a single object was
    torn into its field values ({'id':1,'name':'a'} became [1,'a']), a string
    shredded into characters, and null or a scalar raised TypeError. Only a
    list is already a list of items; everything else is one item -- except
    null, which is no items.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple) and not hasattr(value, '_fields'):
        # a plain tuple is a sequence; a namedtuple is a single record
        return list(value)
    return [value]


def as_mapping(item):
    """
    Field mapping for an item, or None when it has no fields.

    Accepts JsonObject, plain dicts and namedtuples so filtering behaves the
    same whatever the payload looked like.
    """
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, '_asdict'):
        return item._asdict()
    return None


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
        # None, not []: asking for one item and getting an empty list back
        # reads as "here is your item, it is a list", which it is not.
        return None


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
            if self.origin_fetched is None:
                self.origin_fetched = as_item_list(self._valid_data())
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
        _f = self.target or self.origin_fetched or []
        _n = []
        for item in _f:
            _mapping = as_mapping(item)
            if _mapping is None:
                # scalars and strings carry no fields to filter on. Skipping
                # beats the previous AttributeError, which fired on exactly
                # the payloads json_to_obj used to degrade to plain dicts.
                logger.debug('filter skipped non-object item: %r', item)
                continue
            if DictMatcher(superset=_mapping).condition(condition=kwargs).match():
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

    def _current_items(self) -> list:
        """Items currently selected, without consuming the filter."""
        return as_item_list(self.target)

    def fetch_all(self) -> list:
        # Consuming: clears any applied filter so the next query starts from
        # the full response again.
        _target = self._current_items()
        self.target = None
        return _target

    def fetch_one(self):
        return get_item_by_index(ori_list=self.fetch_all(), index=0)

    def fetch_last(self):
        return get_item_by_index(ori_list=self.fetch_all(), index=-1)

    def fetch(self, index=0):
        _items = as_item_list(self._valid_data())

        if not _items:
            return None

        return _items[nice_index(index=index, length=len(_items))]

    def __iter__(self):
        return self

    def __len__(self):
        # Non-consuming: len() must not have side effects, and the old version
        # called fetch_all(), which cleared the filter every time it ran.
        return len(self._current_items())

    def __next__(self):
        _items = self._current_items()
        if self._index >= len(_items):
            # reset index
            self._index = 0
            raise StopIteration(u'stop iter test')
        self._index += 1
        return _items[self._index - 1]

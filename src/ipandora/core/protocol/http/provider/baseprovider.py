# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baseprovider.py
@Time  : 2024-04-19
"""
import inspect
from abc import ABCMeta, abstractmethod
from functools import update_wrapper
from ipandora.core.base.data.markdata import MarkData


class BaseProvider(metaclass=ABCMeta):
    mark_tag = '__pandora_mark__'

    def __init__(self, method='', need_mark=True):
        self.method = method
        self.decorator = None
        self.path = ''

        self.args = tuple()
        self.kwargs = dict()
        self.need_mark = need_mark

    def __call__(self, path=''):
        self.path = path
        return self.hook

    @abstractmethod
    def handle(self, path: str = '', mark: MarkData = '', method: str = '',
               params: dict = None, ori_params: dict = None):
        pass

    def hook(self, f):
        def decorator(*args, **kwargs):
            _mark_tag = '__pandora_mark__'

            _mark = getattr(self.decorator, _mark_tag,
                            getattr(f, _mark_tag, None))

            # if self.need_mark and not _mark:
            #     raise ValueError('must use @api.mark() for each api request')

            # need a default mark object here
            _mark = _mark or MarkData()
            _mark.doc = f.__doc__
            _parse_params = f(*args, **kwargs)

            if _parse_params and not isinstance(_parse_params, dict):
                raise ValueError('this decorator @api.http or @api.socket '
                                 'need function/method return dict or None')

            # set origin args and kwargs
            self.ori_args = args
            self.ori_kwargs = kwargs

            return self.handle(
                path=self.path, method=self.method, params=_parse_params,
                ori_params=self.handle_arg_params(f, *args, **kwargs),
                mark=_mark)

        self.decorator = update_wrapper(decorator, f)
        return self.decorator

    @staticmethod
    def handle_arg_params(f, *args, **kwargs):
        argspec = inspect.getfullargspec(f)
        ori_kwargs = {}

        # get func key-value parameters
        keys = argspec.args
        defaults = list(argspec.defaults) if argspec.defaults else []
        kwonlydefaults = argspec.kwonlydefaults

        if len(keys) < 1:
            pass
        elif keys[0] == 'self':
            keys = keys[1:]
            args = args[1:]

        if len(keys) > len(defaults):
            if defaults:
                for _ in range(len(defaults)):
                    ori_kwargs.update({keys.pop(): defaults.pop()})
            for k, v in zip(keys, list(args)):
                ori_kwargs.update({k: v})

        if kwonlydefaults and isinstance(kwonlydefaults, dict):
            ori_kwargs.update(kwonlydefaults)
        ori_kwargs.update(kwargs)
        return ori_kwargs

# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : importpath.py
# @Time  : 2024-04-17
import importlib
import importlib.util
from importlib.machinery import ModuleSpec, SourceFileLoader
from os.path import basename, isabs
from types import ModuleType
from typing import Union, Optional


class ImportPath(object):

    def __init__(self, path=None):
        self._path = path

        self._module = None  # type:Optional[ModuleType]
        self._spec = None  # type:Optional[ModuleSpec]
        self.importModuleByFilePath()

    @property
    def file_name(self):
        return basename(self._path).split('.')[0]

    @property
    def module_name(self):
        return 'ipandora.core.initial.{}'.format(self.file_name)

    @property
    def spec(self) -> ModuleSpec:
        if not self._spec:
            self._spec = importlib.util \
                .spec_from_file_location(self.module_name, self._path)
        return self._spec

    @property
    def module(self) -> ModuleType:
        if not self._module:
            self._module = importlib.util.module_from_spec(self.spec)
        return self._module

    @property
    def loader(self) -> SourceFileLoader:
        return self.spec.loader

    @property
    def get_source(self) -> str:
        return self.loader.get_source(self.module_name)

    @property
    def path(self):
        return self.loader.path

    def importModuleByFilePath(self) -> Union[ModuleType, bool]:
        # make sure path is a valid absolute python file path
        if not self._path \
                or not isabs(self._path) \
                or not self._path.endswith('.py'):
            return False

        # load py file to module
        self.spec.loader.exec_module(self.module)

    def valid(self):
        return self.spec and self.module

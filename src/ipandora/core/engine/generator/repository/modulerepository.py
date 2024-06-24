# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : modulerepository.py
@Time  : 2024-05-23
"""
from typing import List
from ipandora.core.engine.generator.model.data.case import (Module, ModuleUpdate)
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class ModuleRepository(BaseRepository):

    def get_modules(self) -> List[Module]:
        query = "SELECT * FROM Modules WHERE Status = 1"
        rows = self.execute_query(query)
        return self.filter_fields(rows, Module)
        # return [Module(**row) for row in rows] if rows else []

    def insert_module(self, module: Module) -> int:
        query, values = self.generate_insert_query(module, "Module")
        return self.execute_insert(query, tuple(values))

    def update_module(self, module_update: ModuleUpdate) -> int:
        query, values = self.generate_update_query(module_update, "Module",
                                                   "ModuleID")
        return self.execute_update(query, tuple(values))


# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : submodulerepository.py
@Time  : 2024-05-25
"""
from typing import List
from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import Submodule, SubmoduleUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class SubmoduleRepository(BaseRepository):

    def get_submodules(self) -> List[Submodule]:
        query = "SELECT * FROM Submodules"
        rows = self.execute_query(query)
        return [Submodule(**row) for row in rows] if rows else []

    def get_submodules_by_module_id(self, module_id: int) -> List[Submodule]:
        query = "SELECT * FROM Submodules WHERE ModuleID = %s"
        rows = self.execute_query(query % module_id)
        return [Submodule(**row) for row in rows] if rows else []

    def insert_submodule(self, submodule: Submodule) -> int:
        query, values = self.generate_insert_query(submodule, "Submodules")
        return self.execute_insert(query, tuple(values))

    def update_submodule(self, submodule_update: SubmoduleUpdate) -> int:
        query, values = self.generate_update_query(submodule_update, "Submodules", "SubmoduleID")
        return self.execute_update(query, tuple(values))

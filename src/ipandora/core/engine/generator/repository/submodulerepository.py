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
        query = "SELECT * FROM Submodules WHERE Status = 1"
        rows = self.execute_query(query)
        return self.filter_fields(rows, Submodule)

    def get_submodules_by_submodule_id(self, submodule_id: int) -> List[Submodule]:
        query = "SELECT * FROM Submodules WHERE SubmoduleID = %s AND Status = 1"
        rows = self.execute_query(query % submodule_id)
        return self.filter_fields(rows, Submodule)
        # return [Submodule(**row) for row in rows] if rows else []

    def get_submodules_by_sub_module_name(self,sub_module_name: str) -> List[Submodule]:
        query = "SELECT * FROM Submodules WHERE SubmoduleName = %s AND Status = 1"
        rows = self.execute_query(query, (sub_module_name,))
        return self.filter_fields(rows, Submodule)

    def get_submodule_id_by_description(self, description: str) -> int:
        query = "SELECT * FROM Submodules WHERE Description = %s AND Status = 1"
        rows = self.execute_query(query, (description,))
        result = self.filter_fields(rows, Submodule)
        return result[0].SubmoduleID if result else 0
        # return self.filter_fields(rows, Submodule)[0].SubmoduleID

    def insert_submodule(self, submodule: Submodule) -> int:
        query, values = self.generate_insert_query(submodule, "Submodules")
        return self.execute_insert(query, tuple(values))

    def update_submodule(self, submodule_update: SubmoduleUpdate) -> int:
        query, values = self.generate_update_query(submodule_update, "Submodules", "SubmoduleID")
        return self.execute_update(query, tuple(values))

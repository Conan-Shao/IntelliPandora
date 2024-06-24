# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : teststeprepository.py
@Time  : 2024-05-22
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.engine.generator.model.data.testcase import (TestStep, TestStepUpdate,
                                                                TestStepGetter)
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TestStepRepository(BaseRepository):

    def get_test_steps(self) -> List[Step]:
        query = "SELECT * FROM TestSteps WHERE Status = 1"
        rows = self.execute_query(query)
        return self.filter_fields(rows, Step)

    def get_test_steps_by_case_id(self, test_case_id: int) -> List[StepGetter]:
        query = self.generate_select_query(StepGetter, "TestSteps",
                                           "TestCaseID")
        rows = self.execute_query(query, (test_case_id,))
        return self.filter_fields(rows, StepGetter)

    def get_latest_step(self, test_case_id: int) -> Optional[Step]:
        query = "SELECT * FROM TestSteps WHERE TestCaseID = %s ORDER BY StepNumber DESC LIMIT 1"
        rows = self.execute_query(query, (test_case_id,))
        return self.filter_single(rows, Step)

    def insert_test_step(self, test_step: Step) -> int:
        query, values = self.generate_insert_query(test_step, "TestSteps")
        return self.execute_insert(query, tuple(values))

    def update_test_step(self, test_step: StepUpdate) -> int:
        query, values = self.generate_update_query(test_step, "TestSteps",
                                                   "StepID")
        return self.execute_update(query, tuple(values))

    def insert_test_step_as_transaction(self, test_step: Step,
                                        connection: Optional[Connection] = None,
                                        last_trans: bool = False):
        query, values = self.generate_insert_query(test_step, "TestSteps")
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            _conn = connection if _conn is None else _conn
            self.commit_transaction(_conn)
        return _conn, result


if __name__ == '__main__':
    # resp = TestStepRepository().get_test_steps(2)
    # print(resp)
    resp1 = TestStepRepository().get_test_steps_by_case_id(82)
    print(resp1)

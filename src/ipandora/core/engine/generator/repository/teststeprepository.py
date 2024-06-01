# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : teststeprepository.py
@Time  : 2024-05-22
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import TestStep, TestStepUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TestStepRepository(BaseRepository):

    def get_test_steps(self, test_case_id: int) -> List[TestStep]:
        query = "SELECT * FROM TestSteps WHERE TestCaseID = %s"
        rows = self.execute_query(query % test_case_id)
        return [TestStep(**row) for row in rows] if rows else []

    def get_latest_step(self, test_case_id: int) -> Optional[TestStep]:
        query = "SELECT * FROM TestSteps WHERE TestCaseID = %s ORDER BY StepNumber DESC LIMIT 1"
        rows = self.execute_query(query, (test_case_id,))
        return TestStep(**rows[0]) if rows else None

    def insert_test_step(self, test_step: TestStep) -> int:
        fields, values = AttrValueSplit(test_step).get_fields_and_values()
        query = f"""
                    INSERT INTO TestSteps ({', '.join(fields)}, ModifiedBy)
                    VALUES ({', '.join(['%s'] * len(values))}, %s)
                """
        return self.execute_insert(query, tuple(values))

    def update_test_step(self, test_step: TestStepUpdate) -> int:
        fields, values = AttrValueSplit(test_step, "StepID").get_fields_and_values()
        query = f"""
            UPDATE TestSteps
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE StepID = %s
        """
        values.append(test_step.StepID)
        return self.execute_update(query, tuple(values))

    def insert_test_step_as_transaction(self, test_step: TestStep,
                                        connection: Optional[Connection] = None,
                                        last_trans: bool = False):
        fields, values = AttrValueSplit(test_step).get_fields_and_values()
        query = f"""
                    INSERT INTO TestSteps ({', '.join(fields)}, ModifiedBy)
                    VALUES ({', '.join(['%s'] * len(values))}, %s)
                """
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            self.commit_transaction(_conn)
        return _conn, result


if __name__ == '__main__':
    resp = TestStepRepository().get_test_steps(2)
    print(resp)

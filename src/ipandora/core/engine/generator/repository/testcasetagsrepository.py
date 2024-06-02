# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testcasetagsrepository.py
@Time  : 2024-05-23
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import TestCaseTag, TestCaseTagUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TestCaseTagsRepository(BaseRepository):

    def get_test_case_tags_by_test_case_id(self, test_case_id: int) -> List[TestCaseTag]:
        query = "SELECT * FROM TestCaseTags WHERE TestCaseID = %s"
        rows = self.execute_query(query % test_case_id)
        return [TestCaseTag(**row) for row in rows] if rows else []

    def get_test_case_tags_by_tag_id(self, tag_id: int) -> List[TestCaseTag]:
        query = "SELECT * FROM TestCaseTags WHERE TagID = %s"
        rows = self.execute_query(query % tag_id)
        return [TestCaseTag(**row) for row in rows] if rows else []

    def get_test_case_ids_by_tag_id(self, tag_id: int) -> List[int]:
        query = "SELECT TestCaseID FROM TestCaseTags WHERE TagID = %s"
        rows = self.execute_query(query, (tag_id,))
        return [row['TestCaseID'] for row in rows] if rows else []

    def insert_test_case_tag(self, test_case_tag: TestCaseTag) -> int:
        query, values = self.generate_insert_query(test_case_tag, "TestCaseTags")
        return self.execute_insert(query, tuple(values))

    def update_test_case_tag(self, test_case_tag: TestCaseTagUpdate) -> int:
        fields, values = self._get_fields_and_values(test_case_tag, "TestCaseID")
        query = f"""
            UPDATE TestCaseTags
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE TestCaseTagID = %s
        """
        values.append(test_case_tag.TestCaseID)
        query, values = self.generate_update_query(test_case_tag, "TestCaseTags",
                                                   "TestCaseID")
        return self.execute_update(query, tuple(values))

    def insert_test_case_tag_as_transaction(self, test_case_tag: TestCaseTag,
                                            connection: Optional[Connection] = None,
                                            last_trans: bool = False):
        query, values = self.generate_insert_query(test_case_tag, "TestCaseTags")
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            _conn = connection if _conn is None else _conn
            self.commit_transaction(_conn)
        return _conn, result


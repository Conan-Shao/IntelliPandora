# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testcaserepository.py
@Time  : 2024-05-22
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import (TestCase, TestCaseUpdate,
                                                                 TestCaseFull)
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TestCaseRepository(BaseRepository):

    def get_test_cases(self) -> List[TestCase]:
        query = "SELECT * FROM TestCases"
        rows = self.execute_query(query)
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_case_by_id(self, test_case_id: int) -> Optional[TestCase]:
        query = "SELECT * FROM TestCases WHERE TestCaseID = %s"
        rows = self.execute_query(query, (test_case_id,))
        return TestCase(**rows[0]) if rows else None

    def get_test_cases_by_is_automated(self, is_automated: bool) -> List[TestCase]:
        """
        Get test cases by is_automated
        :param is_automated: True, return automated test cases; False, return manual test cases
        :return:
        """
        query = "SELECT * FROM TestCases WHERE IsAutomated = %s"
        rows = self.execute_query(query, (int(is_automated),))
        return [TestCase(**row) for row in rows] if rows else []

    def get_automated_test_cases(self) -> List[TestCase]:
        return self.get_test_cases_by_is_automated(True)

    def get_test_cases_by_title(self, title: str) -> List[TestCase]:
        query = "SELECT * FROM TestCases WHERE Title = %s"
        rows = self.execute_query(query, (title,))
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_cases_by_submodule_id(self, submodule_id: int) -> List[TestCase]:
        query = "SELECT * FROM TestCases WHERE SubmoduleID = %s"
        rows = self.execute_query(query, (submodule_id,))
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_cases_by_tag_id(self, tag_id: int) -> List[TestCase]:
        """
        Get test cases by tag id
        :param tag_id:
        :return:
        """
        query = """
            SELECT DISTINCT tc.* FROM TestCases tc
            JOIN TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            WHERE tct.TagID = %s
        """
        rows = self.execute_query(query, (tag_id,))
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_cases_by_tag_ids(self, tag_ids: List[int]) -> List[TestCase]:
        """
        Get test cases by tag ids, return test cases that contain one of the tag ids
        :param tag_ids:
        :return:
        """
        query = """
            SELECT DISTINCT tc.* FROM TestCases tc
            JOIN TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            WHERE tct.TagID IN (%s)
        """ % ','.join(['%s'] * len(tag_ids))
        rows = self.execute_query(query, tuple(tag_ids))
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_cases_by_exact_tag_ids(self, tag_ids: List[int]) -> List[TestCase]:
        """
        Get test cases by tag ids, return test cases that tags exactly the same as the tag ids.
        :param tag_ids:
        :return:
        """
        tag_count = len(tag_ids)
        tag_ids_str = ','.join(['%s'] * tag_count)
        query = f"""
            SELECT tc.* FROM TestCases tc
            JOIN (
                SELECT TestCaseID
                FROM TestCaseTags
                WHERE TagID IN ({tag_ids_str})
                GROUP BY TestCaseID
                HAVING COUNT(DISTINCT TagID) = %s
                AND COUNT(DISTINCT TagID) = (
                    SELECT COUNT(DISTINCT TagID)
                    FROM TestCaseTags AS innerTCT
                    WHERE innerTCT.TestCaseID = TestCaseTags.TestCaseID
                )
            ) tct ON tc.TestCaseID = tct.TestCaseID
        """
        rows = self.execute_query(query, tuple(tag_ids + [tag_count]))
        print(query)
        print(tuple(tag_ids + [tag_count]))
        print(rows)
        return [TestCase(**row) for row in rows] if rows else []

    def get_test_cases_by_contain_tag_ids(self, tag_ids: List[int]) -> List[TestCase]:
        """
        Get test cases by tag ids, return test cases that contain all the tag ids
        :param tag_ids:
        :return:
        """
        tag_ids_str = ','.join(['%s'] * len(tag_ids))
        query = f"""
            SELECT DISTINCT tc.* FROM TestCases tc
            JOIN TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            WHERE tct.TagID IN ({tag_ids_str})
            GROUP BY tc.TestCaseID
            HAVING COUNT(DISTINCT tct.TagID) = %s
        """
        rows = self.execute_query(query, tuple(tag_ids + [len(tag_ids)]))
        return [TestCase(**row) for row in rows] if rows else []

    def get_automated_cases_by_tag_ids(self, tag_ids: List[int],
                                       is_automated: bool) -> List[TestCase]:
        tag_count = len(tag_ids)
        tag_ids_str = ','.join(['%s'] * tag_count)
        query = f"""
            SELECT tc.* FROM TestCases tc
            JOIN (
                SELECT TestCaseID
                FROM TestCaseTags
                WHERE TagID IN ({tag_ids_str})
                GROUP BY TestCaseID
                HAVING COUNT(DISTINCT TagID) = %s
                AND COUNT(DISTINCT TagID) = (
                    SELECT COUNT(DISTINCT TagID)
                    FROM TestCaseTags AS innerTCT
                    WHERE innerTCT.TestCaseID = TestCaseTags.TestCaseID
                )
            ) tct ON tc.TestCaseID = tct.TestCaseID
            WHERE tc.IsAutomated = %s
        """
        rows = self.execute_query(query, tuple(tag_ids + [tag_count, int(is_automated)]))
        return [TestCase(**row) for row in rows] if rows else []

    def get_automated_case_id_by_tag_id(self, tag_id: int) -> List[int]:
        """
        Get all automated test case IDs by tag_id.
        :param tag_id: ID of the tag.
        :return: List of test case IDs.
        """
        query = """
            SELECT DISTINCT tc.TestCaseID 
            FROM TestCases tc
            JOIN TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            WHERE tct.TagID = %s AND tc.IsAutomated = 1
        """
        rows = self.execute_query(query, (tag_id,))
        return [row['TestCaseID'] for row in rows] if rows else []

    def get_full_cases(self, is_automated: Optional[bool] = None) -> List[TestCaseFull]:
        """
        Get full test cases.
        :param is_automated: True, return automated test cases; False, return manual test cases.
                None, return all.
        :return:
        """
        query = """
            SELECT 
                tc.TestCaseID, tc.Title, m.ModuleID, m.ModuleName, sm.SubmoduleID, sm.SubmoduleName,
                tc.Description, tc.Precondition, tc.IsAutomated, 
                GROUP_CONCAT(CONCAT(tg.CategoryName, ':', t.TagName) SEPARATOR ', ') as Tags, 
                tc.ModifiedBy, tc.CreatedTime, tc.UpdatedTime
            FROM 
                TestCases tc
            LEFT JOIN 
                Submodules sm ON tc.SubmoduleID = sm.SubmoduleID
            LEFT JOIN 
                Modules m ON sm.ModuleID = m.ModuleID
            LEFT JOIN 
                TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            LEFT JOIN 
                Tags t ON tct.TagID = t.TagID
            LEFT JOIN 
                TagCategories tg ON t.CategoryId = tg.CategoryId
            WHERE 
                1=1
        """
        params = []
        if is_automated is not None:
            query += " AND tc.IsAutomated = %s"
            params.append(int(is_automated))
        query += """
            GROUP BY 
                tc.TestCaseID, m.ModuleID, m.ModuleName, sm.SubmoduleID, sm.SubmoduleName,
                tc.Description, tc.Precondition, tc.IsAutomated, 
                tc.ModifiedBy, tc.CreatedTime, tc.UpdatedTime
        """
        rows = self.execute_query(query, tuple(params))
        result = []
        if rows:
            for row in rows:
                tags_str = row.pop('Tags', None)
                tags = tags_str.split(', ') if tags_str else []
                result.append(TestCaseFull(**row, Tags=tags))
        return result

    def get_full_case_by_id(self, test_case_id: int) -> Optional[TestCaseFull]:
        """
        Get full test case by test_case_id.
        :param test_case_id: ID of the test case.
        :return: TestCaseFull object or None
        """
        query = """
            SELECT 
                tc.TestCaseID, tc.Title, m.ModuleID, m.ModuleName, sm.SubmoduleID, sm.SubmoduleName,
                tc.Description, tc.Precondition, tc.IsAutomated, 
                GROUP_CONCAT(CONCAT(tg.CategoryName, ':', t.TagName) SEPARATOR ', ') as Tags, 
                tc.ModifiedBy, tc.CreatedTime, tc.UpdatedTime
            FROM 
                TestCases tc
            LEFT JOIN 
                Submodules sm ON tc.SubmoduleID = sm.SubmoduleID
            LEFT JOIN 
                Modules m ON sm.ModuleID = m.ModuleID
            LEFT JOIN 
                TestCaseTags tct ON tc.TestCaseID = tct.TestCaseID
            LEFT JOIN 
                Tags t ON tct.TagID = t.TagID
            LEFT JOIN 
                TagCategories tg ON t.CategoryId = tg.CategoryId
            WHERE 
                tc.TestCaseID = %s
            GROUP BY 
                tc.TestCaseID, m.ModuleID, m.ModuleName, sm.SubmoduleID, sm.SubmoduleName,
                tc.Description, tc.Precondition, tc.IsAutomated, 
                tc.ModifiedBy, tc.CreatedTime, tc.UpdatedTime
        """
        rows = self.execute_query(query, (test_case_id,))
        if rows:
            row = rows[0]
            tags_str = row.pop('Tags', None)
            tags = tags_str.split(', ') if tags_str else []
            return TestCaseFull(**row, Tags=tags)
        return None

    def insert_test_case(self, test_case: TestCase) -> int:
        fields, values = AttrValueSplit(test_case).get_fields_and_values()
        query = f"""
            INSERT INTO TestCases ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        return self.execute_insert(query, tuple(values))

    def update_test_case(self, case_update: TestCaseUpdate) -> int:
        fields, values = AttrValueSplit(case_update, "TestCaseID").get_fields_and_values()
        query = f"""
            UPDATE TestCases
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE TestCaseID = %s
        """
        values.append(case_update.TestCaseID)
        return self.execute_update(query, tuple(values))

    def insert_test_case_as_transaction(self, test_case: TestCase,
                                        connection: Optional[Connection] = None,
                                        last_trans: bool = False):
        """
        Insert test case as transaction.
        :param test_case:
        :param connection:
        :param last_trans:
        :return:
        """
        fields, values = AttrValueSplit(test_case).get_fields_and_values()
        query = f"""
            INSERT INTO TestCases ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            self.commit_transaction(_conn)
        return _conn, result


if __name__ == '__main__':
    # resp0 = TestCaseRepository().get_test_cases_by_tag_ids([75, 1])
    # print(resp0)
    # resp1 = TestCaseRepository().get_test_cases_by_contain_tag_ids([44, 118])
    # print(resp1)
    # print(len(resp1))
    # resp2 = TestCaseRepository().get_test_cases_by_exact_tag_ids([44, 118])
    # print(resp2)
    # print(len(resp2))
    # resp3 = TestCaseRepository().get_automated_cases_by_tag_ids([44, 118],
    #                                                             is_automated=False)
    # print(resp3)
    # print(len(resp3))
    resp4 = TestCaseRepository().get_full_cases()
    print(resp4)
    print(len(resp4))

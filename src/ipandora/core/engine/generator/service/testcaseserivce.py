# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testcaseserivce.py
@Time  : 2024-05-24
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.engine.generator.repository.testcaserepository import TestCaseRepository
from ipandora.core.engine.generator.repository.teststeprepository import TestStepRepository
from ipandora.core.engine.generator.repository.tagrepository import TagRepository
from ipandora.core.engine.generator.repository.testcasetagsrepository import TestCaseTagsRepository
from ipandora.core.engine.generator.model.data.testcase import (TestCase, TestStep, Tag,
                                                                 TestCaseTag, TestCaseUpdate,
                                                                 TestCaseFull)
from ipandora.core.engine.generator.model.data.robotsuite import (RobotSuite, RobotCase,
                                                                   RobotSettings)
from ipandora.utils.log import logger


class TestCaseService:

    def __init__(self):
        self.test_case_repo = TestCaseRepository()
        self.test_step_repo = TestStepRepository()
        self.tag_repo = TagRepository()
        self.test_case_tags_repo = TestCaseTagsRepository()

    def get_test_case_by_id(self, test_case_id: int) -> TestCase:
        return self.test_case_repo.get_test_case_by_id(test_case_id)

    def get_tags_by_case_id(self, test_case_id: int) -> List[Tag]:
        test_case_tags = self.test_case_tags_repo.get_test_case_tags_by_test_case_id(test_case_id)
        return [self.tag_repo.get_tag_by_id(tag.TagID) for tag in test_case_tags]

    def get_test_cases_by_tags(self, tag_names: List[str]) -> List[TestCase]:
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_test_cases_by_contain_tag_ids(tag_ids)

    def get_automated_test_cases_by_tags(self, tag_names: List[str]) -> List[TestCase]:
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_automated_cases_by_tag_ids(tag_ids, True)

    def get_test_cases_by_contain_tags(self, tag_names: List[str]) -> List[TestCase]:
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_test_cases_by_contain_tag_ids(tag_ids)

    def get_full_cases_by_tag(self, tag_name: str) -> List[TestCaseFull]:
        _tag_id = self.tag_repo.get_tag_id_by_name(tag_name)
        if not _tag_id:
            return []
        _case_id_list = self.test_case_tags_repo.get_test_case_ids_by_tag_id(_tag_id)
        if not _case_id_list:
            return []
        return [self.test_case_repo.get_full_case_by_id(_case_id)
                for _case_id in _case_id_list]

    def get_automated_full_cases_by_tag(self, tag_name: str) -> List[TestCaseFull]:
        _tag_id = self.tag_repo.get_tag_id_by_name(tag_name)
        if not _tag_id:
            return []
        _case_id_list = self.test_case_repo.get_automated_case_id_by_tag_id(_tag_id)
        if not _case_id_list:
            return []
        return [self.test_case_repo.get_full_case_by_id(_case_id)
                for _case_id in _case_id_list]

    def add_testcase(self, test_case: TestCase) -> int:
        test_case_id = self.test_case_repo.insert_test_case(test_case)
        logger.info(f"Test case inserted with ID: {test_case_id}")
        return test_case_id

    def add_test_step_to_case(self, test_case_id: int, test_step: TestStep) -> int:
        _step_number = self.get_latest_step_number_by_case_id(test_case_id) + 1
        test_step.TestCaseID = test_case_id
        test_step.StepNumber = _step_number
        step_id = self.test_step_repo.insert_test_step(test_step)
        logger.info(f"Test step inserted with ID: {step_id} for test case ID: {test_case_id}")
        return step_id

    def add_tags_to_case(self, test_case_id: int, tag_names: List[str]):
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        if all(isinstance(item, list) and not item for item in tags):
            logger.warning("No tags found with the provided names.")
        else:
            for tag in tags:
                if tag:
                    test_case_tag = TestCaseTag(TestCaseID=test_case_id, TagID=tag[0].TagID)
                    self.test_case_tags_repo.insert_test_case_tag(test_case_tag)
                    logger.info(f"Tag ID: {tag[0].TagID} added to test case ID: {test_case_id}")

    def modify_test_case(self, case_update: TestCaseUpdate) -> int:
        logger.info(f"Modifying test case with ID: {case_update.TestCaseID}")
        rows_affected = self.test_case_repo.update_test_case(case_update)
        logger.info(f"Rows affected: {rows_affected}")
        return rows_affected

    def get_latest_step_number_by_case_id(self, test_case_id: int) -> Optional[int]:
        try:
            # 获取指定测试用例的所有步骤，按 StepNumber 降序排列，取第一个
            latest_step = self.test_step_repo.get_latest_step(test_case_id)
            if latest_step:
                return latest_step.StepNumber
            return 0
        except Exception as e:
            logger.error(f"Error getting latest step number for case {test_case_id}: {e}")
            raise e

    def create_test_case(self, test_case: TestCase, steps: List[TestStep],
                         tags: List[TestCaseTag]) -> bool:
        _connection: Optional[Connection] = None
        try:
            # add case with transaction.
            _connection, _test_case_id = self.test_case_repo.insert_test_case_as_transaction(
                test_case)
            if _test_case_id == -1:
                self.test_case_repo.close_connection(_connection)
                raise Exception("Failed to insert test case")

            # add test steps.
            for step in steps:
                step.TestCaseID = _test_case_id
                _, _step_ids = self.test_step_repo.insert_test_step_as_transaction(step, _connection)
                if _step_ids == -1:
                    # self.test_step_repo.close_connection(connection)
                    raise Exception("Failed to insert test step")
            # add tags and the last one will commit.
            for i, tag in enumerate(tags):
                tag.TestCaseID = _test_case_id
                if i == len(tags) - 1:
                    _, _tag_case_id = self.test_case_tags_repo.insert_test_case_tag_as_transaction(
                        tag, _connection, True)
                    if _tag_case_id == -1:
                        # self.test_case_tags_repo.close_connection(connection)
                        raise Exception("Failed to insert test case tag")
                else:
                    _, _tag_case_id = self.test_case_tags_repo.insert_test_case_tag_as_transaction(
                        tag, _connection)
                    if _tag_case_id == -1:
                        # self.test_case_tags_repo.close_connection(connection)
                        raise Exception("Failed to insert test case tag")
            return True
        except Exception as e:
            if _connection:
                # rollback transaction
                self.test_case_repo.rollback_transaction(_connection)
            logger.error(f"Error creating test case: {e}")
            return False
        finally:
            if _connection:
                _connection.close()


if __name__ == '__main__':
    from ipandora.core.engine.generator.model.data.testcase import TestCase
    # 创建服务实例
    test_case_service = TestCaseService()
    result = test_case_service.get_full_cases_by_tag('G40')
    print(result)
    result = test_case_service.get_automated_full_cases_by_tag('G40')
    print(result)

    # # 创建一个测试用例对象
    # new_test_case = TestCase(
    #     TestCaseID=None,
    #     SubmoduleID=11,
    #     Title="Test Case Title Shaft 006",
    #     Description="Test Case Description Shaft 006",
    #     Precondition="Precondition Shaft 006",
    #     IsAutomated=True,
    # )
    # print(new_test_case)
    # _case_id = test_case_service.add_testcase(new_test_case)
    # print(f"New test case ID: {_case_id}")
    #
    # modify_test = TestCaseUpdate(
    #     TestCaseID=_case_id,
    #     SubmoduleID=None,
    #     Title="Test Case Title Shaft 006, Modified222",
    #     Description=None,
    #     Precondition=None,
    #     IsAutomated=True,
    # )
    # print(modify_test)
    # test_case_service.modify_test_case(modify_test)

    # # add test steps and tags
    # test_case_service.add_tags_to_case(_case_id, ['smoke', 'G00', 'generator'])

    # _test_step1 = TestStep(
    #     StepID=None,
    #     TestCaseID=None,
    #     StepDescription="Test Step Description Shaft 005 - 001",
    #     StepNumber=1,
    #     ExpectedResult="Expected Result Shaft 005 - 001",
    # )
    # test_case_service.add_test_step_to_case(_case_id, _test_step1)
    #
    # _test_step2 = TestStep(
    #     StepID=None,
    #     TestCaseID=None,
    #     StepDescription="Test Step Description Shaft 005 - 002",
    #     StepNumber=1,
    #     ExpectedResult="Expected Result Shaft 005 - 002",
    # )
    #
    # test_case_service.add_test_step_to_case(7, _test_step1)

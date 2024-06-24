# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testcaseserivce.py
@Time  : 2024-05-24
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.common.timeutils import TimeUtils
from ipandora.common.uuidutils import UUIDFactory
from ipandora.core.engine.generator.model.handler.programhandler import ProgramHandler
from ipandora.core.engine.generator.repository.attachmentrepository import AttachmentRepository
from ipandora.core.engine.generator.repository.testcaserepository import TestCaseRepository
from ipandora.core.engine.generator.repository.teststeprepository import TestStepRepository
from ipandora.core.engine.generator.repository.tagrepository import TagRepository
from ipandora.core.engine.generator.repository.testcasetagsrepository import TestCaseTagsRepository
from ipandora.core.engine.generator.repository.testcasetagsrepository import TestCaseTagsRepository
from ipandora.core.engine.generator.model.data.case import (Case, Step, Tag, CaseTag, CaseUpdate,
                                                            TestCaseFull, StepGetter,
                                                            AttachmentGetter, Attachment)
from ipandora.core.engine.generator.model.data.robotsuite import (RobotSuite, RobotCase,
                                                                  RobotSettings)
from ipandora.utils.log import logger


class TestAttachmentRepository:
    pass


class TestCaseService(object):
    def __init__(self):
        self.test_case_repo = TestCaseRepository()
        self.test_step_repo = TestStepRepository()
        self.tag_repo = TagRepository()
        self.test_case_tags_repo = TestCaseTagsRepository()
        self.test_attachment_repo = AttachmentRepository()
        self.phandler = ProgramHandler()

    def get_test_case_by_id(self, test_case_id: int) -> Case:
        return self.test_case_repo.get_test_case_by_id(test_case_id)

    def get_test_case_by_excel_case_id(self, excel_case_id: int) -> Case:
        return self.test_case_repo.get_test_case_by_excel_case_id(excel_case_id)

    def get_tags_by_case_id(self, test_case_id: int) -> List[Tag]:
        test_case_tags = self.test_case_tags_repo.get_test_case_tags_by_test_case_id(test_case_id)
        return [self.tag_repo.get_tag_by_id(tag.TagID) for tag in test_case_tags]

    def get_steps_by_case_id(self, test_case_id: int) -> List[StepGetter]:
        return self.test_step_repo.get_test_steps_by_case_id(test_case_id)

    def get_attachments_by_case_id(self, test_case_id: int) -> List[AttachmentGetter]:
        return self.test_attachment_repo.get_attachments_by_test_case_id(test_case_id)

    def get_test_cases_by_source(self, source: str = 'doc') -> List[Case]:
        return self.test_case_repo.get_test_cases_by_source(source)

    def get_automated_test_cases_by_source(self, source: str = 'doc') -> List[Case]:
        return self.test_case_repo.get_automated_test_cases_by_source(source)

    def get_test_cases_by_tags(self, tag_names: List[str]) -> List[Case]:
        """
        Get test cases by tag names. Return test cases that tags exactly the same as the tag ids.
        :param tag_names:
        :return:
        """
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_test_cases_by_exact_tag_ids(tag_ids)

    def get_test_cases_contain_tags(self, tag_names: List[str]) -> List[Case]:
        """
        Get test cases by tag names. Return test cases that tags contain the tag ids.
        :param tag_names:
        :return:
        """
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_test_cases_by_contain_tag_ids(tag_ids)

    def get_automated_test_cases_by_tags(self, tag_names: List[str]) -> List[Case]:
        tags = [self.tag_repo.get_tags_by_name(tag_name) for tag_name in tag_names]
        tag_ids = [tag[0].TagID for tag in tags if tag]
        if not tag_ids:
            return []
        return self.test_case_repo.get_automated_cases_by_tag_ids(tag_ids, True)

    def get_full_case_by_id(self, test_case_id: int) -> TestCaseFull:
        _steps_obj = self.get_steps_by_case_id(test_case_id)
        _attachments_obj = self.get_attachments_by_case_id(test_case_id)
        _full_case_obj = self.test_case_repo.get_full_case_by_id(test_case_id)
        if _full_case_obj:
            _full_case_obj.Steps = _steps_obj
            _full_case_obj.Attachments = _attachments_obj
        else:
            logger.warning(f"No test case found with the provided ID={test_case_id}.")
        return _full_case_obj

    def get_full_cases_by_tag(self, tag_name: str) -> List[TestCaseFull]:
        _tag_id = self.tag_repo.get_tag_id_by_name(tag_name)
        if not _tag_id:
            return []
        _case_id_list = self.test_case_tags_repo.get_test_case_ids_by_tag_id(_tag_id)
        if not _case_id_list:
            return []
        return [self.get_full_case_by_id(_case_id)
                for _case_id in _case_id_list]

    def get_automated_full_cases_by_tag(self, tag_name: str) -> List[TestCaseFull]:
        _tag_id = self.tag_repo.get_tag_id_by_name(tag_name)
        if not _tag_id:
            return []
        _case_id_list = self.test_case_repo.get_automated_case_id_by_tag_id(_tag_id)
        if not _case_id_list:
            return []
        return [self.get_full_case_by_id(_case_id)
                for _case_id in _case_id_list]

    def get_full_cases_by_source(self, source: str = 'doc') -> List[TestCaseFull]:
        _case_obj_list = self.get_automated_test_cases_by_source(source)
        if not _case_obj_list:
            return []
        else:
            _case_id_list = [case.TestCaseID for case in _case_obj_list]
        if not _case_id_list:
            return []
        return [self.get_full_case_by_id(_case_id) for _case_id in _case_id_list]

    def add_testcase(self, test_case: Case) -> int:
        test_case_id = self.test_case_repo.insert_test_case(test_case)
        logger.info(f"Test case inserted with ID: {test_case_id}")
        return test_case_id

    def add_test_step_to_case(self, test_case_id: int, test_step: Step) -> int:
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
                    test_case_tag = CaseTag(TestCaseID=test_case_id, TagID=tag[0].TagID)
                    self.test_case_tags_repo.insert_test_case_tag(test_case_tag)
                    logger.info(f"Tag ID: {tag[0].TagID} added to test case ID: {test_case_id}")

    def modify_test_case(self, case_update: CaseUpdate) -> int:
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

    def create_test_case(self, test_case: Case, steps: List[Step], tags: List[str],
                         attachments: List[Attachment] = None,
                         is_download = True) -> int | list[int]:
        """
        Create a test case with steps, tags and attachments.
        :param test_case:
        :param steps:
        :param tags: list of tag name. tag category can be selected.
            e.g. ["milling_center", "xz", "G01", "single", "handbook"]
            - 机床类别(单选):  turning_center
                        turning_center_with_c_axis
                        milling_center
                        milling_center_with_head_table
                        milling_center_with_dual_table
                        milling_center_with_dual_head
            - 机床结构(单选):  xz, xyz, xyzc ...
            - 指令类型(多选):  CYCLE71, CYCLE72, CYCLE76, G00, G01, G02 ...
            - 指令结构(单选):  single, program
            - 来源(单选):     handbook, robot, document
            - 测试执行(单选): smoke, daily
        :param attachments:
        :param is_download: bool, the attachments will be downloaded when is_upload is True.
        :return:
        """
        _connection: Optional[Connection] = None
        _excel_case_id = test_case.ExcelCaseID
        _case_obj = self.get_test_case_by_excel_case_id(_excel_case_id)
        if not _case_obj:
            logger.info("This is new case")
            return self._add_full_test_case(test_case, steps, tags, attachments, is_download)
        else:
            logger.warning("This excel case have been in mysql yet.")
            return self._update_full_test_case()

    def _add_full_test_case(self, test_case: Case, steps: List[Step], tags: List[str],
                            attachments: List[Attachment] = None, is_upload = True):
        _test_case_id = -1
        # 1. add case with transaction.
        logger.info("Start to create test case.")
        _connection, _test_case_id = self.test_case_repo.insert_test_case_as_transaction(
            test_case)
        try:
            if _test_case_id == -1:
                logger.warning("Failed to insert test case. Rollback transaction.")
                self.test_case_repo.close_connection(_connection)
                raise Exception("Failed to insert test case")
            # 2. add test steps.
            logger.info("Start to add test steps.")
            for step in steps:
                step.TestCaseID = _test_case_id
                _, _step_ids = self.test_step_repo.insert_test_step_as_transaction(step,
                                                                                   _connection)
                if _step_ids == -1:
                    logger.warning("Failed to insert test step. Rollback transaction.")
                    raise Exception("Failed to insert test step")
            # 3. generated TagCase object and add tags.
            logger.info("Start to add tags.")
            if tags:
                for _tag_name in tags:
                    _tag_id = self.tag_repo.get_tag_id_by_name(_tag_name)
                    if not _tag_id:
                        logger.warning(f"No tags found with the provided names: <{_tag_name}>.")
                        continue
                    tag_case_obj = CaseTag(TestCaseID=_test_case_id, TagID=_tag_id)
                    _, _tag_case_id = (
                        self.test_case_tags_repo.insert_test_case_tag_as_transaction(tag_case_obj,
                                                                                     _connection))
                    if _tag_case_id == -1:
                        logger.warning("Failed to insert test case tag. Rollback transaction.")
                        raise Exception("Failed to insert test case tag")
            # 4. deal with attachments
            if attachments:
                for _attachment in attachments:
                    if isinstance(_attachment, Attachment):
                        _attachment.TestCaseID = _test_case_id
                        self.test_attachment_repo.insert_attachment_as_transaction(_attachment,
                                                                                   _connection)
                        if (_attachment.OriginalLink and 'zentao' in _attachment.OriginalLink and
                                is_upload):
                            self.phandler.transfer_program(_attachment.OriginalLink,
                                                           _attachment.FilePath)
                        else:
                            logger.warning(f"Attachment link is zentao or upload_tag is False.\n "
                                           f"<link:{_attachment.OriginalLink}> \n"
                                           f"<is_upload: {is_upload}>")
            # commit transaction
            self.test_case_repo.commit_transaction(_connection)
        except Exception as e:
            if _connection:
                # rollback transaction
                self.test_case_repo.rollback_transaction(_connection)
            logger.error(f"Error creating test case: {e}")
        finally:
            if _connection:
                self.test_case_repo.close_connection(_connection)
            return _test_case_id

    @staticmethod
    def _update_full_test_case():
        return -1


if __name__ == '__main__':
    from ipandora.core.engine.generator.model.data.case import Case
    # # create service
    test_case_service = TestCaseService()
    # result = test_case_service.get_full_cases_by_tag('G40')
    # print(result)
    # result = test_case_service.get_automated_full_cases_by_tag('G40')
    # print(result)

    # # create case object
    # new_test_case = Case(
    #     TestCaseID=None,
    #     SubmoduleID=11,
    #     Title="Test Case Title Shaft 006",
    #     Description="Test Case Description Shaft 006",
    #     Precondition="Precondition Shaft 006",
    #     Source="doc",  # handbook, robot, doc
    #     IsAutomated=True,
    # )
    # print(new_test_case)
    # # create steps object
    # _steps = []
    # for _i in range(1, 6):
    #     _test_step = Step(
    #         StepID=None,
    #         TestCaseID=None,
    #         StepDescription=f"Test Step Description Shaft create 001",
    #         StepNumber=_i,
    #         ExpectedResult=f"Expected Result Shaft create- 00{_i}",
    #     )
    #     _steps.append(_test_step)
    # # create attachments object, attachment is optional.
    # _attachment_new_list = []
    # for _j in range(1, 3):
    #     uuid_str = UUIDFactory().generate_uuid4()
    #     _attachment_new = Attachment(
    #         AttachmentID=None,
    #         TestCaseID=None,
    #         OriginalFileName=f"test_program_origin.txt",
    #         FilePath=f"/var/data/test_case_attachments/{uuid_str}.txt")
    #     _attachment_new_list.append(_attachment_new)

    # # create test case, tag is optional and tags is a list of tag names.
    # _new_case_id = test_case_service.create_test_case(new_test_case, _steps,
    #                                                   ['smoke', 'G00', 'turning_center', 'xz'])
    #                                                   # _attachment_new_list)
    # print(_new_case_id)
    # _full_case = test_case_service.get_full_case_by_id(1)
    # print(_full_case)
    # res = test_case_service.get_test_case_by_excel_case_id(100)
    # print(res)
    # # create test case, tag is optional and tags is a list of tag names.
    # _new_case_id = test_case_service.create_test_case(new_test_case, _steps,
    #                                                   ['smoke', 'G00', 'turning_center', 'xz'],
    #                                                   _attachment_new_list)
    # print(_new_case_id)
    # _full_case = test_case_service.get_full_case_by_id(217)
    # print(_full_case)

    _full_case_objs = test_case_service.get_full_cases_by_source()
    print(_full_case_objs)
    print(len(_full_case_objs))
    # res = test_case_service.get_test_case_by_excel_case_id(1)
    # print(res)

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotcaseservice.py
@Time  : 2024-05-25
"""
from typing import List, Optional
from ipandora.core.engine.generator.model.handler.robotrenderer import RobotRenderer
from ipandora.core.engine.generator.model.data.robotsuite import (RobotSuite, RobotSettings,
                                                                   RobotCase)
from ipandora.core.engine.generator.repository.testcaserepository import TestCaseRepository
from ipandora.core.engine.generator.repository.testcasetagsrepository import TestCaseTagsRepository
from ipandora.core.engine.generator.repository.teststeprepository import TestStepRepository
from ipandora.core.engine.generator.service.testcaseserivce import TestCaseService
from ipandora.utils.error import DataError
from ipandora.utils.filewriter import RobotFileWriter
from ipandora.utils.log import logger


class RobotCasesService(object):
    def __init__(self):
        self.test_case_repository = TestCaseRepository()
        self.test_step_repository = TestStepRepository()
        self.test_case_tags_repository = TestCaseTagsRepository()
        self.test_case_service = TestCaseService()

    @staticmethod
    def create_robot_file(_suite: RobotSuite, output_path: Optional[str] = None) -> bool:
        try:
            if not isinstance(_suite, RobotSuite):
                raise DataError(f"The {_suite} is not RobotSuite object.")
            RobotFileWriter(_suite.name, RobotRenderer(_suite).content(), output_path)
            return True
        except Exception as e:
            logger.error(f"Error creating robot suite: {e}")
            return False

    @staticmethod
    def creat_robot_suite(suite_name: str, settings: RobotSettings,
                          cases: List[RobotCase]) -> RobotSuite:
        if not isinstance(settings, RobotSettings):
            raise DataError(f"The {settings} is not RobotSettings object.")
        if not isinstance(cases, list):
            raise DataError(f"The {cases} is not list object.")
        else:
            for case in cases:
                if not isinstance(case, RobotCase):
                    raise DataError(f"The {case} is not RobotCase object.")
        return RobotSuite(name=suite_name, settings=settings, cases=cases)

    def create_robot_suite_from_case_tag(self, tags) -> [RobotSuite]:
        _cases_obj = self.test_case_service.get_test_cases_by_tags(tags)
        if not _cases_obj:
            raise DataError(f"No test cases found with tags {tags}")
        return _cases_obj
        # return self.creat_robot_suite(tag, self.test_case_repository.get_settings(), cases)


if __name__ == '__main__':
    _case_obj = RobotCasesService().create_robot_suite_from_case_tag(['G40', 'tag2'])
    print(_case_obj)
    print(len(_case_obj))


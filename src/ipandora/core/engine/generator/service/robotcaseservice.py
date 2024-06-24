# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotcaseservice.py
@Time  : 2024-05-25
"""
import os, re
from collections import defaultdict
from typing import List, Optional
from ipandora.common.stringaction import StringAction
from ipandora.core.engine.generator.model.data.case import TestCaseFull, StepGetter
from ipandora.core.engine.generator.model.handler.robotrenderer import RobotRenderer
from ipandora.core.engine.generator.model.handler.programhandler import ProgramHandler
from ipandora.core.engine.generator.model.data.robotsuite import (RobotSuite, RobotSettings,
                                                                  RobotCase)
from ipandora.core.engine.generator.repository.testcaserepository import TestCaseRepository
from ipandora.core.engine.generator.repository.testcasetagsrepository import TestCaseTagsRepository
from ipandora.core.engine.generator.repository.teststeprepository import TestStepRepository
from ipandora.core.engine.generator.service.testcaseserivce import TestCaseService
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.error import DataError
from ipandora.utils.fileload import FileLoad
from ipandora.utils.filewriter import RobotFileWriter
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils


class RobotCasesService(object):
    def __init__(self):
        self.test_case_repository = TestCaseRepository()
        self.test_step_repository = TestStepRepository()
        self.test_case_tags_repository = TestCaseTagsRepository()
        self.test_case_service = TestCaseService()
        self.config = {}
        self.robot_steps_template = []
        self.initialize_config()
        self._phandler = ProgramHandler()

    def initialize_config(self):
        _config_path = Runtime.Generator.config
        self.config = FileLoad(_config_path).load_yaml()

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

    def create_robot_with_source(self, source='doc', program_dir=''):
        """
        Create robot object with source.
        :param source: doc-case designed in excels, handbook-case generated with handbook.
        :param program_dir: attachment of case will be downloaded and store in the directory.
        :return:
        """
        _robot_obj_list = []
        if source == 'doc':
            _robot_obj_list = self.create_robot_for_doc_case(program_dir)
        elif source == 'handbook':
            _robot_obj_list = self.create_robot_for_handbook_case()
        return _robot_obj_list

    def create_robot_for_doc_case(self, program_dir='') -> [RobotSuite]:
        """
        To create a Robot Framework test for document case where the source is equal to "doc".
        :return:
        """
        # if not program_dir:
        #     program_dir = PathUtils.get_home_path()
        program_dir = program_dir if program_dir else PathUtils.get_home_path()
        program_dir = PathUtils.join_paths_ignore_duplicates(program_dir, 'i5programs')
        _config_doc = self.config.get('doc')
        self.robot_steps_template = _config_doc.get('steps')
        _full_case_obj_list = self.test_case_service.get_full_cases_by_source()

        _cases_dd = self._filter_by_field(_full_case_obj_list, 'SubmoduleName')
        robot_object_list = []
        for _m, _cases in _cases_dd.items():
            # set suite name with module name
            if _m is None:
                _suite_name = _config_doc.get("name")
            else:
                _m_fmt = StringAction.capitalize_and_remove_spaces(_m)
                _suite_name = "Test_{}".format(_m_fmt)
            # set suite setting
            _setting = _config_doc.get("setting")
            _setting_obj = RobotSettings(suite_setup=_setting.get("Suite Setup"),
                                         suite_teardown=_setting.get("Suite Teardown"),
                                         test_setup=_setting.get("Test Setup"),
                                         test_teardown=_setting.get("Test Teardown"),
                                         test_template=_setting.get("Test Template"),
                                         resource=_setting.get("Resource"),
                                         library=_setting.get("Library")
                                         )
            # get case object list
            _robot_case_obj_list = [self.convert_full_case_to_robot(_case_o, program_dir)
                                    for _case_o in _cases]
            # set suite object
            _robot_suite_object = self._create_robot_suite(_suite_name, _setting_obj,
                                                           _robot_case_obj_list)
            robot_object_list.append(_robot_suite_object)
        self._phandler.disconnect_remote_server()
        return robot_object_list

    def create_robot_for_handbook_case(self) -> [RobotSuite]:
        """
        To create a Robot Framework test for handbook case where the source is equal to "handbook".
        :return:
        """
        _full_case_obj_list = self.test_case_service.get_full_cases_by_source('handbook')
        _result = self._filter_by_field(_full_case_obj_list, 'ModuleName')
        return _result
        # return [self.convert_full_case_to_robot(_obj) for _obj in _full_case_obj_list]

    def create_robot_with_tag(self, tags) -> [RobotSuite]:
        _cases_obj = self.test_case_service.get_test_cases_by_tags(tags)
        if not _cases_obj:
            raise DataError(f"No test cases found with tags {tags}")
        return _cases_obj
        # return self.creat_robot_suite(tag, self.test_case_repository.get_settings(), cases)

    def convert_full_case_to_robot(self, _case_object: TestCaseFull,
                                   program_dir='') -> Optional[RobotCase]:
        if not isinstance(_case_object, TestCaseFull):
            raise DataError(f"The {_case_object} is not TestCaseFull object.")
        if _case_object.Source == 'doc':
            # doc, zentao
            return self._convert_doc_case_to_robot(_case_object, program_dir)
        elif _case_object.Source == 'robot':
            logger.warning("The case is robot case, no need to convert.")
            return None
        else:
            # handbook
            pass

    def _convert_doc_case_to_robot(self, _case_object: TestCaseFull, program_dir=''):
        _step_var = {'main_program_name': ''}
        _case_name = StringAction.filter_illegal_characters(_case_object.Title
                                                            )+'_'+str(_case_object.TestCaseID)
        _tags = _case_object.Tags
        _robot_steps = list(self.robot_steps_template)

        for _index, _att in enumerate(_case_object.Attachments):
            origin_program_path = _att.FilePath
            program_name = _att.OriginalFileName
            if 'sub' not in program_name:
                _step_var.update({"main_program_name": program_name})
            if origin_program_path and program_name:
                _remote_file_path = PathUtils.join_paths_ignore_duplicates(
                    Runtime.Remote.directory, origin_program_path)
                _prog_dir = PathUtils.join_paths_ignore_duplicates(program_dir,
                                                                   os.path.dirname(
                                                                       origin_program_path))

                self._phandler.download_program_from_service(_remote_file_path, _prog_dir)
                _robot_steps.insert(0,
                                    f'${{source_file_{_index}}}    Put_Program_to_I5OS    {origin_program_path}    {program_name}')
                _robot_steps.insert(1,
                                    f'${{prog_content}}    OperatingSystem.Get File    ${{source_file_{_index}}}')
        # _robot_steps_new = [step.format(**_step_var) for step in _robot_steps]
        _robot_steps_new = [self.replace_variables(step, _step_var) for step in _robot_steps]
        _tags.extend(["source:{}".format(_case_object.Source),
                      "ExcelCaseID:{}".format(_case_object.ExcelCaseID)])
        if _case_object.ModuleName:
            _tags.append("module:{}".format(_case_object.ModuleName))
        return RobotCase(name=_case_name, steps=_robot_steps_new,
                         setup=None, teardown=None, tags=_tags)

    def _convert_handbook_case_to_robot(self, _case_object: TestCaseFull):
        pass

    @staticmethod
    def _create_robot_suite(suite_name: str, settings: RobotSettings,
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

    @staticmethod
    def _filter_by_field(_case_obj_list: List[TestCaseFull], field: str):
        split_dict = defaultdict(list)
        for _case_object in _case_obj_list:
            key = getattr(_case_object, field)
            split_dict[key].append(_case_object)
        return split_dict

    @staticmethod
    def replace_variables(step, variables):
        def replace_match(match):
            var_name = match.group(1)
            return variables.get(var_name, match.group(0))

        return re.sub(r'{([^{}]+)}', replace_match, step)


if __name__ == '__main__':
    robot_obj_list = RobotCasesService().create_robot_with_source()
    print(robot_obj_list)


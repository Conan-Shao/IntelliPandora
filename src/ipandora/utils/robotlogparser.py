# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : robotlogparser.py
@Time  : 2024-05-17
"""
import os
import datetime
import xml.etree.ElementTree as ET
from jinja2 import Environment, FileSystemLoader
from ipandora.utils.pathutils import PathUtils
from ipandora.utils.log import logger


class RobotLogParser:
    def __init__(self, xml_file, details_url=None, skip_pass=True):
        """
        RobotLogParser is used to parse Robot Framework results from an XML file.
        This Report is a simple HTML report that displays the test execution summary and details.
        The aggregate report only shows the top layer suite of the robot file.
        :param xml_file: Path to the Robot Framework output XML file
        :param details_url: URL to detailed log
        :param skip_pass: Whether to skip passed test cases in the detailed report
        """
        self.xml_file = xml_file
        if not os.path.exists(self.xml_file):
            raise FileNotFoundError(f"File <{self.xml_file}> not found.")
        self.log_path = os.path.dirname(os.path.abspath(self.xml_file))
        self.skip_pass = skip_pass
        self.details_url = details_url if details_url else "#details"
        self.results = self.parse_robot_results()

    def parse_robot_results(self):
        logger.info("Start to parse robot result...")
        tree = ET.parse(self.xml_file)
        root = tree.getroot()
        results = {
            "head": self.handle_with_time(root),
            "statistics": self.handle_with_statistics(root),
            "Details": self.handle_with_suites(root)
        }
        logger.info("Parse success! ! !")
        return results

    def handle_with_statistics(self, root):
        stats = root.find('.//statistics/total/stat')
        if stats is not None:
            _pass = int(stats.get('pass', 0))
            _fail = int(stats.get('fail', 0))
            _pr = "{:.2f}".format((_pass / (_pass + _fail)) * 100).rstrip('0') + '%'
            return {
                "total": _pass + _fail,
                "pass": _pass,
                "fail": _fail,
                "pass_rate": _pr,
                "log_url": self.details_url
            }
        return {"total": 0, "pass": 0, "fail": 0, "pass_rate": "0%", "log_url": self.details_url}

    def handle_with_suites(self, root):
        suites = {}
        for suite in root.iter('suite'):
            _suite_source = suite.get('source')
            if not _suite_source or not _suite_source.endswith('.robot'):
                continue
            suite_name = '_'.join(suite.get('name').split(' '))
            if suite_name:
                suites[suite_name] = self.handle_with_suite(suite)
        return suites

    def handle_with_suite(self, suite):
        suite_cases = []
        for test in suite.iter('test'):
            case = self.handle_with_case(test)
            if case:
                suite_cases.append(case)
        return suite_cases

    def handle_with_case(self, test):
        test_name = test.get('name')
        if test_name:
            status = test.find('status', '')
            result = status.get('status', '')
            if self.skip_pass and result == 'PASS':
                return None
            message = status.text if status.text else ""
            return {
                "test_case_name": test_name,
                "result": result,
                "message": message.strip()
            }
        return None

    @staticmethod
    def handle_with_time(root):
        time_info = {}
        generated = root.get('generated')
        time_info.update({'generated': generated or ''})
        status = root.find('.//suite/status')
        elapsed = status.get('elapsed')
        if elapsed:
            elapsed_seconds = int(float(elapsed))
            elapsed_formatted = str(datetime.timedelta(seconds=elapsed_seconds))
            time_info['execution'] = elapsed_formatted
        else:
            time_info['execution'] = "0:00:00"
        return time_info

    def generate_report(self):
        logger.info("Start to generate html report to <{}>.".format(self.log_path))
        env = Environment(loader=FileSystemLoader(PathUtils().pandora_path))
        template = env.get_template('conf/static/report_template_jinja2.html')
        html_content = template.render(self.results)
        report_path = os.path.join(self.log_path, 'report_jinja.html')
        with open(report_path, 'w') as f:
            f.write(html_content)
        logger.info("Report have been generated! ! !")
        logger.info("Report: <{}>.".format(report_path))
        return report_path


if __name__ == '__main__':
    xml_file_path = '../common/log/output.xml'
    parser = RobotLogParser(xml_file_path)
    parser.generate_report()


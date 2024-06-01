# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : log.py
# @Time  : 2024-04-17
import sys
import logging
import json
from robot.api import logger as rf_logger


class RobotFrameworkLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelno
            if level >= logging.CRITICAL:
                rf_logger.error(msg)
            elif level >= logging.ERROR:
                rf_logger.error(msg)
            elif level >= logging.WARNING:
                rf_logger.warn(msg)
            elif level >= logging.INFO:
                rf_logger.info(msg)
            else:
                rf_logger.debug(msg)
        except Exception:
            self.handleError(record)


class SmartJsonFormatter(logging.Formatter):
    def format(self, record):
        self.formatTime(record, self.datefmt)
        message = record.getMessage()
        try:
            json_object = json.loads(message)
            return json.dumps(json_object, indent=4)
        except json.JSONDecodeError as e:
            if "Expecting property name enclosed in double quotes" in str(e):
                message = message.replace("'", '"')
                try:
                    json_object = json.loads(message)
                    return json.dumps(json_object, indent=4)
                except json.JSONDecodeError as e:
                    pass
            else:
                pass
        return super().format(record)


def setup_logger():
    # set logger level
    _logger = logging.getLogger(__name__)
    _logger.setLevel(logging.DEBUG)

    # Robot Framework handler
    rf_handler = RobotFrameworkLoggingHandler()
    rf_handler.setLevel(logging.DEBUG)
    rf_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    rf_handler.setFormatter(rf_formatter)
    _logger.addHandler(rf_handler)

    # Console handler
    # formatter = logging.Formatter('[%(asctime)s](%(levelname)s)(%(name)s): %(message)s')
    formatter = SmartJsonFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    return _logger


logger = setup_logger()


class Log(object):
    name = 'default'
    END = '\033[0m'

    # color sequences
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[1;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[1;34m'
    VIOLET = '\033[35m'
    BEIGE = '\033[36m'

    @classmethod
    def green(cls, msg=None):
        cls.format(color=cls.GREEN, msg=msg)

    @classmethod
    def blue(cls, msg=None):
        cls.format(color=cls.BLUE, msg=msg)

    @classmethod
    def yellow(cls, msg=None):
        cls.format(color=cls.YELLOW, msg=msg)

    @classmethod
    def normal(cls, msg=None):
        cls.format(msg=msg)

    @classmethod
    def red(cls, msg=None):
        cls.format(color=cls.RED, msg=msg)

    @classmethod
    def red_info(cls, msg=None):
        return cls.RED + msg + cls.END

    @classmethod
    def format(cls, color=None, msg=None):
        _msg = color + msg + cls.END if color is not None else msg
        logger.info(_msg)


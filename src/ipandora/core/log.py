# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : log.py
@Time  : 2024-04-24
"""
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
                print(3333)
                message = message.replace("'", '"')
                json_object = json.loads(message)
                return json.dumps(json_object, indent=4)
            else:
                pass
        return super().format(record)


def setup_logger():
    # set logger level
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Robot Framework handler
    rf_handler = RobotFrameworkLoggingHandler()
    rf_handler.setLevel(logging.DEBUG)
    rf_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    rf_handler.setFormatter(rf_formatter)
    logger.addHandler(rf_handler)

    # Console handler
    # formatter = logging.Formatter('[%(asctime)s](%(levelname)s)(%(name)s): %(message)s')
    formatter = SmartJsonFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


logger = setup_logger()

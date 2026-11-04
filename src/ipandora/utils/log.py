# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : log.py
# @Time  : 2024-04-17
import sys
import logging
import json

# `from robot.api import logger` used to sit here, unguarded, and
# setup_logger() always installed a handler that forwarded every record into
# Robot's log. With the Robot adapter gone and robotframework no longer a
# dependency, that import would have failed at the first `import ipandora` --
# the whole package, unusable, from one line in a logging module.


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

    # Console handler
    # formatter = logging.Formatter('[%(asctime)s](%(levelname)s)(%(name)s): %(message)s')
    formatter = SmartJsonFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    return _logger


logger = setup_logger()


def log_to_stderr():
    """
    Send console logging to stderr instead of stdout.

    Required by anything that speaks a protocol over stdout -- an MCP stdio
    server, for instance, where a stray log line lands in the middle of the
    JSON-RPC stream and drops the connection. stderr is free for logs there by
    convention.
    """
    _switched = 0
    for _handler in logger.handlers:
        if isinstance(_handler, logging.StreamHandler) and \
                getattr(_handler, 'stream', None) is sys.stdout:
            _handler.setStream(sys.stderr)
            _switched += 1
    return _switched


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


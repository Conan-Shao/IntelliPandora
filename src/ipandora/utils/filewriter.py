# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : filewriter.py
@Time  : 2024-04-28
"""
import csv
import json
import yaml
import os
from ipandora.utils.log import logger
from ipandora.utils.error import FileError, DataError


class FileWriter(object):
    def __init__(self, filename, content, directory=''):
        self.filename = filename
        self.content = content
        self.directory = directory
        self.handle()

    @property
    def extension(self):
        return '.txt'

    @property
    def asb_path(self):
        return os.path.abspath(self.filename)

    def handle(self):
        if self.filename.endswith('{}'.format(self.extension)):
            pass
        else:
            self.filename += self.extension
        self._handle_base_path()
        self._handle_write()

    def _handle_base_path(self):
        if not os.path.isabs(self.filename):
            if os.path.isabs(self.directory):
                self.filename = os.path.join(self.directory, self.filename)
            else:
                logger.warning(f"The <{self.directory}> is not exist. files will be stored <home>")
                self.filename = os.path.join(os.path.expanduser('~'), self.filename)
        _dir_name = os.path.dirname(self.filename)
        # check directory exists and create if not
        if not os.path.exists(_dir_name):
            os.makedirs(_dir_name)

    def _handle_write(self):
        try:
            self._write()
        except IOError as e:
            raise FileError(f"Failed to write to file {self.filename}: {e}")
        except Exception as e:
            raise FileError(f"An unexpected error occurred: {e}")
        logger.info(f"File <{self.filename}> has been written successfully.")

    def _write(self):
        """ Override this method in subclasses to handle specific file writing logic. """
        raise NotImplementedError("Subclass must implement abstract method")

    def __repr__(self):
        _asb_path = os.path.abspath(self.filename)
        return f"{self.__class__.__name__}(name={self.filename}, asb_path={_asb_path})"


class TextFileWriter(FileWriter):
    """
    TextFileWriter is a class that writes.
    Content should be a string.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        with open(self.filename, 'w', encoding='utf-8') as file:
            file.write(self.content)

    @property
    def extension(self):
        return '.txt'


class CSVFileWriter(FileWriter):
    """
    CSVFileWriter is a class that writes.
    Content should be a list of lists.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        with open(self.filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerows(self.content)

    @property
    def extension(self):
        return '.csv'


class JSONFileWriter(FileWriter):
    """
    JSONFileWriter is a class that writes.
    Content should be a dictionary.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as file:
                json.dump(self.content, file, indent=4)
        except json.JSONDecodeError as exc:
            raise DataError(f"Failed to serialize the content to JSON: {exc}")

    @property
    def extension(self):
        return '.json'


class YAMLFileWriter(FileWriter):
    """
    YAMLFileWriter is a class that writes.
    Content should be a dictionary.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as file:
                yaml.dump(self.content, file, default_flow_style=False)
        except yaml.YAMLError as exc:
            raise DataError(f"Failed to serialize the content to YAML: {exc}")

    @property
    def extension(self):
        return '.yaml'


class RobotFileWriter(FileWriter):
    """
    RobotFileWriter is a class that writes.
    Content should be a string. which has be rendered by RobotRendererLegacy.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        with open(self.filename, 'w', encoding='utf-8') as file:
            file.write(self.content)

    @property
    def extension(self):
        return '.robot'


class HtmlFileWriter(FileWriter):
    """
    HtmlFileWriter is a class that writes.
    Content should be a string. which has be rendered by HtmlRenderer.
    The file will be created in the home directory if filename is not the absolute path.
    """
    def _write(self):
        with open(self.filename, 'w', encoding='utf-8') as file:
            file.write(self.content)

    @property
    def extension(self):
        return '.html'


if __name__ == '__main__':
    resp = YAMLFileWriter("test", {"name": "test"}, directory='/Users/shaofeng/temp_file/')
    print(resp)

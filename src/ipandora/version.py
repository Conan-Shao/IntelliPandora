# -*- coding: utf-8 -*-
# @Author: Shao Feng
# @File  : version.py
# @Time  : 2024-04-17
import re
import os


def get_versions(base_path):
    if not os.path.exists(base_path):
        base_path = os.path.dirname(__file__)
    path = os.path.join(base_path, "CHANGELOG")
    with open(path, "rb+") as f:
        text = str(f.read(), 'utf-8').strip()
    result = re.findall(re.compile(r'(.*)\n*=+'), text)
    return result


def get_latest_version(base_path=''):
    versions = get_versions(base_path)
    if versions == [] or versions is None:
        raise Exception("CHANGELOG Format Error~")
    return str(versions[0]).replace('v', '')

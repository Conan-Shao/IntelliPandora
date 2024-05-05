# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_http_get.py
@Time  : 2024-04-19
"""
import json
import unittest
from httpretty import httprettified, register_uri, GET
from ipandora.core import api
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core import logger


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return {}


PluginManager.endpoints(reg=EndPointPlugin())


class TestHttp(unittest.TestCase):
    @httprettified
    def test_httpbin(self):
        register_uri(
            GET,
            uri="https://httpbin.org/ip",
            body=json.dumps({'origin': '10.0.0.1'})
        )
        response = GetIP().get_ip_info()
        logger.info('\n')
        logger.info(response.data)
        assert response.data.origin == '10.0.0.1'


class GetIP:
    def __init__(self):
        pass

    @api.http.get("https://httpbin.org/ip")
    def get_ip_info(self):
        return {}


if __name__ == '__main__':
    unittest.main()

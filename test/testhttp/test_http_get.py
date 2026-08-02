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
from ipandora.core.assertion import assert_all, json_equals, status_ok
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core.schedule.session import SessionManager
from ipandora.core import logger


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return {}


PluginManager.endpoints(reg=EndPointPlugin())


class TestHttp(unittest.TestCase):

    def setUp(self):
        # httpretty matches on the registered URI, but requests honours
        # HTTP(S)_PROXY from the environment and would instead open a CONNECT
        # tunnel to the proxy -- which httpretty does not recognise, so the
        # "mocked" call escapes to the real network and fails wherever a proxy
        # is configured. Ignoring the ambient env keeps this test hermetic.
        SessionManager._session_map.pop(SessionManager.name(), None)
        SessionManager.getSession().trust_env = False

    def tearDown(self):
        SessionManager._session_map.pop(SessionManager.name(), None)

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
        # Goes through the real decorator -> transport -> ResponseHandler path.
        # status_ok matters: without it this test passed on a 500.
        assert_all(
            status_ok(response),
            json_equals(response, 'origin', '10.0.0.1'),
        )


class GetIP:
    def __init__(self):
        pass

    @api.http.get("https://httpbin.org/ip")
    def get_ip_info(self):
        return {}


if __name__ == '__main__':
    unittest.main()

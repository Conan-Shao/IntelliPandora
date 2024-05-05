# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : innerplugin.py
@Time  : 2024-04-19
"""
from ipandora.core.base.classwrap.multihandle import UploadApiInfo
from ipandora.core.protocol.http.model.data.responseobject import ResponseObject
from ipandora.core.plugin.interface.plugininterface import PluginInterface
from ipandora.core.schedule.runtime import Runtime


class InnerPlugin(PluginInterface):
    upload_api_info = None

    def response(self, response: ResponseObject):
        # upload api detail info
        if Runtime.Option.only_api:
            _url = response.request.url
            if Runtime.Host.report_host not in _url:
                self.upload_api_info = self.upload_api_info or UploadApiInfo()
                _j = {
                    'name': response.request.mark.doc.strip().split('\n')[0],
                    'url': _url,
                    'params': response.request.option.params,
                    'duration': response.total_time,
                }
                self.upload_api_info.put(_j)

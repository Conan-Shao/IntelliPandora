# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : basewrapper.py
@Time  : 2024-04-19
"""
from ipandora.core.base.data.markdata import MarkData
# from pandora.core.initial.encrypt.EncryptManager import EncryptManager
from ipandora.core.plugin import PluginManager


class EndPointApiProxy(object):

    def __init__(self, mark: MarkData = '', path=''):
        self._mark = mark
        self._url_path = path

    @property
    def mark(self):
        return self._mark

    @property
    def endpoint(self) -> dict:

        _endpoint = (self.get_end_point_config().get(self.mark.module, None) or
                     self.get_end_point_config().get('default', None))
        # if not _endpoint:
        #     raise ValueError(
        #         'can not get url item in config info [{}] by mark [{}]'.format(
        #             self.getEndPointConfig(), self.mark.module
        #         ))
        return _endpoint

    def get_path_from_end_point(self):
        _config = self.get_end_point_config()
        return

    def get_end_point_config(self) -> dict:
        """
        get end point file by env config
        :return:
        """

        # get endpoints
        from ipandora.utils.variable import Variable
        _endpoint = Variable().get_endpoints()

        # todo ugly code, need to optimize
        # get endpoints from plugins
        if not _endpoint:
            _ep = PluginManager.run('endpoints', mark=self.mark)
            if isinstance(_ep, list) and _ep:
                for _e_ep in _ep:
                    if _e_ep and isinstance(_e_ep, dict):
                        _endpoint = _e_ep
                        break

        # encrypt endpoints
        # if _endpoint:
        #     _e = EncryptManager.encrypt(variable_name='ENDPOINTS',
        #                                 variable_value=_endpoint)
        #
        #     _endpoint = _e if _e else _endpoint

        # if not _endpoint:
        #     raise ValueError('can not get endpoint config in variables file')
        if _endpoint is None:
            _endpoint = {}
        return _endpoint

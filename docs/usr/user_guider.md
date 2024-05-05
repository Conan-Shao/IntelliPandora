# User Guider of PandoGT
`This is the user guider of PandoGT.`

## 1. 安装说明

## 2. 功能介绍

### 2.1 核心功能
#### 2.1.1 Http
> 列举常见的http接口的调用实现
* **一般接口**

```python
from ipandora.core import api


class EventTrackService(object):

    @api.mark(module='unionPlatform')
    @api.http.post(path="api/union/event/queryAutoCaseCheckResult")
    def get_event_track_result(self, device_id, id_count_map, start_time, end_time):
        _data = {"deviceId": device_id, "startTime": start_time, "endTime": end_time,
                 "idCountMap": id_count_map}
        return dict(json=_data)

```

* **URI带参数**

```python
from ipandora.core import api


class Hit(object):

    @api.mark(module='hit')
    @api.http.post(path="v1/hits/{hitId}")
    def get_hit_detail(self, hitId, _json = None, _params = None):
        return dict(json=_json, params=_params,
                    other_params={"hitId": hitId})

```


* **文件上传**

```python
from ipandora.core import api


class ReportService(object):

    @api.mark(module='unionPlatform')
    @api.http.post(path='api/union/test/s3/upload')
    def upload_point_log(self, _params, _file_items = {}):
        _file_params = {}
        if _file_items:
            for _k, _v in _file_items.items():
                _file_params[_k] = open(_v, 'rb')
        return dict(params=_params, files=_file_params)
```



### 2.2 辅助功能

#### 2.2.1 测试数据注入

```python
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface

ENDPOINTS = {
    "unionPlatform": {"url": "https://adqa.test.gifshow.com",
                      "token": "20005_cc76734266c02094846bdcdc82b3de7d",
                      "user": "shaofeng"}
}


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return ENDPOINTS


PluginManager.endpoints(reg=EndPointPlugin())

```

#### 2.2.2 测试执行参数全局管理 Runtime

```python
import pytest
import os
from ipandora.core.schedule.runtime import Runtime

# 写入
# config 为pytest的配置对象，其他框架可以同理自定义
Runtime.settings = config.option.__dict__
Runtime.Option.project_path = os.path.dirname(os.path.abspath(__file__))

# 获取
_project_path = Runtime.Option.project_path
_os = Runtime.Ui.os
```

#### 2.2.3 命令行能力
* **一键创建工程**
```shell
 ~/Repos/intellipandora ⮀ intellipandora -h
usage: intellipandora [-h] [-v] [-V] {project} ...

positional arguments:
  {project}        intellipandora support these sub-commands.
    project        project command

options:
  -h, --help       show this help message and exit
  -v, --verbosity  log verbosity
  -V, --version    print version
```


### 2.3 kitTools
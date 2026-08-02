# User Guider of Pandora
`This is the user guider of Pandora.`

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



#### 2.1.2 响应数据

`response.data` 会自动剥掉 `data` / `result` 外层包装，返回的对象**同时支持属性和键访问**：

```python
resp.data.origin           # 属性访问
resp.data['x-req-id']      # 键访问 —— 含连字符、Python 关键字的键用这种
resp.data.user.name        # 嵌套
```

字段不存在时报错会列出有哪些字段，不用去翻响应体。

**取列表数据**：

```python
resp.fetch_all()                      # 全部条目
resp.fetch_one()                      # 第一个；没有数据时返回 None
resp.filter(status='ok').fetch_all()  # 过滤后再取
```

`filter` 支持的比较器与断言层一致：`$gt` `$in` `$notIn` `$contains` `$startWith` `$eq`。

各种响应形态的行为：

| 响应 | `fetch_all()` |
|---|---|
| `{"data":[{...},{...}]}` | 两个条目 |
| `{"data":{...}}` | **一个**条目（不会被拆成字段值） |
| `{"data":null}` | `[]` |
| `{"data":5}` | `[5]` |
| 非 JSON（HTML/二进制） | 原样返回 str / bytes |

> `fetch_all()` 是**消耗性**的：它会清掉已应用的 filter，让下次查询从完整响应重新开始。`len(resp)` 不消耗。

#### 2.1.3 传输行为（超时 / 重试 / TLS）

框架给每个请求都套了默认策略，**不需要在用例里写这些**：

| 项 | 默认值 | 说明 |
|---|---|---|
| 超时 | 连接 10s / 读取 30s | 每个请求都有界，不会挂死套件 |
| TLS 校验 | **开启** | 关掉就发现不了证书过期 |
| 重试 | 2 次，指数退避 | **仅幂等方法**，仅 429/502/503/504 |
| 连接池 | 10 | |

改默认值在 `conf/config.yaml` 的 `http:` 段。单次调用要覆盖就直接传：

```python
@api.http.get(path="v1/slow-report")
def get_report(self):
    return dict(timeout=120)          # 这个接口就是慢
```

**为什么 POST 不重试**：重放可能造成重复提交。需要的话自己在用例里控制。

**为什么 500 不重试**：500 是真实缺陷，重试只会把确定的失败伪装成偶发。

**传输失败与断言失败是两回事**：

```python
from ipandora.utils.error import HttpTimeoutError, TransportError

try:
    resp = Client().fetch()
except HttpTimeoutError as e:
    # 压根没拿到响应，没有东西可断言
    print(e.url, e.method, e.elapsed)
```

`HttpTimeoutError` / `HttpConnectionError` 都继承自 `TransportError`，同时也继承对应的 `requests` 异常 —— 既有的 `except requests.exceptions.Timeout` 照常生效。

#### 2.1.4 断言

> 断言是"判定对错"的地方。**每个 HTTP 测试都应该有 `status_ok`** —— 没有它，接口返回 500 测试照样 PASS。

```python
from ipandora.core.assertion import assert_all, status_ok, json_equals

def test_get_user():
    resp = UserService().get_user(uid=1)
    assert_all(
        status_ok(resp),
        json_equals(resp, 'data.id', 1),
        json_equals(resp, 'data.name', 'alice'),
    )
```

**为什么是 `assert_all` 而不是一串 `assert`**

每个 check 是一个**值**，构造时不抛异常。所以 `assert_all` 能把全部判定都跑完，一次告诉你所有问题：

```
Assertion failed (2/3 checks failed)

  [FAIL] 请求成功 (2xx) (api) | status = 500
  [FAIL] data.id == 1 (api) | data.id = 7 (expected 1)

  passed: data.name == 'alice'
```

用一串 `assert` 的话，你只会看到第一个失败，修完再跑才发现第二个。

**可用的判定**

| 函数 | 用途 |
|---|---|
| `status_ok(resp)` | 2xx |
| `status_is(resp, 201)` | 精确状态码 |
| `header_is(resp, 'Content-Type', 'application/json')` | 响应头 |
| `json_has(resp, 'data.token')` | 字段存在（值为 null 也算存在） |
| `json_equals(resp, 'data.id', 1)` | 字段等于 |
| `json_matches(resp, 'data.total', {'$gt': 0})` | 比较器：`$gt` `$in` `$notIn` `$contains` `$startWith` `$eq` |
| `schema_conforms(resp, schema)` | JSON Schema 校验 |

路径支持点号与下标：`data.items[0].name`、`items[-1].id`。

**前置条件用 `require`，不用 `assert_all`**

```python
from ipandora.core.assertion import require, Check

require(Check(name='账号有余额', ok=wallet.balance > 0,
              expr='balance = {}'.format(wallet.balance)))
```

前置不满足会 **skip** 而不是 fail。这个区分很重要：「账号没钱」和「代码坏了」在看板上必须长得不一样，否则跑久了没人再看红灯。

**自定义判定**

返回 `Check` 即可，会自动被 `assert_all` 收集：

```python
from decimal import Decimal
from ipandora.core.assertion import Check, Source, json_value

def fee_within_cap(resp, cap):
    # json_value 返回 (值, 失败原因)；原因非空表示 body 解析失败或路径不存在
    fee_raw, err = json_value(resp, 'data.fee')
    if err:
        return Check(name='手续费在上限内', ok=False, expr=err, src=Source.DERIVED)
    fee = Decimal(str(fee_raw))
    return Check(name='手续费在上限内', ok=fee <= cap,
                 expr='fee {} <= cap {}'.format(fee, cap), src=Source.DERIVED)
```

两条约束：

- **不要抛异常。** 字段缺失、body 不是 JSON，都应该返回 `ok=False` 的 Check。一旦抛出，`assert_all` 就退化成"第一个失败就停"，失去了意义 —— 所以用 `json_value` 而不是 `body['fee']`。
- **`expr` 要写足证据。** 失败时应该不用翻日志就能看懂。

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

**配置是进程级懒缓存的** —— 首次读取后就记住了。测试里改过配置要还原，用 `reset`：

```python
Runtime.Http.verify = False
...
Runtime.reset('Http')     # 恢复该段默认值
Runtime.reset()           # 恢复全部
```

不还原的话，这个覆盖会泄漏给后面所有测试。

#### 2.2.3 用例步骤记录

`Runtime.Case` 的状态是 **thread-local** 的，并发跑用例不会互相串号：

```python
Runtime.Case.cur_case_name = 'test_send'
Runtime.Case.steps = [url, headers, params, body]   # 追加一条

Runtime.Case.steps          # 读取，非破坏性
Runtime.Case.drain_steps()  # 取走并清空
Runtime.Case.clear()        # 清掉当前线程的全部记录
```

#### 2.2.4 以库方式执行测试

不用起子进程、不用解析 stdout：

```python
from ipandora.core.runner import run, explain

result = run('test/testapi', env='dev')

result.ok          # 全过才是 True
result.headline()  # '5 passed, 1 failed'
result.failures    # 失败的 CaseResult 列表
result.summary()   # 裁剪过的 dict，适合给 agent / 存报告

explain(result.run_id)   # 完整 traceback，按需取
```

**为什么 `summary()` 和 `explain()` 分开**：`summary()` 只带失败用例名和断言消息；完整 traceback 留在 run store 里按 `run_id` 取。给 agent 灌几千行 pytest 日志只会淹掉它的上下文。

`selector` 可以是路径、pytest nodeid，或 `-k` 表达式；留空跑全部。

几个注意点：

- **选择器匹配不到东西时 `ok` 是 `False`** —— 打错一个字不会被当成"全部通过"
- **stdout 归调用方所有**：如果你自己在 stdout 上跑协议（比如 MCP stdio），传 `quiet=True`，并调 `ipandora.utils.log.log_to_stderr()`
- 运行记录存在 `~/.ipandora/runs`（`IPANDORA_RUNS_DIR` 可改），保留最近 50 次
- pytest 在**当前进程内**执行，测试模块会被导入且保持导入状态；需要完全干净的环境请用新进程

#### 2.2.5 MCP 能力面

`ipandora mcp` 启动后暴露 4 个工具：

| tool | 用途 |
|---|---|
| `run_tests(selector, env)` | 跑用例，返回摘要 |
| `explain_failure(run_id)` | 取完整失败现场 |
| `list_runs(limit)` | 最近的 run_id |
| `get_test_report(xml_file)` | 解析 Robot Framework 的 output.xml |

典型闭环：`run_tests` → 有失败 → `explain_failure(run_id)` → 改代码 → 再 `run_tests`。

#### 2.2.6 命令行能力

```shell
 ~/Repos/intellipandora ⮀ ipandora -h
usage: ipandora [-h] [-v] [-V] {mcp} ...

positional arguments:
  {mcp}            ipandora support these sub-commands.
    mcp            start the MCP server exposing IntelliPandora capabilities
                   to AI clients

options:
  -h, --help       show this help message and exit
  -v, --verbosity  log verbosity
  -V, --version    print version
```

> 脚手架子命令 `project` 已在 P0 归档 —— agent 直接写文件比 scaffold 更可控。历史代码见提交 `5e0065e`。


### 2.3 kitTools
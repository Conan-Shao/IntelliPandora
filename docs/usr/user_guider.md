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

    @api.mark(module='eventPlatform')
    @api.http.post(path="api/event/track/queryCheckResult")
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

    @api.mark(module='eventPlatform')
    @api.http.post(path='api/event/file/upload')
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

`filter` 支持的比较器与断言层一致，见 [2.1.4 断言](#214-断言) 的比较器表。

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
| `json_matches(resp, 'data.total', {'$gt': 0})` | 比较器，见下表 |
| `schema_conforms(resp, schema)` | JSON Schema 校验 |

路径支持点号与下标：`data.items[0].name`、`items[-1].id`。

**比较器**（`json_matches` 与 `filter` 共用）

| 运算符 | 含义 | 例 |
|---|---|---|
| `$eq` `$gt` `$gte` `$lt` `$lte` | 相等 / 大小；操作数是数字时按数字比 | `{'$gt': 0}` |
| `$in` `$notIn` | 属于 / 不属于 | `{'$in': ['ok', 'pending']}` |
| `$contains` | 子串，**不区分大小写** | `{'$contains': 'success'}` |
| `$startWith` | 前缀 | `{'$startWith': 'ORD-'}` |
| `$regex` | `re.search`，只匹配字符串；要整值匹配自己加 `^…$` | `{'$regex': r'^\d+\.\d+\.\d+$'}` |

一个条件里写多个运算符表示**同时成立**，区间就这么写：`{'$gte': 0, '$lte': 100}`。

比较器**不做猜测**：
- 数字按 `float` 比，不截断——`5.9` 不等于 `5`，`0.9 > 0` 成立
- 布尔不当数字：`true` 不等于 `1`；`{'$eq': True}` 只认真正的 `true`，不认 `"false"` 这种非空字符串
- `$regex` 不把数字转成字符串去匹配
- 不认识的运算符（包括没写 `$` 的键）

这些情况都是**失败的 Check，并写明原因**，不会抛异常打断同一次 `assert_all` 里的其他判定。

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
import os

from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface

# 端点地址可以写死，凭据不行：仓库是公开的。
ENDPOINTS = {
    "eventPlatform": {"url": "https://api.example.com",
                      "token": os.environ["EVENT_PLATFORM_TOKEN"],
                      "user": os.environ["EVENT_PLATFORM_USER"]}
}


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return ENDPOINTS


PluginManager.endpoints(reg=EndPointPlugin())

```

#### 2.2.2 配置文件与环境（`conf/`）

配置放在**你的用例项目**里，不用改装好的包：

```
your-suite/
├── conf/
│   ├── config.yaml      # 本项目的默认配置，覆盖框架自带默认值
│   ├── staging.yaml     # ipandora run -e staging 时叠加
│   └── prod.yaml
└── tests/
```

```yaml
# conf/config.yaml —— 只写要改的键，其余沿用框架默认
http:
  read_timeout: 60
```

```yaml
# conf/staging.yaml
base_url: https://staging.example.com    # 框架不认识的键，留给你的用例自己读
http:
  verify: false        # 只在这个一次性环境关
```

```shell
ipandora run tests -e staging
```

框架只读 `http` / `ai` / `mcp` 三段。其他键（如上面的 `base_url`）原样留在 `Runtime.settings` 里，由你的端点插件（见 [2.2.1](#221-测试数据注入)）自己取：

```python
from ipandora.core.schedule.runtime import Runtime

class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark):
        return {"svc": {"url": Runtime.settings.get("base_url", "http://localhost:8080")}}
```

叠加顺序（后者覆盖前者）：

1. 框架自带 `ipandora/conf/config.yaml`
2. 项目目录 `conf/config.yaml`
3. 项目目录 `conf/<env>.yaml`（仅本次运行）

项目目录默认是**当前工作目录下的 `conf/`**；设了环境变量 `IPANDORA_CONFIG_DIR` 就用它（CI 里从别处取配置时用）。

几条行为：

- **深合并**：`staging.yaml` 写 `ai: {enabled: true}` 只改 `enabled`，`ai.model` 等其余键保留
- **只作用于这一次运行**：`run()` 结束后配置恢复原样。同一进程里连续跑（MCP server 就是这样），上一次的环境不会串到下一次
- **找不到环境文件会打 WARNING**，并列出找过的路径——`-e stagnig` 这种拼写错误不会悄悄用默认配置跑完
- `-e` 只接受名字，不接受路径
- 旧位置（装好的包目录里的 `conf/<env>.yaml`）仍然能读到，但会提示迁到项目目录

#### 2.2.3 测试执行参数全局管理 Runtime

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

#### 2.2.4 用例步骤记录

`Runtime.Case` 的状态是 **thread-local** 的，并发跑用例不会互相串号：

```python
Runtime.Case.cur_case_name = 'test_send'
Runtime.Case.steps = [url, headers, params, body]   # 追加一条

Runtime.Case.steps          # 读取，非破坏性
Runtime.Case.drain_steps()  # 取走并清空
Runtime.Case.clear()        # 清掉当前线程的全部记录
```

#### 2.2.5 以库方式执行测试

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

#### 2.2.6 失败归因

跑完之后可以问"这些失败是什么性质的"：

```python
from ipandora.core.runner import run
from ipandora.core.triage import triage

report = triage(run('test/testapi', quiet=True))
report.headline()        # '2 defect, 1 environment'
report.product_failures  # 只有真正归咎于被测系统的那些
```

| 类别 | 含义 | 该找谁 |
|---|---|---|
| `defect` | 断言失败，系统返回了错的值 | **被测系统** |
| `contract` | 只有 schema 检查失败 | **被测系统**，接口变了 |
| `environment` | 传输失败，没拿到响应 | 环境/网络，**什么都没测到** |
| `data` | 前置不满足（`require` skip） | fixture / 账号状态 |
| `harness` | setup 炸了 | 测试自身 |
| `unknown` | 签名不认识 | 看完整 traceback |

**为什么要区分**：把"连不上服务器"和"服务器答错了"混在一起报，是让人不再看红灯的最快方式。`report.product_failures` 只给你真正该查代码的那些。

这一层是**纯规则、离线、零成本**，永远开着。

**可选：让 LLM 补一句根因**

```python
# conf/config.yaml -> ai.enabled: true, ai.provider, ai.api_key
import ipandora.ai
ipandora.ai.enable()
```

开启后 `explain_failure(run_id)` 的返回里会多一个 `triage.analysis` 字段。

- **默认关闭**，`pip install intellipandora` 连 LLM SDK 都不装（要装：`pip install intellipandora[ai]`）
- **它不决定类别**，只在规则分类之上补一句自然语言
- **成本随失败数增长，不随测试规模**：全绿的运行 0 次调用；一次运行最多调 1 次，不是每条失败一次
- **预算闸**：`ai.max_calls_per_run`，设 0 就是完全禁止
- **fail-open**：模型不可用只是少一段分析文字，**绝不改变测试结论**

#### 2.2.7 生成报告

```python
from ipandora.core.runner import run
from ipandora.core.report import build, write

report = build(run('test/testapi', quiet=True), title='每日回归')
write(report, 'out/')        # 产出 out/report.html + out/report.json
```

HTML 和 JSON 出自同一份数据。**脱敏在 `build()` 时完成，不在渲染时** —— 报告会被下载、转发、进 CI artifact，只在模板里遮，背后的 JSON 照样能读。

会被掩码的东西，靠两个独立信号识别：

- **字段名**：`password` `token` `api_key` `mnemonic` `signedTx` `Authorization` `Cookie` …
- **值的形状**：以太坊私钥 `0x[64位hex]`、JWT、`sk-` 前缀、AWS AKIA、PEM 私钥块、助记词

宁可多掩码 —— 误掩码只是让人多跑一次，泄漏的凭据收不回来。

**报告会显示"什么都没证明"的部分**：

| 状态 | 含义 |
|---|---|
| `SKIPPED` | 前置不满足 |
| `BLOCKED` | 写了但上游失败没跑到 |
| `GAP` | 该有的断言没写（需自行声明，跑一次是推不出来的） |

`pass_rate` **只算有结论的用例**。跳过一半用例的套件不是 100% 健康。

#### 2.2.8 MCP 能力面

`ipandora mcp` 启动后暴露 4 个工具：

| tool | 用途 |
|---|---|
| `run_tests(selector, env)` | 跑用例，返回摘要 |
| `explain_failure(run_id)` | 取完整失败现场 |
| `list_runs(limit)` | 最近的 run_id |
| `build_report(run_id, directory)` | 为某次运行生成 HTML + JSON 报告 |
| `get_test_report(xml_file)` | 解析 Robot Framework 的 output.xml |

典型闭环：`run_tests` → 有失败 → `explain_failure(run_id)` → 改代码 → 再 `run_tests`。

#### 2.2.9 命令行能力

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
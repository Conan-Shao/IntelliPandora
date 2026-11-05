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
resp.filter(status='ok').fetch_all()  # 字段等于（严格：'0' 不等于 0）
resp.filter(lambda x: x['amount'] > 1000).fetch_all()   # 任意条件，直接写 Python
resp.filter(lambda x: 0 <= x['fee'] <= 100, type='A')   # 两种可以一起用
```

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
| `field(resp, 'data.total') > 0` | 用 Python 运算符判断字段，见下 |
| `schema_conforms(resp, schema)` | JSON Schema 校验 |

路径支持点号与下标：`data.items[0].name`、`items[-1].id`。

**用 `field` 判断字段**

用例是 Python，判断就直接写 Python 运算符。`field()` 的每次比较返回一个 Check，而不是 `True/False`：

```python
from ipandora.core.assertion import assert_all, status_ok, field

assert_all(
    status_ok(r),
    field(r, 'data.fee') >= 0,
    field(r, 'data.fee') <= 100,                       # 或者 0 <= field(r, 'data.fee') <= 100
    field(r, 'data.status').is_in(['ok', 'pending']),
    field(r, 'data.code').startswith('ORD-'),
    field(r, 'data.version').matches(r'^\d+\.\d+\.\d+$'),
    field(r, 'data.items').len() > 0,
    field(r, 'data.fee', name='手续费不超上限') <= 100,  # 自定义报告里的名字
)
```

| 写法 | 含义 |
|---|---|
| `==` `!=` `<` `<=` `>` `>=` | 比较 |
| `.is_in([...])` `.not_in([...])` | 属于 / 不属于 |
| `.contains(x)` | 字符串含子串（区分大小写）/ 列表含元素 / 对象含键 |
| `.startswith(s)` | 前缀 |
| `.matches(pattern)` | `re.search`；整值匹配自己加 `^…$` |
| `.len()` | 长度，再接比较：`.len() > 0` |
| `.decimal()` | 转成精确的 Decimal 再比较，用于字符串形式的数字（如 `"100.50"`） |
| `.each(path)` | 列表的每一项都要满足，失败时指出是第几项 |
| `.map(fn, label)` | 对值做任意计算，得到新的 field |
| `field(...) == field(...)` | 两个字段互相比较 |

**常见场景**

```python
from decimal import Decimal
from ipandora.core.assertion import assert_all, field, that

items = field(r, 'data.items')
assert_all(
    # 金额是字符串：显式转成数字。默认不转，因为接口偷偷把数字改成字符串本身就是问题
    field(r, 'data.amount').decimal() > 0,

    # 每一项都满足 —— 失败时：data.items[*].price > 0 — 1 of 3 items failed: data.items[1].price = Decimal('-1')
    items.len() > 0,
    items.each('price').decimal() > 0,
    items.each('sku').matches(r'^SKU-\d+$'),

    # 跨字段：总价等于明细之和
    field(r, 'data.total').decimal() == items.map(
        lambda xs: sum(Decimal(x['price']) for x in xs), '明细合计'),

    # 不是来自这个响应的值：数据库、另一个接口、页面上的文字
    that(db_row['state'], 'db.state') == 'PAID',
)
```

- `.each()` 遇到**空列表默认判失败**：对零个元素说"每一项都对"永远成立，往往说明查询本身坏了。空列表确实合法时，写 `each('price', allow_empty=True)`
- `.map()` 里的函数抛出任何异常（比如某一项缺了键导致 KeyError），都会变成一条失败的 Check，并带上异常信息，不会让用例崩掉
- `that()` 判断出来的 Check 来源记为 `derived`，报告和归因据此区分它和接口返回的字段

失败时直接给出证据：`data.fee = 150 (expected <= 100)`；字段不存在时说明路径在哪一层断了。

**比较是严格的**——测试框架替你"猜"，就会把契约变化藏起来：

- 按值本来的类型比：JSON 里的字符串 `"12"` 不会被当成数字 12。接口把数字改成了字符串，这本身就是要发现的问题
- 布尔不是数字：Python 里 `True == 1`，这里不算相等（`json_equals` 同样如此）
- 数字不截断：`5.9` 不等于 `5`
- 不能比较的情况（字段缺失、类型不符、正则写错）都是**失败的 Check 并写明原因**，不会抛异常打断同一次 `assert_all` 里的其他判定
- `field(...)` 本身不能当布尔用：`if field(r, 'x'):` 会直接报错，避免写出永远为真的判断

更复杂的判断，用 `json_value` 取值后自己构造 `Check`，见下文。

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

#### 2.1.5 判定清单与基线：这次通过可不可信

pytest 只告诉你有没有失败。`ipandora run` 还会记下**每条用例实际做了哪些判定**，并和基线比对。

**哪些算判定**（运行时自动记录，不用改用例）：

| 来源 | 记成什么 |
|---|---|
| `assert_all` / `field` / `that` / `status_ok` 等 | 判定本身：`data.fee <= 100` |
| 成立的原生 `assert`，包括辅助函数里的 | 源码表达式加实际值：`assert fee <= 100`（`50 <= 100`） |
| `pytest.raises` / `pytest.warns`，上下文和函数两种写法 | `raises KeyError` |
| `assert True`、`assert 1` 这类字面量 | **不算**：它不可能失败 |

**零判定。** 用例通过了，却一条判定都没有，状态记为 `UNVERIFIED`（"?"），不计入通过率；命令行、报告、MCP 都会点名，JUnit 里写成 `skipped type="unverified"`。确实不需要断言的用例（比如只验证"不崩"），写一句 `gap('…', '理由')` 说明即可。unittest / doctest 风格的用例不做这个判断，因为它们的 `assertEqual` 不是 assert 语句，框架看不见。

**基线与门禁：**

```shell
ipandora run tests --update-baseline     # 接受这次的判定，写入 conf/judgements.json
git add conf/judgements.json             # 和用例一起提交

ipandora run tests --fail-on-weakened    # CI：判定比基线弱就失败
```

和基线比，会标出这些变化：

```
判定变化（对比 conf/judgements.json）：4 处变弱，1 处其他变化
  ~ 放宽  test_fee  assert fee <= 100 → assert fee <= 1000
  - 删除  test_items  data.items[*].price > 0
  → 改为跳过  test_refund  原本通过  (环境不稳定)
  ○ 零判定  test_cancel  通过，但没有任何判定  (基线里有 1 条判定)
  + 新用例  test_new  1 条判定
```

| 变化 | `--fail-on-weakened` 拦不拦 |
|---|---|
| 删除、放宽（数值上下限变宽）、改变（期望值不同）、改为跳过、被 `-m` 排除、零判定、用例删除 | 拦 |
| 收紧、新增判定、新用例 | 不拦 |

"改变"也拦，是因为 `== 100` 改成 `== 200` 可能是需求变了，也可能是有人为了让测试通过，把期望值改成了错误的输出，只有人能判断是哪一种。确认是有意的改动后，跑一次 `--update-baseline`，基线文件的 diff 会和用例改动一起出现在 PR 里，评审人看这几行就知道判定变了什么。

**建议给 `conf/judgements.json` 设 CODEOWNERS。** 这样 agent 仍然可以随便改用例，但没法在没人看见的情况下把判定改弱。

其他说明：

- 失败的用例不参与比对：它中途就停了，没执行到的判定不能算"删除"
- 只跑一部分用例（`ipandora run tests/test_a.py`）时，不会把没跑到的用例报成"删除"
- 判定写在测试目录之外的普通模块里时，pytest 不会改写那个模块的 assert，所以看不到。用 `pytest.register_assert_rewrite('your.module')` 注册一下即可
- 关掉比对：`--no-baseline`；指定别的基线文件：`--baseline PATH`
- MCP 的 `run_tests` 返回里带 `unverified`、`judgements_weakened`、`judgement_changes` 三个字段

#### 2.1.6 并行执行

```shell
pip install intellipandora[parallel]

ipandora run tests --workers 4          # 4 个进程；auto = 每个 CPU 一个
ipandora run tests --workers auto --timeout 120   # 单条用例超过 120 秒判失败
```

**并行跑的结论和串行完全一样**：判定清单、零判定、基线比对、报告里的用例顺序都一致，只是更快。等待接口响应为主的套件，4 个进程的耗时约为串行的三分之一。

底层是 pytest-xdist（多进程，不是多线程：fixture、Playwright、HTTP 会话都不是线程安全的）。判定是在每个进程里记下的，`ipandora run --workers` 会把它们连同请求证据一起带回主进程；直接用 `pytest -n 4` 也能跑，但没有判定清单。

**共享资源**：多条用例要用同一个测试账号、同一笔固定的订单时，声明出来，它们就不会同时执行：

```python
@pytest.mark.resource('account:vip')
def test_upgrade(): ...

@pytest.mark.resource('account:vip')
def test_downgrade(): ...      # 和 test_upgrade 不会同时跑；其他用例照常并行

@pytest.mark.resource('account:vip', 'order:42')   # 可以同时占用多个
def test_refund(): ...
```

- 只锁真正冲突的用例，不像 `xdist_group` 那样把整组挪到一个进程里串行。
- 串行运行也会加锁，所以同一台机器上的两次运行（两个 CI 作业、你和 MCP server）也不会撞上同一个账号。
- 等锁超过 300 秒（环境变量 `IPANDORA_RESOURCE_TIMEOUT` 可改），用例记为 error，归因为**环境问题**，不算产品缺陷。
- **只管同一台机器**。多台机器、多个 CI runner 共用一个账号时需要分布式锁，目前不支持；这种情况请给每台机器分配不同的账号。

**超时**：`--timeout` 用 pytest-timeout 实现。一条卡住的用例会一直占着一个进程，并行时更难发现。超时的用例判失败，归因为环境问题（多半是依赖的服务不响应；如果是被测系统自己卡死，那就是缺陷）。

**库调用和 MCP**：`run('tests', workers=4, timeout=120)`；MCP 的 `run_tests(selector, env, workers)`。没装 `parallel` 却要求并行时会直接报错并提示安装，不会悄悄改成串行。

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

![用 MCP 和不用 MCP](../dev/static/mcp_vs_cli.svg)

MCP 是**可选的**：只有让 AI agent（Claude Code、Cursor 等）来跑用例时才需要。框架本身就是 MCP server，不用另外部署。它和命令行调的是同一个 `run()`，测试能力完全一样。

**接入**（在用例项目根目录下；server 会从这里读取 `./conf`）：

```shell
pip install intellipandora[mcp]
claude mcp add intellipandora -- ipandora mcp      # Claude Code
```

其他客户端配置 `.mcp.json`：

```json
{"mcpServers": {"intellipandora": {"command": "ipandora", "args": ["mcp"]}}}
```

**4 个工具**：

| tool | 用途 |
|---|---|
| `run_tests(selector, env, workers)` | 跑用例，返回摘要：失败名、断言信息、归因。`workers` 大于 1 时并行 |
| `explain_failure(run_id)` | 按需取完整失败现场（traceback、证据） |
| `list_runs(limit)` | 最近的运行，用来比较回归 |
| `build_report(run_id, directory)` | 为某次运行生成 HTML + JSON 报告，给人看 |

典型闭环：`run_tests` → 有失败 → `explain_failure(run_id)` → 改代码 → 再 `run_tests`。摘要刻意保持精简，细节按 `run_id` 再取，避免撑爆 agent 的上下文。

#### 2.2.9 命令行能力

```shell
 ~/Repos/intellipandora ⮀ ipandora -h
usage: ipandora [-h] [-v] [-V] {mcp,run} ...

positional arguments:
  {mcp,run}        ipandora support these sub-commands.
    mcp            start the MCP server exposing IntelliPandora capabilities
                   to AI clients
    run            run a suite and write its HTML report into the run history

options:
  -h, --help       show this help message and exit
  -v, --verbosity  log verbosity
  -V, --version    print version
```

> 脚手架子命令 `project` 已在 P0 归档 —— agent 直接写文件比 scaffold 更可控。历史代码见提交 `5e0065e`。


### 2.3 kitTools
# 组织用例库

接口定义、造数步骤、页面对象和用例分开放，判定只写在用例里。设计依据见 [决策记录 17](../design/decisions/17-登录态与用例组织.md) §3。

## 生成一个分层的项目

```shell
ipandora init --layout full my-tests
cd my-tests
ipandora run tests
```

```
my-tests/
├─ conf/                 配置；judgements.json 判定基线
├─ apis/                 接口层：每个服务一个模块，每个资源一个类，每个接口一个方法
├─ flows/                业务步骤：多步造数（下单 → 支付），接口用例和 Web 用例共用
├─ pages/                页面层：每个页面或组件一个类，定位器和操作
├─ data/                 造数工厂、参数化数据
├─ tests/
│  ├─ api/               接口用例
│  ├─ web/               Web 用例（需要 intellipandora[web]，没装时跳过并说明原因）
│  └─ conftest.py        地址、客户端等 fixture
├─ conftest.py           登录提供者；示例里还有一个本机的演示服务
└─ pytest.ini            pythonpath = .
```

不加 `--layout full` 时生成的是最小项目：一个示例文件，适合先跑通。两种结构框架都不依赖目录名。

## 各层做什么、不做什么

| 层 | 做什么 | 不做什么 |
|---|---|---|
| `apis/` | 声明接口：路径、方法、参数；返回响应 | 不判定；不登录（登录在提供者里，见 [登录态](auth.md)）；不写死地址 |
| `pages/` | 定位器（优先 `get_by_role`、`get_by_label`、`get_by_test_id`）和操作 | 不判定；不 `sleep`，Playwright 会自己等待 |
| `flows/` | 多步造数，返回造出来的数据 | 不判定；造数失败用 `require()`，报"前置条件不满足"，不让用例失败 |
| `data/` | 工厂函数为每条用例生成唯一数据，方便并行 | 不放口令 |
| `tests/` | 一条用例一个行为；文档字符串第一行是标题；`assert_all` / `expect` 判定，`require` 前置，`@pytest.mark.dims` 进覆盖矩阵 | 不直接调 `requests`，不拼 URL，不 `sleep`（用 `eventually`） |

**为什么判定只放在 `tests/`**：判定写在页面类里也会被记录，不会漏；但写在用例里，读用例就知道它在验证什么，评审判定的改动也只看 `tests/` 的 diff。`.github/CODEOWNERS` 可以给 `tests/` 和 `conf/judgements.json` 指定负责人。

## 用例长什么样

```python
from decimal import Decimal

import pytest

from flows.orders import paid_order
from ipandora.core import auth
from ipandora.core.assertion import assert_all, field, status_ok


@pytest.mark.dims(role='buyer', channel='api')
def test_refund_of_a_paid_order_returns_the_full_amount(shop_url, orders):
    """已支付的订单全额退款，退款金额等于实付金额"""
    order = paid_order(shop_url, identity='buyer', amount='100.50')     # 造数
    with auth.identity('buyer'):
        r = orders.refund(order.id)                                    # 动作
    assert_all(                                                        # 判定
        status_ok(r),
        field(r, 'data.refund_amount').decimal() == Decimal(order.amount),
        field(r, 'data.status') == 'REFUNDED',
    )
```

用例写成函数。只有要共用 fixture 或标记时才用类分组。

## 数据驱动：用例是 Python，输入放在数据文件里

同一个行为要用很多组输入时，用参数化，数据放在 `data/`：

```yaml
# data/refunds.yaml
- id: whole-yuan
  amount: '100.00'
  dims: {role: buyer, channel: api}
- id: with-fen
  amount: '0.01'
  dims: {role: buyer, channel: api}
```

```python
import pytest

from ipandora.core.cases import cases


@pytest.mark.parametrize('case', cases('data/refunds.yaml'))
def test_a_refund_returns_exactly_what_was_paid(case, shop_url, orders):
    amount = case.amount          # case.amount 和 case["amount"] 都可以
```

- 每一行是一次运行：`id` 是测试 id，`dims` 等同于 `@pytest.mark.dims(...)`，会进入覆盖矩阵，其余字段交给用例，`case.amount` 和 `case['amount']` 都能读。
- 支持 YAML、JSON、CSV。CSV 的值都是文本，金额这类数字要在用例里转换（`.decimal()`）；列名写成 `dims.role` 的进入 dims。
- 路径相对于调用它的用例文件查找，找不到就往上一级目录找，所以 `tests/api/` 里写 `data/refunds.yaml` 能找到项目的 `data/`。
- id 重复、文件为空、行不是映射，都直接报错。文件为空时参数化的用例一次都不会运行，却会显示为通过。
- 不做 YAML 写步骤的用例。步骤和判定留在 Python 里，判定清单、零判定检测和 IDE 才看得到。

## `No module named 'apis'`

`ipandora run` 用 `--import-mode=importlib` 导入用例，这种方式不会把项目根目录放进导入路径。所以 `tests/` 里 `from apis.orders import ...` 需要项目根目录的 `pytest.ini`：

```ini
[pytest]
pythonpath = .
```

`--layout full` 生成的项目已经带上。缺了这一行时，`ipandora run` 会在失败信息后面提示要加什么。

## Page Object

要，但要薄：页面类只放定位器和操作，判定留在用例里；页面里重复出现的部分（购物车、导航）做成组件类。框架的定位器记忆对任何选择器都生效；用 `get_by_role` 时，"选择器失效还是元素没了"的判断最准，因为记下的就是角色和名称。

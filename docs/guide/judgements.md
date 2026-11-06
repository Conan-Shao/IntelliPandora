# 判定、零判定与基线

断言怎么写，以及框架怎么回答"这次通过可不可信"。

## 断言

先看一个完整、可以直接运行的例子。`that()` 判断任意 Python 值，`field(r, 'data.x')` 判断接口响应里的字段，两者的运算符和方法完全一样：

<!-- run -->
```python
from decimal import Decimal
from ipandora.core.assertion import assert_all, that

order = {'status': 'PAID', 'fee': 50, 'amount': '100.50',
         'items': [{'sku': 'SKU-1', 'price': '60.50'}, {'sku': 'SKU-2', 'price': '40.00'}]}

assert_all(
    that(order['status'], 'order.status') == 'PAID',
    that(order['fee'], 'order.fee') <= 100,
    that(order['amount'], 'order.amount').decimal() == Decimal('100.50'),
    that(order['items'], 'order.items').len() > 0,
    that(order['items'], 'order.items').each('price').decimal() > 0,
    that(order['items'], 'order.items').each('sku').matches(r'^SKU-\d+$'),
)
```

判定失败时，`assert_all` 一次报出全部失败，而不是停在第一个。比较是严格的：字符串 `'12'` 不等于数字 `12`。

```text
Assertion failed (2/2 checks failed)

  [FAIL] order.fee <= 10 (derived) | order.fee = 50 (expected <= 10)
  [FAIL] order.count == 12 (derived) | order.count = '12' (expected 12)
```

下面是各种写法的细节。

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

路径支持点号与下标：`data.items[0].name`、`items[-1].id`，含点号的键用引号：`releases['2.32.0'].url`。写错的路径（`data..items`、`items[0`）直接判为不成立并说明原因，不会被读成另一条路径。

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
| `.decimal()` | 转成精确的 Decimal 再比较，用于字符串形式的数字（如 `"100.50"`）。和 float 比较时按写出来的样子比：`.decimal() == 0.1` 成立。`"1_000"` 不算数字 |
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

## 等待最终一致：eventually()

写到一个节点、从另一个节点读回；支付后订单状态要等队列消费者处理完才变成 `PAID`。这类判定不要写 `time.sleep(3)`：短了，慢的那天就失败；长了，每天都慢；出错时也说不清读到了什么。

`eventually()` 在截止时间内反复读，直到判定成立或时间用完。它返回一个 Check，和其他判定一起交给 `assert_all`：

<!-- run -->
```python
import itertools
from ipandora.core.assertion import assert_all, eventually, that

reads = itertools.count()          # 模拟复制延迟：第 3 次读才读到新状态

def order_status():
    return 'PAID' if next(reads) >= 2 else 'PENDING'

checks = assert_all(
    eventually(lambda: that(order_status(), 'order.status') == 'PAID', within=2, every=0.05),
)
print(checks[0].expr)   # 第 3 次读到成立，用时 0.1 s（上限 2 s）；之前读到：order.status = 'PENDING' (expected 'PAID')
```

真实用例里，`lambda` 里放的是请求加判定，每次读都会重新发请求：

```python
from ipandora.core.assertion import assert_all, eventually, field, status_ok

assert_all(
    status_ok(order_api.pay(7)),
    eventually(lambda: field(replica_api.get_order(7), 'data.status') == 'PAID', within=10),
)
```

- **证据**：成立时写明第几次读到、用了多久；不成立时写明读了几次、依次读到了什么，例如 `CREATED → PENDING`。这能区分"卡住了"和"只是慢"。
- **一次读出错不算结束**：读的时候抛异常（节点还没起来、连接被拒），记为这次没成立，继续读；到截止时间仍然出错，判定失败并给出最后的异常。
- **探针必须返回 Check**：返回 `True` 或一个没有比较的 `field()` 是用例写错了，会立刻报 `TypeError`，不会白等到截止时间。
- **`within` 进入判定清单**：把等待时间从 10 秒放宽到 60 秒，是一次"改变"，`--fail-on-weakened` 会拦下。等得越久，越容易把延迟上的回归藏起来。
- **报告里只记一条判定**，不是每次读一条。每次读发出的请求会出现在这条用例的 HTTP 证据里。

## 判定清单与基线：这次通过可不可信

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

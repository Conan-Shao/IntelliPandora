# 故障注入

依赖变慢、断开、连接被重置的时候，被测系统还守得住不变量吗？在一条用例里注入故障，用完一定撤销，注入了什么写进证据，失败归因能分清"用例自己注入的故障"和"环境真的出了问题"。设计依据见 [决策记录 18](../design/decisions/18-一致性检查与故障注入.md)。

故障经 [Toxiproxy](https://github.com/Shopify/toxiproxy) 注入：被测服务通过 Toxiproxy 的代理端口访问它的依赖，框架通过 Toxiproxy 的 HTTP 接口在代理上加、删故障。Python 侧不需要装任何东西，Toxiproxy 本身是环境里单独运行的服务（容器或二进制）。

## 打开

只有本地和 CI 环境可以注入。在这个环境的 `conf/<env>.yaml`（或项目的 `conf/config.yaml`）里：

```yaml
faults:
  allowed: true
  toxiproxy: http://127.0.0.1:8474     # 默认值；也可以用环境变量 TOXIPROXY_URL
```

没有这一项时注入直接报错；环境名是 `prod` 或 `production` 时，写了也不允许。

## 用

```python
from ipandora.core import faults
from ipandora.core.assertion import assert_all, field, status_is


def test_payment_degrades_cleanly_when_the_db_resets_connections():
    with faults.injected(faults.reset_peer('orders-db')):
        resp = OrderApi().pay(order_id)
    assert_all(status_is(resp, 503),                        # 明确地失败，而不是 500
               field(ledger_entries(order_id), 'length') == 0)   # 没有扣款
```

| 故障 | 效果 |
|---|---|
| `latency(proxy, ms, jitter=0)` | 每段数据延迟 `ms` 毫秒（±`jitter`） |
| `bandwidth(proxy, kbps)` | 限速 |
| `timeout(proxy, ms=0)` | 数据都不通过；`ms` 毫秒后关闭连接（0 表示一直挂着） |
| `reset_peer(proxy, after_ms=0)` | 连接被重置（TCP RST），模拟突然断开 |
| `slow_close(proxy, ms)` | 关闭连接时延迟 |
| `down(proxy)` | 代理停用：新连接被拒，已有连接断开 |

都可以加 `stream='upstream'`（默认作用在下行）和 `toxicity=0.3`（只影响一部分连接）。`injected()` 可以同时注入多个故障。代理可以在环境准备时建好，也可以用 `faults.proxy('orders-db', listen='0.0.0.0:26379', upstream='db:6379')` 确保它存在。

## 保证

- **一定撤销**：离开 `with` 块时撤销，用例失败或抛异常也一样。撤销失败会报错，下一次运行开始时会清掉残留。
- **清理残留**：框架创建的故障都以 `ipandora-` 开头。每次运行开始和结束时，删除 Toxiproxy 上所有以它开头的故障，并重新启用被它停用的代理。几个运行同时共用一个 Toxiproxy 时会互相清掉，所以每个运行用自己的 Toxiproxy。
- **同一个代理同时只有一个用例在注入**：注入期间持有资源锁 `fault:<代理名>`，并行运行（`--workers`）的 worker 之间也一样。只是*用到*这个依赖、不能被故障影响的用例，声明同一个资源：`@pytest.mark.resource('fault:orders-db')`。
- **写进证据**：每个注入记录类型、代理、参数、起止时间，报告的用例详情里列出来。

## 归因

用例自己注入了故障，期间出现的传输失败（连接被重置、超时）归为**注入的故障**，不归为"环境"：依赖是用例自己弄坏的，要看的是被测系统（或用例的客户端）该不该扛住它——重试、超时、降级。判定不成立（比如重复扣款）仍然是产品缺陷。没有注入故障的用例遇到连接失败，照旧归为环境问题。

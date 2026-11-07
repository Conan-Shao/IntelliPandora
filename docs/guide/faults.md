# 故障注入

依赖变慢、断开、连接被重置的时候，被测系统还守得住不变量吗？在一条用例里注入故障，用完一定撤销，注入了什么写进证据，失败归因能分清"用例自己注入的故障"和"环境真的出了问题"。设计依据见 [决策记录 18](../design/decisions/18-一致性检查与故障注入.md)。

内置的后端是 [Toxiproxy](https://github.com/Shopify/toxiproxy)（别的平台怎么接，见[接入别的故障注入平台](#接入别的故障注入平台)）：被测服务通过 Toxiproxy 的代理端口访问它的依赖，框架通过 Toxiproxy 的 HTTP 接口在代理上加、删故障。Python 侧不需要装任何东西，Toxiproxy 本身是环境里单独运行的服务（容器或二进制）。

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
- **清理残留**：框架创建的故障都以 `ipandora-` 开头。每次运行（最外层的那次，不包括用例里再调用的 `run()`）开始和结束时，删除 Toxiproxy 上所有以它开头的故障，并重新启用被它停用的代理。几个运行同时共用一个 Toxiproxy 时会互相清掉，所以每个运行用自己的 Toxiproxy。
- **同一个代理同时只有一个用例在注入**：同一条用例里嵌套多层 `injected()` 没有问题（锁在进程内可重入）；注入期间持有资源锁 `fault:<代理名>`，并行运行（`--workers`）的 worker 之间也一样。只是*用到*这个依赖、不能被故障影响的用例，声明同一个资源：`@pytest.mark.resource('fault:orders-db')`。
- **写进证据**：每个注入记录类型、代理、参数、起止时间，报告的用例详情里列出来。

## 归因

故障生效期间出现的传输失败（连接被重置、超时）归为**注入的故障**，不归为"环境"。判断依据是时间：故障生效期间抛出的传输错误，消息里会写明当时生效的故障，`concurrently()` 的线程里发出的请求也一样：依赖是用例自己弄坏的，要看的是被测系统（或用例的客户端）该不该扛住它——重试、超时、降级。判定不成立（比如重复扣款）仍然是产品缺陷。故障撤销之后、或者没有注入故障的用例遇到连接失败，照旧归为环境问题。

## 在 K8s 上：Chaos Mesh

集群里装了 [Chaos Mesh](https://chaos-mesh.org) 时，可以对 Pod 注入故障，用法和上面一样：

```python
from ipandora.core import chaosmesh, faults

orders = chaosmesh.pods('orders', namespace='shop', labels={'app': 'orders'})
db = chaosmesh.pods('db', namespace='shop', labels={'app': 'db'})

slow = chaosmesh.delay(orders, ms=800, jitter=200)       # Pod 发出的每个包延迟
cut = chaosmesh.partition(orders, peer=db)               # 两组 Pod 之间双向不通
broken = chaosmesh.pod_failure(orders)                   # 容器换成什么都不做的 pause，撤销后恢复
# 用例里：with faults.injected(slow): ...
```

| 故障 | 效果 |
|---|---|
| `delay(pods, ms, jitter=0)` | Pod 发出的每个包延迟 `ms` 毫秒（±`jitter`） |
| `loss(pods, percent)` | 按比例丢包 |
| `partition(pods, peer)` | 两组 Pod 之间双向断网 |
| `pod_failure(pods)` | Pod 还在，但不再工作，直到撤销 |
| `pod_kill(pods)` | 杀掉一次（由它的控制器重建）；撤销只是删掉记录 |

`pods(..., mode='one')` 只选一个，`'fixed:2'`、`'fixed-percent:50'` 等同 Chaos Mesh 的写法。环境配置：

```yaml
faults:
  allowed: true
  backends: [chaos-mesh]
  chaos_mesh:
    context: kind-staging      # 必填：要注入的集群
    namespace: default         # Chaos 对象建在哪个命名空间
    timeout: 60                # 等故障生效、等撤销完成的秒数
```

- **集群要写明**：每次调用 kubectl 都带上配置里的 `context`；没写就拒绝注入。kubectl 当前指着哪个集群不起作用，免得指着生产集群的 kubectl 被误用。
- **生效了才往下走**：建好 Chaos 对象后等 Chaos Mesh 报告"所有选中的 Pod 都已注入"；超时、或者选择器一个 Pod 都没选中，就报错并删掉对象。撤销是删除对象并等 Chaos Mesh 恢复完 Pod。
- 框架只调用 `kubectl`，Python 侧不装任何东西；Chaos Mesh 由集群的维护者安装。本仓库的 CI 在一个 kind 集群上真实验收这几种故障（`test/testfaults/kind/`）。

## 接入别的故障注入平台

Toxiproxy 是内置的后端。公司自己的故障平台、云厂商的故障服务、K8s 上的 Chaos Mesh，都可以作为另一个后端接进来：写一个 `faults.Backend` 的子类，注册一个名字，故障写明用哪个后端。

```python
from ipandora.core import faults


class ChaosPlatform(faults.Backend):
    """接一个故障平台：每个方法调一次平台的接口（这里用一个字典代替）。"""

    name = 'chaos-platform'

    def __init__(self):
        self.experiments = {}

    def where(self):
        return 'https://chaos.example.test'          # 写进证据：故障是经哪里注入的

    def apply(self, fault):                          # 返回时故障已经生效；做不到就抛 faults.BackendError
        self.experiments[fault.name] = (fault.target, fault.kind, dict(fault.attributes))

    def undo(self, fault):                           # 只撤销这一个；已经不在了也不能报错
        self.experiments.pop(fault.name, None)

    def clean(self):                                 # 删掉所有以 faults.PREFIX 开头的：被杀掉的运行留下的
        ours = [n for n in self.experiments if n.startswith(faults.PREFIX)]
        for n in ours:
            del self.experiments[n]
        return ours


faults.register('chaos-platform', ChaosPlatform)
kill_orders = faults.Fault('orders', 'pod-kill', backend='chaos-platform')
```

用的时候和内置的一样：`with faults.injected(kill_orders): ...`。环境配置里写上它，运行开始和结束时才会清理它的残留：

```yaml
faults:
  allowed: true
  backends: [toxiproxy, chaos-platform]
```

后端只负责加和撤。其余的不论哪个后端都由框架做，接入方不用、也不能改：没打开就不许注入（`prod` 永远不许）；同一个目标同时只有一个注入者（资源锁 `fault:<目标>`）；每个故障写进证据，带起止时间和 `backend`、`via`；生效期间的传输错误带标记，归因为"注入的故障"；离开 `with` 块一定撤销。后端要保证的只有三条：`apply` 返回时故障已经生效，失败就抛 `BackendError`、什么都不留；`undo` 只撤这一个，重复调用不报错；它创建的东西都用 `fault.name` 命名（以 `ipandora-` 开头），`clean()` 才找得到。

## 和一致性检查一起用

故障下记录操作历史、交给检查器判定（Jepsen 的做法），见 [一致性检查 · 在故障下检查](consistency.md#在故障下检查)。历史里的每个操作都记下当时生效的故障。

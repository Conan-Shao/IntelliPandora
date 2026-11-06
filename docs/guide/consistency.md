# 一致性检查

并发读写之后，结果能不能用"操作一个一个按某种顺序执行"来解释？一组事务的结果，符不符合声称的隔离级别？这类问题靠逐条写断言写不全：要记录完整的操作历史，交给现成的检查器判定。设计依据见 [决策记录 18](../design/decisions/18-一致性检查与故障注入.md)。

检查器是 [elle-cli](https://github.com/ligurio/elle-cli)：Knossos 判线性一致，Elle 判事务隔离异常，还有 Jepsen 的计数器、集合、转账检查器。框架负责记录历史、写成检查器要的格式、调用、把结论变成判定，不自己实现算法。

## 准备

elle-cli 是一个 Java 程序，不随 intellipandora 安装：

1. 装 Java 21 或更新的版本。
2. 下载 [elle-cli-bin-0.1.11.zip](https://github.com/ligurio/elle-cli/releases/download/0.1.11/elle-cli-bin-0.1.11.zip)，解压出 `target/elle-cli-0.1.11-standalone.jar`。
3. 设置 `ELLE_CLI_JAR` 指向它（或在配置里写 `consistency.elle_cli`）。

框架每次运行前核对 jar 的 SHA-256，和登记表（`docs/security/components.md`）里准入的那个版本不一致就拒绝运行。没装 Java 或检查器时，用到它的用例跳过并说明原因，不会被当成通过。

## 用

```python
from ipandora.core import consistency
from ipandora.core.assertion import assert_all
from ipandora.core.concurrency import concurrently


def test_concurrent_increments_are_not_lost():
    history = consistency.History()

    def add():
        return history.call('add', 1, lambda: CounterApi().incr(), ok=lambda r: r.status_code == 200)

    concurrently([add] * 10)
    history.call('read', None, lambda: CounterApi().get(),
                 ok=lambda r: r.status_code == 200, result=lambda r: r.json()['n'])
    assert_all(history.check('counter'))
```

`history.call(f, value, operation, ok=, fail=, result=)` 执行一个操作并记两条：发出（invoke）和完成。完成分三种，由用例说明：

| 结果 | 含义 | 怎么得到 |
|---|---|---|
| `ok` | 生效了 | `ok(r)` 为真（不给 `ok` 时：没抛异常就算） |
| `fail` | 肯定没生效（比如 409） | `fail(r)` 为真 |
| `info` | 不知道：超时、连接断了，可能生效也可能没有 | 抛了异常，或者既不是 ok 也不是 fail |

`result(r)` 是操作完成时的值，读操作读到了什么。检查器会把 `info` 的两种可能都考虑进去；之后这个线程以一个新的"进程"继续，这是检查器的要求。`concurrently()` 的每个线程就是一个进程。

## 模型

| 模型 | 判什么 | 操作 |
|---|---|---|
| `cas-register` | 单个寄存器的线性一致 | `write v`、`read`、`cas [旧 新]` |
| `mutex` | 锁的互斥 | `acquire`、`release` |
| `counter` | 计数器：读到的值在已确认的增加之间 | `add n`、`read` |
| `set` / `set-full` | 集合：加进去的都读得到 | `add x`、`read` |
| `rw-register` / `list-append` | 事务隔离：`history.check('list-append', consistency_models=['serializable'])` | 一个事务的值是若干微操作：`consistency.append(k, v)`、`consistency.read(k)`、`consistency.write(k, v)` |
| `bank`、`long-fork` | 转账总额守恒、并行快照隔离的长分叉 | 见 elle-cli 的说明 |

## 结论

- **一致**：判定成立。
- **不一致**：判定不成立，证据是检查器的反例：计数器写"读到 1，按已确认的操作应在 8 到 8 之间"；寄存器写"没有任何顺序能解释这个操作"；事务写检查到的异常（G1c、G-single……）和不满足的隔离级别。完整结论在 `history.result`。
- **无法判定**（检查器超时或内存不够）：记为未覆盖（gap），不算通过；只有这一条判定的用例显示为"未判定"。

线性一致检查是 NP 完全问题，历史越长越慢。一条用例里几十到几百个操作是合适的规模。

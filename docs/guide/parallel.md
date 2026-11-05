# 并行与并发

用例之间并行跑得快；一条用例里同时发起 N 个操作，测并发下对不对。

## 并行执行

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

## 并发场景测试

上一节是让**用例之间**并行、跑得快；这一节是在**一条用例里**同时发起 N 个操作，判断产品在并发下对不对：同一笔订单只扣一次款、库存不超卖、幂等键真的生效。不需要安装额外的组件。

```python
from ipandora.core.assertion import assert_all
from ipandora.core.assertion import field, that
from ipandora.core.assertion.http import status_code
from ipandora.core.concurrency import concurrently


def test_pay_exactly_once():
    shop = ShopApi()
    shop.login()                                     # 登录态会带到每个并发请求

    results = concurrently(lambda: shop.pay('order-1', key='idem-1'), n=20)
    codes = [status_code(r.value) for r in results]

    assert_all(
        results.overlap_check(),                     # 先确认并发真的发生了
        that(codes, '各请求状态').each().is_in([200, 409]),
        that(codes.count(200), '成功扣款次数') == 1,     # 恰好一次
        field(shop.order('order-1'), 'data.paid_amount') == 100,   # 终态
    )
```

- **同时起跑**：所有线程准备好之后才一起放行。
- **登录态**：每个并发线程拿到调用方 session 的副本，包括请求头、cookie、认证、TLS 和代理设置。如果不这样做，新线程用的是一个空 session，所有并发请求都会以未登录身份发出去，而一堆 401 看起来很像"只有一个成功"。并发期间响应里新设置的 cookie 只留在各自的线程里。
- **证据**：每个并发请求都记在这条用例下，报告里能看到全部 N 个请求和各自的响应。
- **结果**：`results` 按给出的顺序排列，每一项有 `value`（返回值）、`error`（抛出的异常）、`start`（相对第一个起跑的偏移）、`duration`。异常**不会抛出**，而是交给你来判定，因为并发下"除了一个之外全部报错"往往正是期望的结果。
- **几个操作互相竞争**：传一个列表，每个执行一次：`concurrently([lambda: shop.pay(o), lambda: shop.refund(o)])`。
- **并发真的发生了吗**：线程被唤醒有先后。如果某个操作在最后一个起跑之前就已经结束，这次实际上有一部分是串行的，要触发的竞态可能根本没有机会出现。`results.overlapped` 会告诉你是否所有操作同时在进行，`results.overlap_check()` 把它变成一条判定。建议放在 `assert_all` 的第一条：串行跑的并发测试永远不会重复扣款，没有它，这样的测试会通过。
- **起跑前就失败**：某个线程在准备阶段出错，或者没能在 `timeout`（默认 60 秒）内就绪时，整组都不执行，抛出 `NotConcurrent`。不会退化成"少一个"或"一个接一个"地照样判定。
- **卡住的操作**：超过 `timeout` 还没结束的，结果里记为 `TimeoutError`，不会一直等下去。

**边界**：这是并发下的正确性测试，不是压测，不提供 RPS 目标和延迟分位数，那是 Locust、k6 的事。

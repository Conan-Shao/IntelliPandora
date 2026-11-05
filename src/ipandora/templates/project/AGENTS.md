# AGENTS.md

写给在这个仓库里编写、修改测试用例的 agent（Claude Code、Codex、Cursor 等）。人也可以读。

这个项目用 [IntelliPandora](https://github.com/Conan-Shao/IntelliPandora) 运行和判定用例。它在 pytest 之上回答一个问题：**这次通过可不可信**。下面每条规则都对应一个门禁或一个报告信号。违反规则，CI 或报告会把它指出来；规则不是一句口号。

## 怎么跑

```shell
ipandora run tests                     # 跑用例，写报告，和判定基线比对
ipandora run tests -e staging          # 叠加 conf/staging.yaml
ipandora run tests --workers 4         # 并行（需要 intellipandora[parallel]）
```

用 MCP 时：`run_tests(selector, env)` 返回摘要，`explain_failure(run_id)` 返回完整的失败现场。

## 规则

| 规则 | 谁来发现 |
|---|---|
| **每条用例都要有判定**：`assert_all(field(r, 'data.fee') <= 100, ...)`、`that(value, '标签') == ...`、普通 `assert`、`pytest.raises`、Playwright 的 `expect`，都算判定 | 没有任何判定却通过的用例，报告里标为 **UNVERIFIED**，不计入通过率 |
| **不许为了让用例变绿而改弱判定**：删掉断言、放宽范围、改期望值、改成 skip、加 xfail | 每次运行都和 `conf/judgements.json` 比对，判定变弱会被列出来；CI 用 `--fail-on-weakened` 拦下 |
| **期望值确实需要改时，写明原因，交给人决定**。不要自己运行 `--update-baseline` | 基线文件的改动出现在 PR 里；`.github/CODEOWNERS` 要求负责人审 `conf/judgements.json` |
| **不许重新录制基准图来让图像判定通过** | 基准图的内容哈希写在判定里，换图会被当作"判定改变"拦下；CODEOWNERS 同样保护 `__goldens__/` |
| **文字用文字断言判**：`expect(locator).to_have_text(...)` 或 `that(...)`，不要用截图判 | 截图几乎看不见文字变化：100.50 改成 100.60 只差 7 个像素，图像判定会判为通过 |
| **UI 定位优先用稳定的定位方式**：`get_by_role`、`get_by_label`、`get_by_test_id`，少用依赖页面结构的 CSS / XPath | 选择器找不到元素时，报告会区分"选择器过时"（用例的问题）和"待确认：可能是产品缺陷"（元素真的没了） |
| **前置条件不满足时用 `require()`**，不要让用例在没有数据时假装通过 | 归因为 data（数据问题），不算通过 |
| **不稳定的用例标 `@pytest.mark.flaky(reason='...')`**，写清原因；不要直接删除或 skip | 用 `--exclude-flaky` 排除时，报告仍会点名这些用例 |
| **多条用例共用一个账号或一份固定数据时，声明出来**：`@pytest.mark.resource('account:vip')` | 并行运行时，同名资源的用例不会同时执行；等锁超时归因为环境问题 |
| **凭据不写进仓库**：放在环境变量里，或者不提交的 `conf/<env>.yaml` 里 | 报告会对凭据脱敏，但脱敏不能替代不提交 |

## 写判定

```python
from ipandora.core.assertion import assert_all, field, status_ok, that

def test_order_is_paid(orders):
    r = orders.get(7)
    assert_all(                                  # 一次报出所有失败，而不是停在第一个
        status_ok(r),
        field(r, 'data.status') == 'PAID',
        field(r, 'data.fee') <= 100,
        field(r, 'data.items').len() > 0,
    )
```

比较是严格的：JSON 里的字符串 `"12"` 不等于数字 `12`。接口把数字改成字符串，本身就是要发现的问题。确实是字符串形式的数字（比如金额），显式写 `field(r, 'data.amount').decimal() == Decimal('100.50')`。

## 判定失败时

先看失败原因被归到了哪一类：
- defect：产品问题；
- contract：接口结构变了；
- environment：环境问题；
- data：数据问题；
- harness：用例自身的问题。

修复的方向取决于类别：只有 harness 才该改用例，defect 和 contract 该报给负责被测系统的人。

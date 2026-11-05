# 报告、归因与以库方式调用

跑完之后看什么，以及在 Python 里直接调用运行器。

## 以库方式执行测试

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

## 失败归因

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

## 生成报告

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

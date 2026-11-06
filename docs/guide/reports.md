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

| 类别 | 报告里显示为 | 含义 | 该找谁 |
|---|---|---|---|
| `defect` | 产品缺陷 | 断言失败，系统返回了错的值 | **被测系统** |
| `contract` | 接口契约 | 只有 schema 检查失败 | **被测系统**，接口变了 |
| `environment` | 环境 | 传输失败，没拿到响应 | 环境/网络，**什么都没测到** |
| `data` | 测试数据 | 前置不满足（`require` skip） | fixture / 账号状态 |
| `harness` | 测试代码 | setup 炸了，或 Web 选择器失效 | 测试自身 |
| `unknown` | 待确认 | 签名不认识 | 看完整 traceback |

类别是英文代码，给程序比较用；每条归因的依据（`reason`）和下一步（`next_step`）是中文。

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

- **字段名**：`password` `token` `api_key` `mnemonic` `signedTx` `Authorization` `Cookie` …。JSON 里的字段、请求头，以及 `key=value` 形式的文本都按名字认：表单请求体 `username=alice&password=…`、URL 查询串 `?access_token=…`、消息里的 `password=…`；还有冒号形式：消息里引用的字典 `{'password': '…'}`、JSON 片段 `"token": "…"`、YAML 行 `password: …`，以及文本里整行的 `Cookie: …`、`Authorization: …`
- **值的形状**：以太坊私钥 `0x[64位hex]`、JWT、`sk-` 前缀、AWS AKIA、PEM 私钥块、助记词

宁可多掩码 —— 误掩码只是让人多跑一次，泄漏的凭据收不回来。嵌套超过 20 层的部分整块掩码。长值先掩码再截断，截断不会把 PEM、JWT、助记词切成认不出的片段。

评测报告（`ipandora eval run`）和导出给人工标注的样本同样脱敏：agent 的输出、轨迹、评分器和评委的说明都会掩码，成本里的数字保留。交给模型做根因分析的提示里，用例 id 的参数部分整个隐藏（`test_login[参数已隐藏]`）：参数可能就是密码，而密码没有可识别的形状。

同样的掩码也用在交给 agent 的内容上：MCP 的 `run_tests` 摘要和 `explain_failure` 的失败消息、traceback，以及开启 LLM 归因时发给模型的提示。这些内容通常会被发往模型服务商，所以和报告一样处理，并且先掩码再截断。框架自己的运行存档（`~/.ipandora/runs`）只在本机，保留原文。

**报告会显示"什么都没证明"的部分**：

| 状态 | 含义 |
|---|---|
| `SKIPPED` | 前置不满足 |
| `BLOCKED` | 写了但上游失败没跑到 |
| `GAP` | 该有的断言没写（需自行声明，跑一次是推不出来的） |

`pass_rate` **只算有结论的用例**。跳过一半用例的套件不是 100% 健康。

## 报告首屏：这次能不能信

报告第一屏回答一个问题：这次通过能不能作为放行依据。从上到下是：

1. **结论**：一句话，由固定模板根据计数拼出来，不经过 LLM。

   | 结论 | 什么时候 | 退出码 |
   |---|---|---|
   | 可以放行 | 全部通过，没有需要复核的地方 | 0 |
   | 通过，但需要复核 | 没有失败，但有判定变弱（没开 `--fail-on-weakened`）、有未判定的用例，或者没有一条用例给出结论 | 0 |
   | 不能放行 | 有失败；或开了 `--fail-on-weakened` 且判定变弱 | 1 |
   | 没有跑起来 | 收集失败，或没有用例运行 | 1 |

2. **指标卡**：用例结果（通过率写明分子分母，跳过与未判定不进分母）、判定强度（对比基线）、未判定、已声明的缺口、维度覆盖。
3. **这次新红的**：见下一节。
4. **需要看的用例**：失败按归因分组，被测系统的问题排在前面；通过但不可信的用例（未判定、标记为不稳定、判定比基线弱）单独成组。
5. 判定变化、覆盖矩阵、用例明细（判定、HTTP 请求、截图、trace、图像对比）、缺口汇总。

页面跟随系统的浅色或深色主题，手机上也能看。报告是一个 HTML 文件，可以离线打开、作为 CI 制品上传。

## 和什么比：基线，以及可选的一次运行

**框架不是平台，不存运行历史，也不画趋势。** "这次新红了什么"按下面两个来源回答：

**对比基线**：每次都有，只要有基线文件。基线 `conf/judgements.json` 随代码提交，所以本机和 CI 得到的答案一样。基线只记录写入时通过或跳过的用例，失败的不记，所以：

| 这次 | 基线里 | 报告里 |
|---|---|---|
| 失败 | 通过 | 基线通过，这次失败（新红） |
| 失败 | 没有，或不是通过 | 基线里无通过记录 |
| 没失败 | 没有 | 新用例 |

**对比一次运行**：可选，有可比的运行才显示。

1. `ipandora run --compare-with REPORT`：传入一份更早的 `report.json`（或它所在的运行目录）。在 CI 里，通常是从主分支上次运行的制品里下载的那份。
2. 没传时，找本机报告存档里**同一选择器、同一环境**的上一次运行。报告会标明"来源：本机缓存"，因为这份缓存只在这台机器上有。
3. 都没有，就不显示这一栏。

结果分"新失败 / 仍在失败 / 恢复通过"。这次没跑的用例不算恢复。

在 Python 里：

```python
from ipandora.core.runner import run
from ipandora.core.report import build, compare, write

report = build(run('test/testapi', quiet=True))
compare.attach(report, compare_with='main-report.json')   # 不传则查本机存档
write(report, 'out/')

report.verdict            # {'status': 'fail', 'label': '不能放行', 'sentence': ..., 'releasable': False, ...}
report.pass_rate_basis    # {'passed': 5, 'denominator': 8, 'not_counted': {'skipped': 1, 'unverified': 1}}
report.against_baseline   # {'newly_failing': [...], 'no_passing_record': [...], 'new_cases': [...]}
report.against_run        # {'source': 'argument', 'run_id': ..., 'newly_failing': [...], ...}
```

这些字段也都在 `report.json` 里，是在原有字段之外新增的；原有字段的含义不变。MCP 的 `run_tests` 返回里多了 `newly_failing`（基线里通过、这次失败的用例），`build_report` 多了 `compare_with` 参数和返回的 `verdict`。

## 覆盖矩阵怎么声明

在测试模块里声明坐标轴，用例用 `@pytest.mark.dims(...)` 落位。没有用例的格子就是没人测过的组合，这是矩阵存在的理由。

简写：两个维度和各自的取值，先写行再写列：

```python
import pytest

COVERAGE = [{'role': ['admin', 'guest'], 'channel': ['web', 'app']}]

@pytest.mark.dims(role='admin', channel='web')
def test_admin_on_web():
    ...
```

完整写法可以给标题、说明和显示名：

```python
COVERAGE = [{
    'id': 'role-channel', 'title': '角色 × 渠道', 'note': 'app 渠道下个迭代补',
    'y': {'key': 'role', 'label': '角色',
          'values': [{'key': 'admin', 'label': '管理员'}, {'key': 'guest', 'label': '访客'}]},
    'x': {'key': 'channel', 'label': '渠道', 'values': ['web', 'app']},
}]
```

写法无法识别时，报告和命令行会说明原因，不会画成一个"0 / 0"的空矩阵。

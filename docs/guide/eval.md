# 评测 agent

评测一个 agent：同一组任务每题跑 k 次，判分，算成功率和置信区间，和基线比较，判断"变好、变差，还是无法区分"。设计依据见 [决策记录 13](../design/decisions/13-agent验证.md)。

两条执行路径共用一套底座：业务 agent 直接用这里的 Python 接口跑；编码类 agent 在 [Inspect](https://inspect.aisi.org.uk/) 的沙箱里跑，日志读进同样的结构（见 [Inspect 路径](#inspect-路径)）。两条路径的统计、基线、报告和退出码完全一样。

## 三样东西

- **任务**是数据：YAML 或 JSONL，写输入、期望、标签、参考解。
- **agent** 是一个 Python 函数：收到任务，返回输出，可以附带轨迹和成本。
- **评分器**是一个 Python 函数：收到任务和 agent 的结果，返回判定（`Check`），和用例里的判定是同一种东西。

<!-- run -->
```python
from ipandora.core.assertion import that
from ipandora.core.eval import AgentResult, Graded, dataset, evaluate

data = dataset.from_records([
    {'id': 'refund', 'input': '订单 A1001 金额 120.50 元', 'expected': 'A1001',
     'tags': {'kind': '常规'}, 'reference': 'A1001'},
    {'id': 'two-orders', 'input': '订单 A1003 已退，另一笔 A1004 未退', 'expected': 'A1004',
     'tags': {'kind': '多个订单'}, 'reference': 'A1004'},
], name='orders')


def agent(task):
    import re
    found = re.search(r'A\d{4}', task.input)          # 只认第一个订单号
    return AgentResult(output=found.group(0) if found else None, cost={'usd': 0.001})


def grade(task, result):
    return [that(result.output, 'order') == task.expected]


run = evaluate(data, agent, grade, trials=3)
summary = run.summary()
print(summary['success_rate'], summary['interval'], summary['pass_hat_k'])   # 0.5 [0.18…, 0.81…] 0.5
```

## 任务格式

```yaml
name: coding-tasks
version: 3
tasks:
  - id: multi/rename-config-key
    input: 把配置项 timeout_s 重命名为 timeout，旧名继续可读
    expected: {hidden_tests: tests/hidden/test_rename.py}
    tags: {kind: 多文件修改, difficulty: medium}
    polarity: do          # do：应该做；dont：应该拒绝。报告按极性分开看
    split: test           # dev：调提示用；test：下结论用
    budget: {seconds: 600, usd: 1.0}   # 超出就算失败；usd 等成本由 agent 在 AgentResult.cost 里报告
    reference: refs/rename-config-key.patch     # 参考解：相对数据集文件的路径，或直接写值
```

- 拼错的字段会报错，不会被悄悄忽略（`refrence` 不会让参考解丢掉）。
- 参考解写成文件名（`refs/x.patch`、`answer.json`）时，文件必须存在于数据集所在目录内，否则读取数据集就报错。`3.14` 这类内联答案照常当作值。
- **预算**：`budget` 的每一项都变成一条必需判定。`seconds` 是 agent 实际用时，其他键（`usd`、`tokens_in`……）读 agent 报告的成本；超出就算失败。agent 没报告的项不判。
- **极性**：数据集里有 `dont` 的任务时，报告和基线比较会按 `polarity` 分开列出，和标签一样。一个什么都拒绝的 agent 在 `dont` 题上满分，合在一起的成功率会掩盖这一点。
- **内容哈希**：任务和参考解文件的内容一起算出哈希，写进每次运行的版本清单。哈希不同的两次运行，分数不可比，报告会直接说明。

## 判分

评分器返回 `Check`，或者用 `Graded` 加上权重和是否必需：

```python
from ipandora.core.assertion import Check, that
from ipandora.core.eval import Graded


def grade(task, result):
    return [
        that(result.output['tests_passed'], 'hidden tests') == True,             # 必需，权重 1
        Graded(that(result.output['files_changed'], 'files').len() <= 3, required=False),
        Check('计划是否合理', ok=True, src='llm_judge'),                          # 模型评委：只展示
    ]
```

- **成功**：所有必需判定都成立。**得分**：按权重算成立的比例。两个数字都报。
- **模型评委**（`src='llm_judge'`）的判定只展示，不参与成功和得分，直到它和人工标注的一致率达标。评委不确定时用 `Graded(..., uncertain=True)`，不算成立也不算不成立。
- **agent 抛异常**算基础设施问题：沙箱没起来、超时。不计入成功率，单独统计。agent 答错要体现在输出里，由评分器判。
- **评分器抛异常**算评分器的问题。

## 参考解自检

每道题的参考解用全部评分器判一遍，必须全部通过。判不过，说明任务或评分器有问题；这道题上 agent 的失败归为"任务有问题"，不算 agent 的问题。

```shell
ipandora eval selfcheck evals/coding.py      # 参考解判不过、评分器出错时退出码为 1，可以放进 CI；没有参考解的题只列出来
```

## 运行与比较

一个 spec 文件说明跑什么：

```python
# evals/coding.py
DATASET = 'coding.yaml'                       # 相对这个文件
MANIFEST = {'harness': 'my-agent@abc123', 'model': 'claude-sonnet-5',
            'resources': {'cpu': 2, 'memory': '4G'}}

def agent(task): ...
def grade(task, result): ...
```

```shell
ipandora eval run evals/coding.py -k 5 --split test --workers 8
ipandora eval run evals/coding.py -k 5 --split test --update-baseline     # 写入 conf/eval_baseline.json
```

退出码就是结论：和基线比"变差"或"不可比"时为 1，其他为 0；数据集、spec 或显式给出的 `--baseline` 读不了时为 2。

报告给出：

- **成功率**和 95% Wilson 区间；**pass@k**（k 次里至少一次成功）和 **pass^k**（k 次全部成功，用户真正体验到的稳定性）；平均分；成本。
- **和基线比较**：按任务配对。每题一次试验时用 McNemar 精确检验；多次试验或部分分时用分层 bootstrap，任务和每题的试验都重新抽样，一道题自身的波动也算进去。区间不跨过 0，**并且**差值超过 `--noise` 给的基础设施噪声，才判为变好或变差，否则是"无法区分"。
- 按标签分别比较；变差的任务；没有成功的试验按归因分组，附判定、模型评委的意见和轨迹。
- **版本清单**：数据集哈希、划分、外壳、模型、配置、资源、种子。和基线的哈希、划分或资源不同时，报告直接说"不可比"。

## Inspect 路径

编码类 agent 要在容器里跑，要在沙箱里运行 Claude Code、Codex CLI 这类命令行 agent：这些交给 Inspect 和 [inspect_swe](https://meridianlabs-ai.github.io/inspect_swe)，框架不重做。框架做两件事：把 Inspect 的日志读成评测结果，把评分器包成 Inspect 的 scorer。需要 `pip install "intellipandora[inspect]"`（Python 3.11 及以上）。

**读日志**：

```shell
inspect eval coding.py --model anthropic/claude-sonnet-5 --epochs 5 --log-dir logs/run-1
ipandora eval inspect logs/run-1 --update-baseline       # 第一次：写基线
ipandora eval inspect logs/run-2                         # 之后：和基线比较，变差时退出码为 1
```

```python
from ipandora.core.eval import inspect_log

run = inspect_log.read('logs/run-1')        # 一个 .eval / .json 文件、一个目录，或文件列表
run.summary()['success_rate']
```

怎么换算：

- 每个样本的每个 epoch 是一次试验。几个任务的日志（一次 `eval_set`）读成一次运行，题号前面加任务名；同一个任务有两份日志、或者模型不同，直接报错，不混在一起算。
- 每个评分器的分数是一条判定，达到阈值算通过：默认 1，也就是 `CORRECT`、`True`、`1.0`；`--threshold 0.5` 让 `PARTIAL` 也算过，`--threshold match=0.5` 只对一个评分器。字典或列表形式的分数，每一项一条判定。
- `model_graded_qa`、`model_graded_fact` 是模型评委，`--judge 名字` 标出自己写的模型评委。它们的结论列在报告里，但和 pytest 路径一样，校准之前不计入成功率。
- 样本出错（沙箱没起来、agent 崩溃），或者撞上时间上限，算基础设施问题，不算 agent 失败，单独计数。撞上 token、消息数、费用、轮数上限，算一条没通过的预算判定。
- 样本的 `metadata` 里写 `tags`、`polarity`、`split`，报告就能按标签、按极性分开出分。
- 版本清单记录 Inspect 的版本、solver、模型、生成参数、沙箱、各项上限，以及样本内容的哈希：换了题、换了沙箱，和基线比较时会直接说"不可比"。

**评分器包成 scorer**：pytest 路径的评分器原样用在 Inspect 里，判定按名字进报告，而不是一个说不清的分数。

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate

from ipandora.core.assertion import that
from ipandora.core.eval.inspect_scorer import scorer


def grade(task, result):                        # 和 pytest 路径同一个评分器
    return [that(result.output, 'answer').contains(task.expected)]


@task
def coding():
    return Task(dataset=[Sample(input='...', target='...', metadata={'tags': {'kind': 'rename'}})],
                solver=generate(), scorer=scorer(grade))
```

- 必需的确定性判定全部成立是 `CORRECT`，有一条不成立是 `INCORRECT`；一条判定也没有是 `NOANSWER`，不会被当成通过。
- 评分器可以是 `async def`：要在沙箱里跑隐藏测试的，`await sandbox().exec([...])`（`from inspect_ai.util import sandbox`）。
- 评分器抛异常，算评分器的问题，不算 agent 的。
- 用 inspect_swe 在沙箱里跑 Claude Code、Codex CLI 时，把它的 agent 作为 `solver`，评分器照样用这一个。

## 人工标注

```shell
ipandora eval samples reports/eval-…/report.json -o samples.jsonl -n 50     # 导出评委判定，留给人填
ipandora eval agreement samples.jsonl                                        # 一致率和 Cohen kappa
```

把 `human` 一栏填上 `true` / `false` / `null`。看 kappa，不只看一致率：一个永远说"是"的评委，在九成是"是"的样本上一致率有 90%，kappa 是 0。加 `--all-checks` 导出确定性判定，让两个人各自标，可以检查一道题有没有歧义。

完整的例子在 `examples/eval/`：`ipandora eval run examples/eval/spec.py -k 5`。

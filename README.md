# IntelliPandora

> AI 时代的通用测试框架内核：**agent 负责写，框架负责执行。**
>
> 目前支持 HTTP 接口测试；UI 自动化（Web / App）在规划中。框架不绑定任何业务——业务相关的用例、流程、环境配置放在使用方自己的仓库里。

AI 写得出用例，但用例不能只有 agent 才跑得起来——那样 CI 接不上，别人很难直接跑，agent 参与执行还会把不确定性带进结果。

IntelliPandora 是被拆出来的那一半：**一个确定性的、独立运行的执行器**。人、CI、agent 三个入口调用同一套 runner，跑出来的结果一致。

![架构](docs/dev/static/architecture.svg)

## 它解决什么

| | 之前 | 现在 |
|---|---|---|
| 状态码 | 500 静默通过——`status_code` 只用来给日志上色 | 断言层判定，不看就是 `gap` |
| 断言失败 | 第一个失败就停 | `Check` 是值不是异常，`assert_all` 一次报全部 |
| 失败原因 | 自己翻日志 | 归因到 defect / contract / environment / data / harness |
| 跑完的结果 | 控制台一段文字 | HTML + JSON + **JUnit XML**，可直接进 CI 门禁 |
| 超时 | 默认无，一个挂起的接口挂死整个套件 | 连接 10s / 读取 30s，每个请求都有界 |
| TLS | 强制 `verify=False` | 默认开启 |

## 安装

```shell
pip install intellipandora            # 内核，依赖只有 8 个
pip install intellipandora[ai]        # 可选：失败归因接 LLM
pip install intellipandora[mcp]       # 可选：agent 入口
```

## 用起来

```shell
ipandora run test/api                        # 跑完出 HTML + JSON + JUnit XML
ipandora run test/api --junit-xml out.xml    # 给 CI 的那份放到指定位置
ipandora run test/api --exclude-flaky        # 门禁模式：已知不稳定的用例不参与判定
ipandora run test/api -e staging             # 叠加 ./conf/staging.yaml，只作用于本次运行
ipandora mcp                                 # 以 MCP server 方式供 agent 调用
```

写一条用例：

```python
from ipandora.core import api
from ipandora.core.assertion import assert_all, json_equals, status_ok

class OrderService:
    @api.http.post(path="api/order/create")
    def create(self, amount):
        return dict(json={"amount": amount})

def test_create_order():
    """下单成功，金额与请求一致"""
    r = OrderService().create(100)
    assert_all(
        status_ok(r),
        json_equals(r, 'data.amount', 100),
    )
```

📖 [使用手册](docs/usr/user_guider.md)

## 日常工作流

![工作流](docs/dev/static/workflow.svg)

失败之后第一件事是**分清是用例错还是产品错**——这两件事是不同的人该去修的。归因层做的就是这个判定，`blames_system_under_test` 为假时，报告不会把它算成产品缺陷。

## LLM 的成本边界

**LLM 只出现在「编写时」和「运行后」，绝不出现在「运行时」。**

| 时机 | 是否用 LLM | 成本随什么增长 |
|---|---|---|
| 运行时（执行用例） | ❌ 绝不 | **恒为 0** |
| 编写时（起草用例） | ✅ 外部 agent 写文件 | 人 × 编写次数 |
| 运行后（失败归因、报告摘要） | ⚠️ 可选，默认关 | 失败数，可设上限 |

一天跑 10000 次用例，LLM 调用 0 次。这不是约定，是四条结构性保证：默认安装不含任何 LLM SDK；`ai.enabled: false`；`core/` 不得 import `ai/`（CI 用 AST 检查）；**`rm -rf src/ipandora/ai && pytest` 必须全绿**（CI 里真的在跑）。

📖 [`docs/design/03-LLM接入边界.md`](docs/design/03-LLM接入边界.md)

## 代码结构

代码在 `src/ipandora/`：

| | |
|---|---|
| `core/protocol` | 协议层。传输策略、响应解析 |
| `core/assertion` | 断言层。`Check` / `assert_all` / `require` / `gap` |
| `core/runner` | 库可调用的执行入口。CLI 和 MCP 都是它的薄壳 |
| `core/report` | ReportData → HTML / JSON / JUnit XML + 历史归档 |
| `core/triage` | 失败归因（规则优先，LLM 可选） |
| `core/evidence` | 请求响应证据采集 |
| `core/mcp` | agent 入口 |
| `ai/` | 可选 LLM 支持，可整包删除 |

## 设计文档

全部决策与返工记录在 [`docs/design/`](docs/design/)：

- [`README.md`](docs/design/README.md) — 索引与一页纸结论
- [`09-对齐新规划的现状复核.md`](docs/design/09-对齐新规划的现状复核.md) — 现状逐项对照架构图
- [`10-迭代方案.md`](docs/design/10-迭代方案.md) — 整改、能力拓展、agent 评测、安全两条线

## 开发

```shell
pytest                               # 全部密闭，零网络依赖
python scripts/smoke_import.py       # 每个模块都 import 得进来
python scripts/check_layering.py     # core/ 不得依赖 ai/
python scripts/check_secrets.py $(git ls-files)
python scripts/check_packaging.py    # 必需数据文件要真的进 wheel
python scripts/mutation.py core/report/junit.py   # 变异测试：故意改坏，看测试抓不抓得住
```

📖 [开发手册](docs/dev/IntelliPandora_Dev.md)

## License

Apache License 2.0

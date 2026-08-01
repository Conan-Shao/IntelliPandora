# IntelliPandora AI化路线图

## 背景

IntelliPandora 长期以来是纯规则驱动的自动化测试框架（分层架构 + pluggy 插件系统 + pymysql 用例仓库 + Jinja2 报告）。本文档记录把它演进为"AI化测试框架"的整体路线图，明确哪些能力已经落地（Phase 0/1），哪些是后续迭代方向（Phase 2/3）。

## Phase 0：可插拔 AI Provider 抽象（已落地）

新增 `src/ipandora/core/engine/ai/`，参照 `core/engine/crypto/` 的 `ABC + 具体实现 + Factory` 模式：

- `providerabc.py`：`AIProviderABC(ABC)`，只要求实现一个方法 `chat(messages, **kwargs) -> str`
- `anthropicprovider.py`：`AnthropicProvider`，用官方 `anthropic` 同步 SDK
- `mockprovider.py`：`MockProvider`，无需 API key，离线开发/单测默认使用
- `aifactory.py`：`AIProviderFactory`，根据 `Runtime.Ai.provider` 配置懒加载对应实现

切换后端（Anthropic / 内部网关 / 其他供应商）只需要新增一个实现类 + 改配置，调用方代码不用动。API Key 走 `CryptoFactory` 既有的解密约定，不明文存 config。

## Phase 1：MCP 能力暴露 + 智能断言（已落地）

### MCP Server
`src/ipandora/core/mcp/server.py` 用官方 `mcp` SDK 的 `MCPServer`（装饰器式 API，`@mcp.tool()`）暴露 4 个工具：
`list_test_cases` / `create_test_case` / `run_test_suite` / `get_test_report`。

设计取舍：**MCP Server 本身不内置 AI 逻辑**，只是把框架已有原语（建用例/跑用例/查报告）暴露成工具，"思考"交给连接过来的外部 AI 客户端（Claude Code/Claude Desktop 等）。这也正是 Phase 3 Agent 化编排的接口基础。

同步/异步隔离：`mcp` SDK 是 asyncio 的且要求 Python ≥3.10；框架其余部分（HTTP/断言/用例引擎）保持全同步不变，只有 `ipandora mcp` 这一个 CLI 子命令内部起事件循环。`mcp`、`anthropic` 都是 `setup.py` 的 `extras_require`，不强迫所有用户升级依赖。

### 智能断言
`utils/match.py` 的 `DictMatcher`/`Compare` 本来就是 `$op -> cmp_op` 的通用分发，新增 `Compare.cmp_semantic` 直接复用这个分发机制，调用 `AIProviderFactory().default.chat(...)` 做语义判断：

```python
response.filter(field={'$semantic': '看起来像一个合法的 UUID'})
```

## Phase 2：失败根因分析 / 智能报告（路线图，暂未实现）

目标：`RobotLogParser.parse_robot_results()` 产出的 `self.results["Details"]` 里，为失败用例调用 AI 生成一句话根因摘要。

落地方式：
- `RobotLogParser.handle_with_case` 在 `result == 'FAIL'` 时，把 `message`（失败堆栈/断言信息）传给 `AIProviderFactory().default.chat(...)`，prompt 要求给出"最可能的根因 + 建议排查方向"一句话结论，写入新字段 `case["rca"]`
- `conf/static/report_template_jinja2.html` 增加 `{% if case.rca %}` 展示块
- 为了不拖慢报告生成，建议异步/批量调用（一次性把所有失败 message 打包成一个 prompt），或加缓存/限流

未实现原因：这是本轮 Phase 0/1 地基验证之后的下一步，且报告改动需要真实失败样本调优 prompt 效果，放到有真实用例失败数据后再做更合适。

## Phase 3：Agent 化测试编排（路线图，暂未实现）

目标：让 Agent 自主探索被测系统、规划用例、执行、根据失败结果迭代。

依赖：
- Phase 0（AI Provider）+ Phase 1（MCP 工具面）已经提供了"Agent 可以调用什么"的基础设施——Agent 本身不需要框架内置一个 agent loop，可以直接是任何支持 MCP 的客户端（Claude Code、Claude Desktop 等）连上 `ipandora mcp` 来驱动
- 如果要框架内置一个自主 agent loop（而不是依赖外部客户端），还需要额外设计：
  - **执行安全边界**：防止 Agent 对生产系统做出破坏性操作（只读优先、白名单环境、人工审核点）
  - **上下文管理**：多轮探索-执行-观察的状态如何持久化和恢复
  - **成本/预算控制**：LLM 调用次数、单次任务的时间/token 上限

建议：先用 Phase 1 的 MCP 工具面接一个外部 AI 客户端跑几轮真实场景，验证工具粒度是否合适，再决定是否需要框架自带 agent loop。这个方向开放度最高，值得后续单独立项详细设计。

## 关于"自愈定位"的范围说明

现有框架没有任何 UI/浏览器协议层（只有 http/websocket），"UI 元素自愈定位"字面含义暂不适用。Phase 1 的"智能断言"是把这个方向重新落到"响应数据的语义级自愈匹配"；等未来真的加了 UI 协议层（如 Selenium/Playwright provider），再实现真正的定位器自愈。

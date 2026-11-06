# 使用指南

按任务组织。第一次用，从 [快速开始](quickstart.md) 读起。

| 想做什么 | 读这一篇 |
|---|---|
| 装好，生成一个项目，跑出第一份报告 | [快速开始](quickstart.md) |
| 弄清它和 pytest、Playwright 是什么关系，为什么这样设计 | [定位与对比](why.md) |
| 调用接口、读取响应、超时与重试 | [HTTP 接口](http.md) |
| 登录态：用例只写身份，token 和 cookie 由提供者获取、刷新 | [登录态](auth.md) |
| 组织用例库：接口、造数、页面、用例分层；`init --layout full` | [组织用例库](layout.md) |
| 写判定；理解零判定、判定清单和基线 | [判定、零判定与基线](judgements.md) |
| 并行执行；在一条用例里测并发 | [并行与并发](parallel.md) |
| Web 自动化（Playwright） | [Web 自动化](web.md) |
| 截图和基准图比对 | [图像判定](visual.md) |
| `conf/` 目录、按环境叠加、测试数据 | [配置、环境与测试数据](config.md) |
| 看报告、失败归因、在 Python 里直接调用 | [报告、归因与以库方式调用](reports.md) |
| 接进 CI：JUnit、门禁、基线评审 | [接入 CI](ci.md) |
| 让 agent 写用例：MCP、AGENTS.md | [接入 agent](agents.md) |
| 评测 agent：每题跑 k 次、成功率与区间、和基线比较、人工标注；多轮对话的业务 agent；agent 安全；回归门禁与饱和；编码 agent 的评分器（变异得分、改动范围）；读 Inspect 日志 | [评测 agent](eval.md) |
| 在用例里注入故障（延迟、断开、连接重置），归因分清注入的故障和真实的环境问题 | [故障注入](faults.md) |
| 记录并发操作的历史，判定线性一致、计数器 / 集合正确、事务隔离级别 | [一致性检查](consistency.md) |
| 从失败的请求跳到服务端的调用链路（Jaeger、Tempo） | [跨服务链路](tracing.md) |

查参数和配置项：[命令行参考](../reference/cli.md)、[配置参考](../reference/config.md)。这两份是从代码生成的，不会和代码不一致。

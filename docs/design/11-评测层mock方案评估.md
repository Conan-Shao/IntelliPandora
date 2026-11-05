# 评测层 mock 方案评估

> 2026-11-05 · **结论：mock 不进框架。** 录制回放（cassette）随之移除，见 `07-流量录制回放.md`。

## 结论

框架的定位是**通用测试框架**：HTTP 接口测试，UI 自动化（Web / App）在规划中；尽量少的业务侵入；不求复杂。在这个定位下：

- **框架不提供 mock。** 用例里需要桩掉某个响应，用 `responses`、`httpretty` 这类标准库就够了，不需要框架来管。
- **评测时为被测服务准备 mock 环境，是业务方的事。** 选什么工具、怎么编排，由业务仓库自己决定，框架不感知。
- **cassette 移除。** 评估下来它唯一说得通的用途就是给评测层当 mock；这个用途不成立，它就没有留下来的理由。

## 这一版推翻了上一版什么

上一版（同日早些时候）的推荐是「阶段 3/4 用 cassette，阶段 5 用 Anvil + Hoverfly 旁路容器」，并且把最终选型挂在一个问题上：**钱包在链下调用了哪些 HTTP 接口**。

这个问题不该由测试框架来问。它让一个具体业务系统的细节决定了框架的形态。Anvil 分叉链、价格规则、钱包的上游依赖，这些全都属于业务，应该放在业务仓库里。

## 评估中得出的、与具体业务无关的结论

调研本身没有白做。下面几条对任何需要 mock 的使用方都适用，留作参考。

### 1. mock 需求分两类，适用的手段不同

| | 被测对象发出的请求是否确定 | 谁发请求 | 适合的手段 |
|---|---|---|---|
| 测一组写好的用例 | 确定 | 测试进程自己 | 进程内桩（`responses` / `httpretty`）或录制回放 |
| 测一个会自己做决定的系统（如 agent） | **不确定** | **被测服务**，可能是另一个进程、另一种语言 | 网络层、**按规则生成响应**的 mock 服务 |

**录制回放是精确匹配。** 原型实测：录的是 `/pypi/requests/json`，那么 `/pypi/flask/json`、`?v=2`、换版本号，统统未命中。如果被测方会自己选择请求什么，回放就会大面积 miss。

### 2. 网络层故障要做对，有一条长尾

原型里，延迟、改状态码各一两行。但「连接被重置」第一版就做错了：HTTP/1.1 keep-alive 下 `close()` 不发 RST，客户端会挂起直到自己超时，必须设 `SO_LINGER(1, 0)`。WireMock 3.13.2 内置了四种网络故障：`CONNECTION_RESET_BY_PEER`、`EMPTY_RESPONSE`、`MALFORMED_RESPONSE_CHUNK`、`RANDOM_DATA_THEN_CLOSE`。**这部分不要自己写。**

### 3. 选网络级 mock 工具时的安全判据：管理 API 能否在网络层隔离

WireMock 和 Hoverfly 都有运行时管理 API，可以在运行中改 stub。如果被测方（例如 agent）能访问到 mock 的管理 API，**它就能改掉自己要被评判的数据**。

| | 管理 API 的位置 | 能做的防护 |
|---|---|---|
| WireMock 3.13.2 | 与 stub **同端口**（`/__admin/*`），没有关闭选项，也不能单独开端口 | 只有 `--admin-api-basic-auth`。唯一的防线是一个密码 |
| Hoverfly 1.12.17 | **独立端口**（默认 8888），服务端口默认 8500，服务端口一侧的源码对管理 API 零引用 | 网络层把 8888 挡在被测方之外，再加 `-auth`。两道防线 |

### 4. 错误注入要在判分侧、在响应时发生

不能事先写一份「篡改过的」数据文件给 mock 用：要么和完整性校验冲突，要么被测方能看到被注入了哪些字段，进而专门针对它们写断言，评测就失效了。

### 5. Inspect 的沙箱直接支持旁路容器

`compose.yaml` 可以定义多个服务；文档原话建议：服务之间只需要互通时，用 **internal network**。被测容器加 mock 旁路容器、不通外网，是它直接支持的用法。

---

## 核实记录

| 结论 | 来源 | 核实于 |
|---|---|---|
| 精确匹配导致参数一变即 miss；连接重置需 `SO_LINGER(1, 0)` | 本地原型，curl 实测 | 2026-11-05 |
| WireMock 4 种网络故障、模板、Scenario、匹配器 | `wiremock-standalone-3.13.2.jar` 类清单与 `Fault.class` 常量 | 2026-11-05 |
| WireMock 管理 API 只能加 basic auth，无关闭选项，无独立端口 | 同 jar，`CommandLineOptions.class` 全部字符串常量**不限前缀**检索 | 2026-11-05 |
| WireMock 稳定线 3.13.2，4.x 仍为 beta | `repo1.maven.org` maven-metadata.xml | 2026-11-05 |
| Hoverfly 管理端口独立（默认 8888）、`-auth` | `core/cmd/hoverfly/main.go`、`core/settings.go` | 2026-11-05 |
| Hoverfly 服务端口不暴露管理 API | `core/admin.go`：管理路由仅在 `AdminPort` 上 `ListenAndServe`；`core/proxy.go`、`core/hoverfly.go` 对管理 API 零引用 | 2026-11-05 |
| Hoverfly 模板（query / path / JSONPath）、state | `SpectoLabs/hoverfly` 仓库 `docs/pages/keyconcepts/{templating,state}` | 2026-11-05 |
| mitmproxy server_replay、modify_body | `docs/src/content/overview/features.md` | 2026-11-05 |
| Prism 从 OpenAPI 生成假响应 | `stoplightio/prism` README | 2026-11-05 |
| Inspect 支持 compose 多服务、建议 internal network | `inspect_ai` 仓库 `docs/sandboxing.qmd` | 2026-11-05 |

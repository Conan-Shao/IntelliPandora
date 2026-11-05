# 评测层 mock 方案评估

> 2026-11-05 · 依据《AI 时代的测试框架：迭代计划》阶段 3 / 4 / 5 与「安全要求」
>
> 前提已确认：评测层需要 mock。本文回答的是**用什么做、怎么做**。所有关于第三方工具的结论都核实过来源，见文末「核实记录」；关于 cassette 的结论来自读代码与一个可运行的原型。

---

## 结论先行

1. **规划里其实有两种 mock 需求，不是一种。** 阶段 3/4 的被测对象是「AI 写好的用例」，请求是确定的；阶段 5 的被测对象是 **agent 本身**，请求由 agent 自己决定。前者适合录制回放，后者不适合。
2. **阶段 3/4 用现有的 cassette（进程内）**，补两件事：判分侧在回放时注入错误、读时校验完整性。不需要新工具。
3. **阶段 5 的链上状态用 Anvil（规划已定），链下 HTTP 依赖用 Hoverfly 作旁路容器。** 选它而不是 WireMock，决定性理由是安全：Hoverfly 的管理接口在独立端口，能在网络层挡在 agent 之外；WireMock 的管理接口与 stub 同端口，只能靠一个密码。

**不建议给 cassette 加服务端模式。** 原型证明服务化只要 60 行，但真正的工作量在规则匹配、响应模板和网络层故障——那正是现成工具已经做好、而我在原型里第一次就做错了的部分。

---

## 一、需求：从规划里抽出来

| | 阶段 3 注入抽查 | 阶段 4 评测试插件 | 阶段 5 评 agentic wallet |
|---|---|---|---|
| 规划原文 | 用 mock 故意返回错误结果，看用例会不会失败 | 用例能跑通、覆盖关键路径、能抓住注入的错误 | 用 Anvil 分叉 BSC 和 ETH，价格接口用 mock，跑完查链上状态判分 |
| **被测对象** | AI 写的用例 | 测试插件（产出用例） | **agent 产品** |
| **谁发 HTTP 请求** | IntelliPandora 用例 | IntelliPandora 用例 | **钱包服务**，不是 IntelliPandora |
| **请求是否确定** | 是 | 是 | **否——查什么、换多少由 agent 决定** |
| 需要的 mock 行为 | 回放 + 注入错误 | 同左 | **按规则生成**响应；模拟上游故障 |
| 有状态 | 基本不需要 | 基本不需要 | 价格随时间变化；链上状态由 Anvil 承担 |
| 运行位置 | 判分侧 | 判分侧，用例在沙箱里产出 | Docker 沙箱，网络能关就关 |

两条决定性的观察：

**第一，阶段 5 发请求的是钱包服务，不是 IntelliPandora。** cassette 是挂在 `requests` 会话上的进程内适配器（`ReplayAdapter(HTTPAdapter)`），没有任何对外监听的服务端模式。它根本拦不到另一个进程、可能是另一种语言写的服务发出的请求。阶段 5 必须是**网络层**的 mock。

**第二，阶段 5 的请求不确定。** 录制回放是精确匹配。原型实测，录的是 `/pypi/requests/json`：

```
/pypi/requests/json          → 200
/pypi/flask/json             → 599  未命中
/pypi/requests/json?v=2      → 599  未命中
/express/4.18.2              → 599  未命中
```

agent 换一个币种、换一个金额就 miss。而 agent 怎么选，恰恰是阶段 5 要评的东西。这里需要的是「查任意币种 → 从价格表里取」这种**按规则生成**的响应。

---

## 二、候选方案

所有能力描述都已核实（来源见文末）。

| | 形态 | 回放 | 规则匹配 / 模板 | 有状态 | 网络层故障 | 管理接口 | 运行时 | 维护状态 |
|---|---|---|---|---|---|---|---|---|
| **cassette** | 进程内适配器 | ✅ 精确匹配 | ❌ | 同键顺序播放 | ❌ | 无（进程内） | 无新依赖 | 本仓库 |
| **WireMock 3.13.2** | 独立服务 | ✅ 录制 | ✅ JSONPath / 正则 / Handlebars 模板 | ✅ Scenario | ✅ 4 种 | **与 stub 同端口**，可加 basic auth，**无法关闭** | JVM，jar 19MB | 活跃；4.x 仍在 beta |
| **Hoverfly 1.12.17** | 独立服务（webserver 模式） | ✅ capture | ✅ query / path / JSONPath 模板 | ✅ state map | 延迟、随机失败、限流 | **独立端口 8888**，`-auth` | Go 单二进制 | 活跃，2026-11-01 发布 |
| **mitmproxy 12.3.1** | 拦截代理 | ✅ server_replay | Python addon，完全可编程 | 自己写 | 自己写 | Web UI / API | Python ≥ 3.12 | 活跃 |
| **Prism 5.16.0** | 独立服务 | ❌ | 从 OpenAPI 生成 | ❌ | ❌ | — | Node ≥ 18 | 活跃 |

### 逐个排除

**mitmproxy**——它最强的地方是拦截**你改不了配置**的流量。但钱包是自家产品，把价格接口的 base URL 指向 mock 是一行配置的事，用不着拦截。代价却很实在：它是 TLS 中间人代理，被测服务要信任它的 CA 证书，这本身就扩大了攻击面；故障与规则都要自己写 addon。

**Prism**——从 OpenAPI 生成的响应在结构上合法，但**语义上不对**：生成的价格是示例值或随机值，不是一个真实的价格。它的价值在契约校验，不在评测环境。

**cassette 服务端模式**——见第三节原型。

**respx / responses 这类库级 mock**——和 cassette 同样是进程内的，阶段 5 用不上；阶段 3/4 又已经有 cassette。不引入。

---

## 三、原型：给 cassette 加服务端到底要多少

为了不凭估算做「自建 vs 采用」的判断，写了一个用标准库 `http.server` 的原型（未进仓库，在 scratchpad）。

**问题 1：`Cassette.play()` 能不能脱离 `requests` 单独用？** 能，一行没改。`play(method, url, body)` 吃的是普通参数。curl（代表一个非 Python 的钱包服务）拿到了原样的 222KB 响应，字段解析正确；未录过的请求返回 599，并说明是哪一条没对上。

**问题 2：故障注入要加多少？**

| 故障 | 结果 |
|---|---|
| 延迟 1500ms | ✅ 实测 1.50s |
| 状态码改成 503 | ✅ |
| 未录过 | ✅ 599，不会被误认为真实响应 |
| 连接被重置 | ❌ **第一版做错了**：`connection.close()` 在 HTTP/1.1 keep-alive 下没有发 RST，客户端挂起 5 秒后自己超时 |
| 连接被重置（修正） | ✅ 设 `SO_LINGER(1, 0)` 后 0.0009 秒「Connection reset by peer」；IntelliPandora 传输层正确判为 `HttpConnectionError` |

原型规模：**60 行非注释代码**。

**这组数据的含义**：服务化本身很便宜，延迟和状态码各一两行。但网络层故障要做对需要知道 `SO_LINGER` 这类细节，而且是长尾的——WireMock 3.13.2 的 jar 里，`Fault` 枚举有四种：`CONNECTION_RESET_BY_PEER`、`EMPTY_RESPONSE`、`MALFORMED_RESPONSE_CHUNK`、`RANDOM_DATA_THEN_CLOSE`。我做第一种就错了一次。

更关键的是：**服务化解决不了第一节的第二条观察**。即使 cassette 能在网络上回放，它仍然是精确匹配，阶段 5 照样大面积 miss。要补的不是 60 行服务端，是规则匹配和响应模板——那就是在重写 Hoverfly。

---

## 四、安全维度：谁能让评测结果与事实不符

规划的安全要求明写「隐藏测试和判分脚本放在沙箱外」「防止 agent 为了变绿去改断言」。同样的思路必须用在 mock 上：**能改 mock 的人，就能决定评测结果**。

### 4.1 完整性：没有一个方案开箱即带

| | 现状 | 需要补的 |
|---|---|---|
| cassette | blob 按 `sha256-<hash>` 命名，但 `get_blob()` **读时不验哈希**（`10-迭代方案.md` 已记录） | 读时验哈希；manifest 记录 `exchanges.jsonl` 的摘要 |
| WireMock / Hoverfly | stub / simulation 都是普通 JSON 文件，无任何校验 | 只读挂载 + 判分侧启动前校验目录摘要，摘要随数据集版本冻结 |

cassette 反而离完整性最近——它已经是按内容寻址的，差一步校验。

### 4.2 运行时篡改：这是 WireMock 与 Hoverfly 的分水岭

两者都有运行时管理 API，可以在运行中增删改 stub。阶段 5 里，agent 所在容器与 mock 旁路容器在同一个内部网络上——**agent 可能直接调管理 API 改价格**。

- **WireMock**：管理 API 走 `/__admin/*`，与 stub **同一个端口**。3.13.2 的启动参数里有 `--admin-api-basic-auth`、`--admin-api-require-https`，**但没有关闭它的选项**。也就是说，唯一的屏障是一个密码不出现在 agent 的环境里。
- **Hoverfly**：服务端口（默认 8500）与管理端口（默认 8888）**分开**，另有 `-auth`。可以把 8888 放在只有判分侧能到的网络上，agent 所在网络里根本没有这个端口——**网络层隔离加鉴权，两道防线**。

这一条是选 Hoverfly 的决定性理由。

### 4.3 注入必须在判分侧、在服务时发生

阶段 3/4 的错误注入，**不能靠写一份被篡改过的磁带**：

1. 篡改过的磁带会和 4.1 的完整性校验互相冲突——要么校验形同虚设，要么注入用不了；
2. 磁带若出现在 agent 能读的地方，agent 就能针对被注入的那几个字段写断言，评测就失效了。

所以注入应当是**回放时**应用一份由判分侧持有的规则（「把 `data.price` 改成 0」「这个请求返回 503」），磁带本身保持原样、可校验。

### 4.4 供应链

规划要求「依赖版本锁死，走公司内部镜像源，安装前扫描」。

| | 扫描面 |
|---|---|
| cassette（阶段 3/4） | 零新依赖 |
| Hoverfly | 单个 Go 静态二进制 |
| WireMock | 19MB jar，含 Jetty、Jackson、Handlebars 等传递依赖，外加 JVM |

两个独立服务都运行在**自己的旁路容器里**，不进 agent 的容器，这一点对两者相同。

---

## 五、推荐方案

```
阶段 3 / 4                              阶段 5
───────────────────                     ──────────────────────────────────────────
IntelliPandora 用例                      agent 容器（钱包服务）
      │ requests                               │                    │
      ▼                                        ▼ HTTP               ▼ JSON-RPC
ReplayAdapter ── 判分侧注入规则          Hoverfly :8500          Anvil 分叉链
      │                                   （webserver 模式）      （BSC / ETH）
      ▼                                        │
cassette（只读、校验后加载）              simulation（只读、校验后加载）
                                               ▲
                                          :8888 管理端口
                                          只在判分侧网络
                        ┌──────────────────────┘
                        │  种子数据
           cassette 录下的真实上游响应
           （脱敏后，经导出转换）
```

### 阶段 3 / 4：cassette，进程内

请求是确定的，录制回放是对的模型。补两件事：

1. **读时校验完整性**——`get_blob()` 验哈希，manifest 记 `exchanges.jsonl` 摘要。这一条无论选什么都要做。
2. **回放时注入**——`ReplayAdapter` 接受一份判分侧的注入规则：改字段值、改状态码、加延迟、抛连接错误；批量跑出「检出率」。这就是阶段 3 完成标准里那个待定的比例。

### 阶段 5：Anvil + Hoverfly 旁路容器

- **链上状态**交给 Anvil（规划已定）。余额、授权、交易结果是真实 EVM 状态，不是 mock 能代替的。
- **链下 HTTP 依赖**（价格等）交给 Hoverfly：webserver 模式，按 query / path 参数匹配，价格表写成规则；需要「报价到成交之间价格变动」就用它的 state。
- **管理端口 8888 放在只有判分侧能到的网络**，开 `-auth`。
- simulation 文件只读挂载，启动前判分侧校验摘要，摘要随数据集版本冻结——对应规划「数据集有版本，对比时冻结」。
- 按 Inspect 文档的建议，服务间只需互通时用 **internal network**：agent 容器能到 Hoverfly 和 Anvil，不通外网。

### cassette 在阶段 5 的位置：数据来源，不是服务端

规划写「数据集来源：真实的 bug、事故和线上对话，脱敏后入库」。cassette 已经能从 HAR / nginx / envoy 导入真实流量并在写入时脱敏。补一个 `ipandora cassette export --format hoverfly`，把录下的真实响应转成 Hoverfly simulation 的种子，再人工改成规则。

这样**采集、脱敏、完整性**只有一条管线（cassette），**服务**只有一个引擎（Hoverfly）。

### 一个场景设计上的陷阱

钱包从 mock 读价格，却在 Anvil 分叉链上成交。分叉链上 DEX 池子的真实价格与 mock 价格**如果不一致，就会出现规划之外的滑点**。要么让 mock 价格从分叉区块的池子状态算出来，要么把不一致当成一个**刻意设计**的滑点场景。不能让它偶然发生。

---

## 六、什么会推翻这个推荐

**钱包的链下 HTTP 依赖有多大、有多少状态？** 这一点我无从得知，它决定了 Hoverfly 是否够用：

- 如果只有少量只读接口（价格、代币元数据）——Hoverfly 绰绰有余，本推荐成立。
- 如果有大量第三方接口，或有「报价 → 凭 quoteId 成交 → 查订单状态」这类**由请求驱动的状态机**，而且需要分块编码损坏、响应截断这类细粒度网络故障——WireMock 的 Scenario 和四种 `Fault` 更完整。那时改用 WireMock，**但必须补上管理 API 的隔离**：在它前面加一层只转发非 `/__admin` 路径的反向代理，或者至少保证 basic auth 的凭据只存在于判分侧。

Hoverfly 的「随机失败」具体能模拟到哪一层网络故障，我只核实到 README 的描述，没有核实到 WireMock 那样的枚举粒度。如果阶段 5 的安全集里有「上游连接被重置时钱包不能重复下单」这类用例，选型前要先实测 Hoverfly 能否产出真正的 RST。

---

## 七、落地拆解

不卡外部输入、可立即做的：

| # | 项 | 依赖 | 规模 |
|---|---|---|---|
| 1 | cassette 读时校验完整性 | 无 | 小 |
| 2 | 回放时注入规则 + 检出率统计 | 1 | 中 |
| 3 | `cassette export --format hoverfly` | 无 | 小 |

卡外部输入的：

| # | 项 | 卡在 |
|---|---|---|
| 4 | Hoverfly + Anvil + agent 的 compose 模板 | 钱包服务的镜像与配置方式 |
| 5 | 价格规则与场景 | 钱包实际调用哪些链下接口（即第六节的问题） |
| 6 | 内部镜像源引入 Hoverfly 镜像 | 公司镜像与扫描流程 |

---

## 核实记录

| 结论 | 来源 | 核实于 |
|---|---|---|
| cassette 是进程内适配器，无服务端 | `core/protocol/http/replay.py`：`class ReplayAdapter(HTTPAdapter)`；全仓库无 `HTTPServer` / `bind` / `listen` | 读代码 |
| cassette 同键顺序播放 | `core/cassette/cassette.py`：`_cursor`、`OnExhausted` | 读代码 |
| cassette 无故障注入 | 同上目录无延迟 / 超时 / 断连相关代码 | 读代码 |
| `Cassette.play()` 可脱离 requests 使用 | 原型，curl 实测 | 2026-11-05 |
| 精确匹配导致参数变化即 miss | 原型，curl 实测 | 2026-11-05 |
| WireMock 4 种网络故障、模板、Scenario、匹配器、Recorder | `wiremock-standalone-3.13.2.jar` 类清单与 `Fault.class` 常量 | 2026-11-05 |
| WireMock 管理 API 只能加 basic auth，无关闭选项，无独立端口 | 同 jar，`CommandLineOptions.class` 全部字符串常量**不限前缀**检索：含 `admin` 的参数只有 `admin-api-basic-auth`、`admin-api-require-https` | 2026-11-05 |
| WireMock 稳定线 3.13.2，4.x 仍为 beta | `repo1.maven.org` maven-metadata.xml | 2026-11-05 |
| Hoverfly 模板（query / path / JSONPath）、state | `SpectoLabs/hoverfly` 仓库 `docs/pages/keyconcepts/{templating,state}` | 2026-11-05 |
| Hoverfly 管理端口独立（`-ap`，默认 8888）、`-auth` | `core/cmd/hoverfly/main.go`、`core/settings.go` | 2026-11-05 |
| Hoverfly 服务端口**不**暴露管理 API | `core/admin.go`：管理路由与 dashboard 挂在同一个路由器上，仅在 `AdminPort` 上 `ListenAndServe`；`core/proxy.go`、`core/hoverfly.go` 服务端口一侧对管理 API 零引用 | 2026-11-05 |
| Hoverfly v1.12.17，2026-11-01 | `proxy.golang.org` | 2026-11-05 |
| mitmproxy server_replay、modify_body | `docs/src/content/overview/features.md` | 2026-11-05 |
| mitmproxy 12.3.1，Python ≥ 3.12 | `pypi.org` | 2026-11-05 |
| Prism 从 OpenAPI 生成、Node ≥ 18 | `stoplightio/prism` README | 2026-11-05 |
| Inspect 支持 compose 多服务、建议 internal network | `inspect_ai` 仓库 `docs/sandboxing.qmd` | 2026-11-05 |
| inspect-ai 0.3.287，Python ≥ 3.11 | `pypi.org` | 2026-11-05 |

# 第三方组件登记表

> 框架引入的每一个第三方组件都登记在这里，并且已经过准入审查（准入规则见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md) §3）。
>
> **这张表由 CI 核对**（`scripts/check_components.py`）：凡是 `setup.cfg`、`setup.py`、`requirements/*.in` 里声明的依赖，或 `.github/workflows/` 里引用的动作，都必须在表中出现，并且版本写法要完全一致；表里多出来、实际已不再使用的条目也会被拦下。不在表里的组件无法合入。
>
> 漏洞状态不写在这里，见每日自动更新的 [安全报告](report.md)。

## 运行时依赖

用户执行 `pip install intellipandora` 时会装上这些。

| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|
| requests | runtime | >=2.31,<3 | HTTP 客户端 | Apache-2.0 | 对用例里配置的地址发请求 | 2026-11-05 |
| urllib3 | runtime | >=2.0,<3 | 传输层：重试、连接池 | MIT | 同上 | 2026-11-05 |
| PyYAML | runtime | >=6.0,<7 | 读取配置文件 | MIT | 仅用 `safe_load` | 2026-11-05 |
| cryptography | runtime | >=42.0,<51 | 测试数据的加解密工具 | Apache-2.0 OR BSD-3-Clause | 密钥放在 `~/.ipandora/crypto`（目录权限 0700） | 2026-11-05 |
| pluggy | runtime | >=1.3,<2 | 插件机制 | MIT | 无 | 2026-11-05 |
| Jinja2 | runtime | >=3.1,<4 | 渲染 HTML 报告 | BSD-3-Clause | 开启自动转义 | 2026-11-05 |
| jsonschema | runtime | >=4.20,<5 | 响应结构校验 | MIT | 无 | 2026-11-05 |
| pytest | runtime | >=7.4,<10 | 用例运行器 | MIT | 运行用例 | 2026-11-05 |

## 可选安装组

只有显式安装 `intellipandora[<组名>]` 时才会装上。

| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|
| anthropic | extra:ai | >=2.1,<3 | 可选的 LLM 失败归因 | MIT | 调用 Anthropic API；默认关闭，有调用上限。2.x 已核对框架用到的接口（`Anthropic()`、`messages.create`、`TextBlock.text`）未变 | 2026-11-05 |
| mcp | extra:mcp | >=2.0,<3 | 作为 agent 的 MCP 服务端 | MIT | 通过 stdio 与 agent 通信 | 2026-11-05 |
| psutil | extra:system | >=5.9,<8 | 系统信息工具 | BSD-3-Clause | 读取本机进程和资源信息 | 2026-11-05 |
| pytest-xdist | extra:parallel | >=3.8,<4 | `--workers` 多进程并行 | MIT | 启动 N 个本机子进程运行用例，经 stdin/stdout 管道通信（execnet），不联网。pytest-dev 组织维护；3.8.0 发布于 2025-07，超过 12 个月无新版，但功能稳定、仍在维护，按此登记 | 2026-11-05 |
| pytest-timeout | extra:parallel | >=2.4,<3 | `--timeout` 单条用例超时 | MIT | 用信号或看门狗线程中断超时用例。pytest-dev 组织维护；2.4.0 发布于 2025-05，超过 12 个月无新版，理由同 pytest-xdist | 2026-11-05 |
| playwright | extra:web | >=1.64,<2 | Web 自动化驱动 | Apache-2.0 | **运行时下载浏览器**（`python -m playwright install chromium`），默认从微软 CDN 下载，可用 `PLAYWRIGHT_DOWNLOAD_HOST` 指向内部镜像；浏览器版本由 Playwright 版本锁定（1.64.0 → Chromium 1248）。也可以用 `--browser-channel chrome` 改用系统 Chrome。驱动是随包附带的 Node 进程，经管道通信。依赖 greenlet、pyee | 2026-11-05 |
| pytest-playwright | extra:web | >=0.10,<0.11 | `page` / `browser` fixture、失败截图与 trace | Apache-2.0 | 每次会话开始时清空 `--output` 目录（框架为每次运行单独指定一个）。还是 0.x，锁到一个次版本，并有集成测试检查我们依赖的 fixture 和选项。传递依赖 text-unidecode 为 Artistic / GPL 双许可，按 Artistic 使用，见 `scripts/check_components.py` 的 REVIEWED_LICENSES | 2026-11-05 |
| pillow | extra:visual | >=12,<14 | 读写图片、遮罩、差异图 | MIT-CMU | 只解码测试自己产生的截图和仓库里的基准图。**图像解析历史上漏洞多**（`15` §7），每日扫描重点关注；13.x 要求 Python ≥ 3.11，3.10 上解析到 12.x | 2026-11-05 |
| pixelmatch | extra:visual | >=0.4,<0.5 | 逐像素比对：抗锯齿识别、YIQ 色差 | ISC | 纯 Python，无依赖，不联网。整图比对约 0.7 秒（1280×720），只在差异包围盒上运行，局部变化时为毫秒级，计数与整图一致（有测试） | 2026-11-05 |
| inspect-ai | extra:inspect | >=0.3.283,<0.4 | agent 评测的 Inspect 路径：读 Inspect 日志（`read_eval_log`），把评分器包成 Inspect 的 scorer | MIT | 框架只调用它的日志读取和评分器注册，不启动它的运行器。用户自己用它跑评测时，它会调用模型 API、在 Docker / K8s 里建沙箱、往 `./logs` 写日志、可启动本机 Web 服务（`inspect view`）。英国 AI Security Institute 维护，几乎每周发布；0.3.287 未满 14 天，选 0.3.283（2026-10-21）。**要求 Python ≥ 3.11**，3.10 上这个安装组不装任何东西。传递依赖约 60 个（boto3、aiobotocore、s3fs、fastapi、uvicorn、textual、numpy、tiktoken 等，用于云存储日志、查看器和分词），只在 Python ≥ 3.11 上装；许可证均在白名单内，agent-client-protocol 的元数据未写许可证，wheel 里的 LICENSE 是 Apache-2.0，见 `scripts/check_components.py` 的 LICENSE_OVERRIDES。pip-audit 无已知漏洞（2026-11-06） | 2026-11-06 |
| uiautomator2 | extra:android | >=3.7.1,<4 | Android 自动化（`core/android.py`，决策 14 §5 M5）：用例直接拿它的 `Device` | MIT | **往被测设备上装东西**：wheel 里带了 `u2.jar`（设备端的 UiAutomator 服务）和 `app-uiautomator.apk`，连接时经 adb 推到设备上运行，输入法 APK 只在需要时装；之后经 adb 转发的本机端口（`127.0.0.1`）和设备端服务通信。只有调用方给出 URL 时才联网（`app_install(url)`、图片模板）——框架只传本地路径。openatx 维护，3.7.1 发布于 2026-10-23。传递依赖：adbutils 2.12.0（MIT，**manylinux wheel 里自带一个 `adb` 可执行文件**，也会用 PATH 里的 adb；它的命令行能下载额外的二进制，框架不用）、lxml 6.1.3（BSD-3-Clause，解析控件树的 XPath）、retry2 0.9.5（Apache-2.0，2023-01 之后没有新版，代码只是一个重试装饰器，按此登记）、decorator 5.3.1（BSD-2-Clause）、deprecation 2.1.0（Apache-2.0），以及已登记的 requests、Pillow、click。pip-audit 无已知漏洞（2026-11-07） | 2026-11-07 |
| httpretty | extra:test | >=1.1,<2 | 测试里模拟 HTTP 响应 | MIT | 只在测试中替换 socket | 2026-11-05 |

## 构建与工具链

只在 CI 和维护者本地使用，不会安装到用户环境。版本由 `requirements/*.txt` 锁定并附哈希。

| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|
| setuptools | build | >=84.1,<85 | 构建后端 | MIT | 构建期执行 `setup.py` | 2026-11-05 |
| wheel | build | >=0.45,<1 | 构建 wheel | MIT | 无 | 2026-11-05 |
| pip-audit | tool | ==2.10.1 | 依赖漏洞扫描 | Apache-2.0 | 查询 PyPI / OSV 漏洞库 | 2026-11-05 |
| bandit | tool | ==1.9.4 | 自身代码的静态安全扫描 | Apache-2.0 | 只读源码 | 2026-11-05 |
| cyclonedx-bom | tool | ==7.5.0 | 生成 SBOM | Apache-2.0 | 只读环境元数据 | 2026-11-05 |
| build | tool | ==1.6.1 | 构建前端 | MIT | 在隔离环境中构建 | 2026-11-05 |
| uv | tool | ==0.13.4 | 生成带哈希的锁文件 | MIT OR Apache-2.0 | 解析依赖时访问 PyPI | 2026-11-05 |
| mutmut | tool | ==3.8.0 | 变异测试（`scripts/mutation.py`），检验测试能否发现被改坏的实现 | BSD-3-Clause | 在临时副本里改写源码并运行测试；不联网。3.8.1 发布未满 14 天，选 3.8.0；依赖 textual、libcst 等，许可证均在白名单内 | 2026-11-06 |

## 外部工具

不是 Python 依赖，不随包分发、不由 pip 安装；框架作为子进程调用它们。按 `15` §3 同样准入：钉住版本和文件的 SHA-256，框架在每次运行前核对，不一致就拒绝运行。

| 组件 | 用途 | 版本 | 来源 | SHA-256 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|---|
| elle-cli | 一致性检查（`core/consistency.py`，决策 18 D3）：Knossos 判线性一致，Elle 判事务隔离异常，Jepsen 的 counter / set / bank 检查器 | 0.1.11（2026-09-01 构建） | GitHub release `elle-cli-bin-0.1.11.zip`（zip 的 SHA-256 `9d3c72eaf3ccc4d0c7dc1da710264dee01f03af58c9fa177fec3f78ff5af1779`） | jar：`85c39a6247509075bf21762d4c8ed3a2cb3d2c9b2c169cb2c80dde25fa760388` | EPL-1.0 或更新版本（Elle、Knossos、Jepsen 同为 EPL-1.0）。**不在白名单内，经单独评审接受**（决策 18 §7）：作为外部工具调用，不分发、不链接，框架代码与它之间只有命令行和文件 | 需要 Java 21+。读一个历史文件，向标准输出写结论，不联网；`--directory` 未使用，不写图。发布流程带 `overwrite: true`，同名文件可能被替换，所以核对哈希而不是只看版本号 | 2026-11-06 |
| Android 模拟器 + 系统镜像（`system-images;android-34;google_apis;x86_64`） | CI 的 `android` 作业里运行 Android 验收用例（`test/testandroid/test_on_emulator.py`） | 由 android-emulator-runner 按 API 34 取当时的最新修订 | Google 的 Android SDK 仓库（`dl.google.com`），经 sdkmanager | —（sdkmanager 按仓库清单里的校验和核对下载内容；修订号由 Google 发布，不钉哈希） | Android SDK License（只在 CI 里使用，不分发、不链接）。**不在白名单内，经单独评审接受**：这是使用 Android 模拟器的唯一途径 | 只在 CI 的 runner 上运行，跑完即销毁；被测的是镜像自带的"设置"App，不下载第三方 APK | 2026-11-07 |
| Docker Engine + Docker Compose | 依赖环境编排（`core/stack.py`，决策 19 D5）：`up --wait`、`port`、`logs`、`down -v` | Compose ≥ 2.20（`--wait-timeout`），运行时检查 | 用户自己安装的系统工具；框架不下载、不分发 | —（系统工具，版本由用户环境决定，不钉哈希） | Apache-2.0 | 框架只用完整路径调用 `docker compose`，参数为列表、不经 shell，只操作自己创建的 `ipandora-<主机>-<进程>-` 项目；清理只删本机已不存在的进程留下的项目。容器里运行什么由用户的 compose 文件决定 | 2026-11-06 |

## 测试用容器镜像

只在本仓库的测试和 CI 里拉取（`test/teststack/compose/`），不随包分发。按摘要（digest）钉住，标签被改指向也拉不到别的内容；测试核对这里登记的摘要与 compose 文件一致。

| 镜像 | 用途 | 版本 | 来源 | 摘要 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|---|
| busybox | 依赖环境测试里的 HTTP 服务（`httpd`）、健康检查（`wget`） | 1.37.0（2024-09-26 构建） | Docker 官方镜像，经 `mirror.gcr.io/library/busybox` 拉取（Docker Hub 匿名拉取限流） | `sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec` | GPL-2.0。**不在白名单内，经单独评审接受**：只在本仓库的测试里作为容器运行，不链接、不随包分发；几乎所有基础镜像都带 GPL 的用户态工具 | 容器内运行测试自己的命令，只监听容器端口，由 Docker 随机映射到本机 | 2026-11-06 |
| toxiproxy | 依赖环境测试里的真实 Toxiproxy（D4 故障注入经它作用于服务） | 2.12.0（2025-03-18 构建） | `ghcr.io/shopify/toxiproxy`，Shopify 官方 | `sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e` | MIT | 转发 TCP；HTTP 管理接口只映射到本机随机端口 | 2026-11-06 |

## CI 动作

固定到提交 SHA，不用可被改指向的标签。选定版本均已发布满 14 天。

| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|
| actions/checkout | action | v7.0.1@3d3c42e5aac5ba805825da76410c181273ba90b1 | 检出代码 | MIT | 用工作流令牌读取仓库 | 2026-11-05 |
| actions/setup-python | action | v7.1.0@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 | 安装 Python | MIT | 下载 Python 构建 | 2026-11-05 |
| actions/upload-artifact | action | v7.0.2@cf430e030ddbb5b0abf93d22962f4752f3646cd9 | 上传报告、wheel、SBOM | MIT | 写入工作流制品 | 2026-11-05 |
| actions/download-artifact | action | v8.0.2@9000827ccba6bdab643e8b6fd33ac0654aef8333 | 发布作业取回构建产物，使构建与持有发布凭据的作业分开 | MIT | 读取本次运行的工作流制品 | 2026-11-05 |
| reactivecircus/android-emulator-runner | action | v2.38.0@a421e43855164a8197daf9d8d40fe71c6996bb0d | CI 的 `android` 作业：装 Android SDK 的模拟器和系统镜像，启动模拟器，跑 Android 的验收用例（M5b） | Apache-2.0（LICENSE 文件；package.json 写的是 MIT，以 LICENSE 为准，两者都在白名单内） | 在 runner 上用 sdkmanager 从 Google 的 SDK 仓库下载模拟器和系统镜像（sdkmanager 校验它们），创建并启动 AVD，运行给定脚本后关掉模拟器。不接触仓库令牌。v2.38.0 发布于 2026-07-05 | 2026-11-07 |
| pypa/gh-action-pypi-publish | action | v1.14.3@7245906fb61fa33a13554f9d5fb856fe61758086 | 发布到 PyPI（Trusted Publishing，附来源证明） | BSD-3-Clause | 使用 OIDC 令牌，仅在 `pypi` 环境中运行 | 2026-11-05 |

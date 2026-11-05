# 第三方组件登记表

> 框架引入的每一个第三方组件都登记在这里，并且已经过准入审查（准入规则见 [`docs/design/15`](../design/15-第三方组件安全准入与漏洞扫描.md) §3）。
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

## CI 动作

固定到提交 SHA，不用可被改指向的标签。选定版本均已发布满 14 天。

| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |
|---|---|---|---|---|---|---|
| actions/checkout | action | v7.0.1@3d3c42e5aac5ba805825da76410c181273ba90b1 | 检出代码 | MIT | 用工作流令牌读取仓库 | 2026-11-05 |
| actions/setup-python | action | v7.1.0@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 | 安装 Python | MIT | 下载 Python 构建 | 2026-11-05 |
| actions/upload-artifact | action | v7.0.2@cf430e030ddbb5b0abf93d22962f4752f3646cd9 | 上传报告、wheel、SBOM | MIT | 写入工作流制品 | 2026-11-05 |
| actions/download-artifact | action | v8.0.2@9000827ccba6bdab643e8b6fd33ac0654aef8333 | 发布作业取回构建产物，使构建与持有发布凭据的作业分开 | MIT | 读取本次运行的工作流制品 | 2026-11-05 |
| pypa/gh-action-pypi-publish | action | v1.14.3@7245906fb61fa33a13554f9d5fb856fe61758086 | 发布到 PyPI（Trusted Publishing，附来源证明） | BSD-3-Clause | 使用 OIDC 令牌，仅在 `pypi` 环境中运行 | 2026-11-05 |

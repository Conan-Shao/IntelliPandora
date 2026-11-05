# 安全报告

> 本页由 `scripts/security_report.py` 生成。每个 PR、每次合入 main、以及每天定时都会扫描一次（[`security.yml`](https://github.com/Conan-Shao/IntelliPandora/actions/workflows/security.yml)）。
> 只有结论变化时才会更新本页，所以下面的日期是**状态最近一次变化的日期**，不是最近一次扫描的日期。最近一次扫描的结果见 [Actions](https://github.com/Conan-Shao/IntelliPandora/actions/workflows/security.yml)。
>
> 组件如何准入见 [`docs/design/15`](../design/15-第三方组件安全准入与漏洞扫描.md)，已准入的组件见 [组件登记表](components.md)，已登记的漏洞例外见 [例外登记](exceptions.md)。

状态日期：2026-11-05

## 结论

| 检查 | 范围 | 结果 |
|---|---|---|
| 依赖漏洞 | `requirements/ci.txt`：框架 + 全部可选组（ai、mcp、system、test） | 通过：51 个包，0 个已知漏洞 |
| 依赖漏洞 | `requirements/ci-noai.txt`：框架 + mcp、test，不含 AI 组 | 通过：43 个包，0 个已知漏洞 |
| 依赖漏洞 | `requirements/tools.txt`：构建与工具链（不安装到用户环境） | 通过：58 个包，0 个已知漏洞 |
| 自身代码 | `src/`，bandit 静态扫描 | 通过：0 个未处理问题，10 处经评估标注（理由见下） |
| 许可证 | 运行环境 52 个分发包、工具链 58 个（含间接依赖） | 通过：全部在白名单内 |
| 组件登记 | 24 个直接依赖与 CI 动作 | 通过：与代码声明一致 |
| 漏洞例外 | 例外登记表 | 通过：0 条 |

## 漏洞明细

无。所有锁定版本均没有已公开的漏洞。

## 自身代码的标注

bandit 报出、经评估不构成问题的地方，在源码里标注 `# nosec` 并在上一行写明理由。没有理由的标注会让扫描失败。

| 规则 | 文件 | 理由 |
|---|---|---|
| B105 | `src/ipandora/core/report/model.py` | a status name, not a password |
| B110 | `src/ipandora/core/assertion/collector.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/evidence/recorder.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/evidence/recorder.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/protocol/http/model/data/responseobject.py` | evidence capture must never fail a request |
| B110 | `src/ipandora/core/protocol/http/model/data/responseobject.py` | evidence capture must never fail a request |
| B311 | `src/ipandora/utils/variable.py` | test data |
| B311 | `src/ipandora/utils/variable.py` | test data, not a secret |
| B405 | `src/ipandora/core/report/junit.py` | this module builds XML and never parses it |
| B704 | `src/ipandora/core/report/render.py` | all text went through html.escape; only our own span tags are raw |

## 许可证

白名单为宽松许可证（MIT、BSD、Apache、ISC、MPL-2.0、PSF 等），不接受 GPL 系、SSPL、BUSL 等，理由见 [`docs/design/15`](../design/15-第三方组件安全准入与漏洞扫描.md) §3。

<details><summary>运行环境（框架 + 全部可选组，即用户可能装上的全部）：52 个</summary>

| 分发包 | 版本 | 许可证 | 结果 |
|---|---|---|---|
| annotated-types | 0.8.0 | MIT | 通过 |
| anthropic | 0.125.0 | MIT License | 通过 |
| anyio | 4.15.1 | MIT | 通过 |
| attrs | 26.1.0 | MIT | 通过 |
| certifi | 2026.10.19 | Mozilla Public License 2.0 (MPL 2.0) | 通过 |
| cffi | 2.1.1 | MIT-0 | 通过 |
| charset-normalizer | 3.5.2 | MIT | 通过 |
| click | 8.5.0 | BSD-3-Clause | 通过 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | 通过 |
| distro | 1.9.0 | Apache Software License | 通过 |
| docstring-parser | 0.18.0 | MIT License | 通过 |
| h11 | 0.16.0 | MIT License | 通过 |
| httpcore | 1.0.9 | BSD-3-Clause | 通过 |
| httpcore2 | 2.16.0 | BSD-3-Clause | 通过 |
| httpretty | 1.1.4 | MIT License | 通过 |
| httpx | 0.28.1 | BSD License | 通过 |
| httpx2 | 2.16.0 | BSD-3-Clause | 通过 |
| idna | 3.20 | BSD-3-Clause | 通过 |
| iniconfig | 2.3.1 | MIT | 通过 |
| intellipandora | 1.11.0 | Apache-2.0 | 通过 |
| jinja2 | 3.1.6 | BSD License | 通过 |
| jiter | 0.17.0 | MIT | 通过 |
| jsonschema | 4.26.0 | MIT | 通过 |
| jsonschema-specifications | 2025.9.1 | MIT | 通过 |
| markupsafe | 3.0.4 | BSD-3-Clause | 通过 |
| mcp | 2.3.0 | MIT License | 通过 |
| mcp-types | 2.3.0 | MIT License | 通过 |
| opentelemetry-api | 1.45.1 | Apache-2.0 | 通过 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 通过 |
| pluggy | 1.7.0 | MIT License | 通过 |
| psutil | 7.2.2 | BSD-3-Clause | 通过 |
| pycparser | 3.12 | BSD-3-Clause | 通过 |
| pydantic | 2.14.1 | MIT | 通过 |
| pydantic-core | 2.50.1 | MIT | 通过 |
| pygments | 2.21.0 | BSD-2-Clause | 通过 |
| pyjwt | 2.15.1 | MIT | 通过 |
| pytest | 9.1.1 | MIT | 通过 |
| python-multipart | 0.0.32 | Apache-2.0 | 通过 |
| pyyaml | 6.0.3 | MIT License | 通过 |
| referencing | 0.37.0 | MIT | 通过 |
| requests | 2.34.2 | Apache Software License | 通过 |
| rpds-py | 2026.9.1 | MIT | 通过 |
| setuptools | 84.2.1 | MIT | 通过 |
| sniffio | 1.3.1 | MIT License / Apache Software License | 通过 |
| sse-starlette | 3.5.0 | BSD-3-Clause | 通过 |
| starlette | 1.9.0 | BSD-3-Clause | 通过 |
| truststore | 0.10.5 | MIT | 通过 |
| typing-extensions | 4.16.0 | PSF-2.0 | 通过 |
| typing-inspection | 0.4.4 | MIT | 通过 |
| urllib3 | 2.8.0 | MIT | 通过 |
| uvicorn | 0.54.0 | BSD-3-Clause | 通过 |
| wheel | 0.48.0 | MIT | 通过 |

</details>

<details><summary>构建与工具链：58 个</summary>

| 分发包 | 版本 | 许可证 | 结果 |
|---|---|---|---|
| arrow | 1.4.0 | Apache Software License | 通过 |
| attrs | 26.1.0 | MIT | 通过 |
| bandit | 1.9.4 | Apache-2.0 | 通过 |
| boolean-py | 5.0 | BSD-2-Clause | 通过 |
| build | 1.6.1 | MIT | 通过 |
| cachecontrol | 0.14.4 | Apache-2.0 | 通过 |
| certifi | 2026.10.19 | Mozilla Public License 2.0 (MPL 2.0) | 通过 |
| chardet | 7.7.0 | 0BSD | 通过 |
| charset-normalizer | 3.5.2 | MIT | 通过 |
| cyclonedx-bom | 7.5.0 | Apache Software License | 通过 |
| cyclonedx-python-lib | 11.12.0 | Apache Software License | 通过 |
| defusedxml | 0.7.1 | Python Software Foundation License | 通过 |
| filelock | 4.2.4 | MIT | 通过 |
| fqdn | 1.6.0 | MPL-2.0 | 通过 |
| idna | 3.20 | BSD-3-Clause | 通过 |
| isoduration | 20.11.0 | ISC License (ISCL) | 通过 |
| jsonpointer | 3.4 | BSD License | 通过 |
| jsonschema | 4.26.0 | MIT | 通过 |
| jsonschema-specifications | 2025.9.1 | MIT | 通过 |
| lark | 1.3.1 | MIT License | 通过 |
| license-expression | 30.4.4 | Apache-2.0 | 通过 |
| lxml | 6.1.3 | BSD-3-Clause | 通过 |
| markdown-it-py | 4.2.0 | MIT License | 通过 |
| mdurl | 0.1.2 | MIT License | 通过 |
| msgpack | 1.2.3 | Apache-2.0 | 通过 |
| packageurl-python | 0.17.6 | MIT License | 通过 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 通过 |
| pip | 26.2.2 | MIT | 通过 |
| pip-api | 0.0.35 | Apache Software License | 通过 |
| pip-audit | 2.10.1 | Apache Software License | 通过 |
| pip-requirements-parser | 32.0.1 | MIT | 通过 |
| platformdirs | 4.13.5 | MIT | 通过 |
| py-serializable | 2.1.0 | Apache Software License | 通过 |
| pygments | 2.21.0 | BSD-2-Clause | 通过 |
| pyparsing | 3.3.3 | MIT | 通过 |
| pyproject-hooks | 1.3.3 | MIT | 通过 |
| python-dateutil | 3.0.0 | BSD License / Apache Software License | 通过 |
| pyyaml | 6.0.3 | MIT License | 通过 |
| referencing | 0.37.0 | MIT | 通过 |
| requests | 2.34.2 | Apache Software License | 通过 |
| rfc3339-validator | 0.1.4 | MIT License | 通过 |
| rfc3986-validator | 0.1.1 | MIT License | 通过 |
| rfc3987-syntax | 1.1.0 | MIT | 通过 |
| rich | 15.0.0 | MIT License | 通过 |
| rpds-py | 2026.9.1 | MIT | 通过 |
| setuptools | 84.2.1 | MIT | 通过 |
| six | 1.17.0 | MIT License | 通过 |
| sortedcontainers | 2.4.0 | Apache Software License | 通过 |
| stevedore | 5.9.1 | Apache-2.0 | 通过 |
| tomli | 2.5.0 | MIT | 通过 |
| tomli-w | 1.2.0 | MIT License | 通过 |
| typing-extensions | 4.16.0 | PSF-2.0 | 通过 |
| tzdata | 2026.5 | Apache-2.0 | 通过 |
| uri-template | 1.3.0 | MIT License | 通过 |
| urllib3 | 2.8.0 | MIT | 通过 |
| uv | 0.13.5 | MIT OR Apache-2.0 | 通过 |
| webcolors | 25.10.0 | BSD License | 通过 |
| wheel | 0.48.0 | MIT | 通过 |

</details>

## 怎么扫的

- **依赖漏洞**：pip-audit 2.10.1，对每个锁文件逐一扫描，查询 PyPI 漏洞库。扫的是锁文件本身（`--require-hashes`），也就是 CI 实际安装的每一个文件，而不是某台机器上碰巧装着的版本。
- **自身代码**：bandit 1.9.4，扫描 `src/` 下全部代码，任何级别的问题都会让扫描失败。
- **许可证**：读取环境中每个分发包的元数据，包括间接依赖，因为它们同样会被装到用户环境。
- **组件登记**：`setup.cfg`、`setup.py`、`requirements/*.in` 和工作流里引用的每个组件，都必须在登记表里出现且版本写法一致。
- **新版本冷静期**：锁文件只接受发布满 14 天的版本（`scripts/update_locks.py`），恶意版本通常在几天内就会被发现并撤下。

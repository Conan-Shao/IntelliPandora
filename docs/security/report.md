# 安全报告

> 本页由 `scripts/security_report.py` 生成。每个 PR、每次合入 main、以及每天定时都会扫描一次（[`security.yml`](https://github.com/Conan-Shao/IntelliPandora/actions/workflows/security.yml)）。
> 只有结论变化时才会更新本页，所以下面的日期是**状态最近一次变化的日期**，不是最近一次扫描的日期。最近一次扫描的结果见 [Actions](https://github.com/Conan-Shao/IntelliPandora/actions/workflows/security.yml)。
>
> 组件如何准入见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md)，已准入的组件见 [组件登记表](components.md)，已登记的漏洞例外见 [例外登记](exceptions.md)。

状态日期：2026-11-07

## 结论

| 检查 | 范围 | 结果 |
|---|---|---|
| 依赖漏洞 | `requirements/ci.txt`：框架 + 可选组 ai、android、inspect、mcp、parallel、system、test、visual、web | 通过：119 个包，0 个已知漏洞 |
| 依赖漏洞 | `requirements/ci-noai.txt`：框架 + 可选组 android、mcp、parallel、test、visual、web，不含 AI 组 | 通过：60 个包，0 个已知漏洞 |
| 依赖漏洞 | `requirements/tools.txt`：构建与工具链（不安装到用户环境） | 通过：69 个包，0 个已知漏洞 |
| 自身代码 | `src/`，bandit 静态扫描 | 通过：0 个未处理问题，28 处经评估标注（理由见下） |
| 许可证 | 运行环境 121 个分发包、工具链 72 个（含间接依赖） | 通过：其余在白名单内，text-unidecode 经人工审查（见下） |
| 组件登记 | 33 个直接依赖与 CI 动作 | 通过：与代码声明一致 |
| 漏洞例外 | 例外登记表 | 通过：0 条 |

## 漏洞明细

无。所有锁定版本均没有已公开的漏洞。

## 自身代码的标注

bandit 报出、经评估不构成问题的地方，在源码里标注 `# nosec` 并在上一行写明理由。没有理由的标注会让扫描失败。

| 规则 | 文件 | 理由 |
|---|---|---|
| B105 | `src/ipandora/core/report/model.py` | a status name, not a password |
| B105 | `src/ipandora/core/report/model.py` | a verdict name, not a password |
| B110 | `src/ipandora/core/assertion/collector.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/evidence/recorder.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/evidence/recorder.py` | reporting must never fail a test |
| B110 | `src/ipandora/core/protocol/http/model/data/responseobject.py` | evidence capture must never fail a request |
| B110 | `src/ipandora/core/protocol/http/model/data/responseobject.py` | evidence capture must never fail a request |
| B110 | `src/ipandora/core/runner/plugin.py` | a lock that will not release must not turn a result red; the process exit frees it |
| B311 | `src/ipandora/core/eval/annotate.py` | sampling rows for people to label, not secrecy |
| B311 | `src/ipandora/core/eval/stats.py` | resampling for a confidence interval, not secrecy |
| B311 | `src/ipandora/core/eval/stats.py` | resampling for a confidence interval, not secrecy |
| B311 | `src/ipandora/core/eval/stats.py` | resampling for a confidence interval, not secrecy |
| B311 | `src/ipandora/utils/variable.py` | test data |
| B311 | `src/ipandora/utils/variable.py` | test data, not a secret |
| B314 | `src/ipandora/core/android.py` | expat resolves no external entities, and Python's expat limits entity expansion |
| B404 | `src/ipandora/core/consistency.py` | the checker is a Java tool run as a child process, never through a shell |
| B404 | `src/ipandora/core/eval/coding.py` | the graders run git and the agent's tests as child processes, never through a shell |
| B404 | `src/ipandora/core/eval/testgen.py` | pytest and git, run in the work directory with argument lists, never a shell |
| B404 | `src/ipandora/core/stack.py` | Docker Compose is run as a child process, never through a shell |
| B405 | `src/ipandora/core/android.py` | the tree comes from the uiautomator server on the device under test, not from a user |
| B405 | `src/ipandora/core/report/junit.py` | this module builds XML and never parses it |
| B603 | `src/ipandora/core/consistency.py` | a java executable we located, asking its version; no shell |
| B603 | `src/ipandora/core/consistency.py` | the verified checker jar, our own arguments and file; no shell |
| B603 | `src/ipandora/core/eval/coding.py` | a fixed argument list with the git found on PATH; no shell |
| B603 | `src/ipandora/core/eval/coding.py` | this interpreter, our own script, the grader's own arguments; no shell |
| B603 | `src/ipandora/core/eval/testgen.py` | the task's own test command, split without a shell, in its work directory |
| B603 | `src/ipandora/core/stack.py` | docker, located by full path; arguments are ours, no shell |
| B704 | `src/ipandora/core/report/render.py` | all text went through html.escape; only our own span tags are raw |

## 许可证

白名单为宽松许可证（MIT、BSD、Apache、ISC、MPL-2.0、PSF 等），不接受 GPL 系、SSPL、BUSL 等，理由见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md) §3。

<details><summary>运行环境（框架 + 全部可选组，即用户可能装上的全部）：121 个</summary>

| 分发包 | 版本 | 许可证 | 结果 |
|---|---|---|---|
| adbutils | 2.12.0 | MIT | 通过 |
| agent-client-protocol | 0.12.1 | Apache-2.0 | 通过 |
| aiobotocore | 3.9.2 | Apache-2.0 | 通过 |
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License | 通过 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | 通过 |
| aioitertools | 0.13.0 | MIT | 通过 |
| aiosignal | 1.4.0 | Apache Software License | 通过 |
| annotated-doc | 0.0.5 | MIT | 通过 |
| annotated-types | 0.8.0 | MIT | 通过 |
| anthropic | 2.1.0 | Apache Software License | 通过 |
| anyio | 4.15.1 | MIT | 通过 |
| attrs | 26.1.0 | MIT | 通过 |
| beautifulsoup4 | 4.15.0 | MIT License | 通过 |
| boto3 | 1.43.106 | Apache-2.0 | 通过 |
| botocore | 1.43.106 | Apache-2.0 | 通过 |
| certifi | 2026.10.19 | Mozilla Public License 2.0 (MPL 2.0) | 通过 |
| cffi | 2.1.1 | MIT-0 | 通过 |
| charset-normalizer | 3.5.2 | MIT | 通过 |
| click | 8.5.0 | BSD-3-Clause | 通过 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | 通过 |
| debugpy | 1.8.22 | MIT License | 通过 |
| decorator | 5.3.1 | BSD-2-Clause | 通过 |
| deprecation | 2.1.0 | Apache Software License | 通过 |
| docstring-parser | 0.18.0 | MIT License | 通过 |
| execnet | 2.1.2 | MIT | 通过 |
| fastapi | 0.161.1 | MIT | 通过 |
| frozenlist | 1.8.0 | Apache-2.0 | 通过 |
| fsspec | 2026.6.0 | BSD-3-Clause | 通过 |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | 通过 |
| h11 | 0.16.0 | MIT License | 通过 |
| httpcore | 1.0.9 | BSD-3-Clause | 通过 |
| httpcore2 | 2.16.0 | BSD-3-Clause | 通过 |
| httpretty | 1.1.4 | MIT License | 通过 |
| httpx | 0.28.1 | BSD License | 通过 |
| httpx2 | 2.16.0 | BSD-3-Clause | 通过 |
| idna | 3.20 | BSD-3-Clause | 通过 |
| ijson | 3.6.0 | BSD-3-Clause AND ISC | 通过 |
| iniconfig | 2.3.1 | MIT | 通过 |
| inspect-ai | 0.3.283 | MIT License | 通过 |
| intellipandora | 1.11.0 | Apache-2.0 | 通过 |
| jinja2 | 3.1.6 | BSD License | 通过 |
| jiter | 0.17.0 | MIT | 通过 |
| jmespath | 1.1.0 | MIT License | 通过 |
| jsonlines | 4.0.0 | BSD License | 通过 |
| jsonpatch | 1.36 | BSD-3-Clause | 通过 |
| jsonpath-ng | 1.12.0 | Apache-2.0 | 通过 |
| jsonpointer | 3.4 | BSD License | 通过 |
| jsonref | 1.1.0 | MIT | 通过 |
| jsonschema | 4.26.0 | MIT | 通过 |
| jsonschema-specifications | 2025.9.1 | MIT | 通过 |
| linkify-it-py | 2.2.0 | MIT License | 通过 |
| lxml | 6.1.3 | BSD-3-Clause | 通过 |
| markdown-it-py | 4.2.0 | MIT License | 通过 |
| markupsafe | 3.0.4 | BSD-3-Clause | 通过 |
| mcp | 2.3.0 | MIT License | 通过 |
| mcp-types | 2.3.0 | MIT License | 通过 |
| mdit-py-plugins | 0.6.1 | MIT License | 通过 |
| mdurl | 0.1.2 | MIT License | 通过 |
| mmh3 | 5.3.1 | MIT License | 通过 |
| multidict | 6.9.1 | Apache License 2.0 | 通过 |
| nest-asyncio2 | 1.7.4 | BSD License | 通过 |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 通过 |
| opentelemetry-api | 1.45.1 | Apache-2.0 | 通过 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 通过 |
| pathlib-abc | 0.5.2 | Python Software Foundation License | 通过 |
| pillow | 13.0.0 | MIT-CMU | 通过 |
| pixelmatch | 0.4.0 | ISC | 通过 |
| platformdirs | 4.13.5 | MIT | 通过 |
| playwright | 1.64.0 | Apache-2.0 | 通过 |
| pluggy | 1.7.0 | MIT License | 通过 |
| propcache | 0.5.4 | Apache-2.0 | 通过 |
| psutil | 7.2.2 | BSD-3-Clause | 通过 |
| pycparser | 3.11 | BSD-3-Clause | 通过 |
| pydantic | 2.14.1 | MIT | 通过 |
| pydantic-core | 2.50.1 | MIT | 通过 |
| pyee | 13.0.1 | MIT License | 通过 |
| pygments | 2.21.0 | BSD-2-Clause | 通过 |
| pyjwt | 2.15.1 | MIT | 通过 |
| pytest | 9.1.1 | MIT | 通过 |
| pytest-playwright | 0.10.0 | Apache Software License | 通过 |
| pytest-timeout | 2.4.0 | DFSG approved / MIT License | 通过 |
| pytest-xdist | 3.8.0 | MIT | 通过 |
| python-dateutil | 2.9.0.post0 | BSD License / Apache Software License | 通过 |
| python-dotenv | 1.2.4 | BSD-3-Clause | 通过 |
| python-multipart | 0.0.32 | Apache-2.0 | 通过 |
| python-slugify | 9.1.3 | MIT | 通过 |
| pyyaml | 6.0.3 | MIT License | 通过 |
| referencing | 0.37.0 | MIT | 通过 |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | 通过 |
| requests | 2.34.2 | Apache Software License | 通过 |
| retry2 | 0.9.5 | Apache Software License | 通过 |
| rich | 15.0.0 | MIT License | 通过 |
| rpds-py | 2026.9.1 | MIT | 通过 |
| s3fs | 2026.6.0 | BSD License | 通过 |
| s3transfer | 0.19.3 | Apache Software License | 通过 |
| semver | 3.1.0 | BSD License | 通过 |
| setuptools | 84.2.1 | MIT | 通过 |
| shortuuid | 1.0.13 | BSD License | 通过 |
| six | 1.17.0 | MIT License | 通过 |
| sniffio | 1.3.1 | MIT License / Apache Software License | 通过 |
| soupsieve | 3.0.4 | MIT | 通过 |
| sse-starlette | 3.5.0 | BSD-3-Clause | 通过 |
| starlette | 1.9.0 | BSD-3-Clause | 通过 |
| tenacity | 9.2.1 | Apache-2.0 | 通过 |
| text-unidecode | 1.3 | Artistic-1.0 OR GPL-2.0-or-later (used under Artistic-1.0) | 通过（人工审查：only with the optional [web] group, via pytest-playwright -&gt; python-slugify, which uses it to transliterate test ids into artifact folder names. Dual licensed; we take the Artistic License, not the GPL. Reviewed 2026-11-05） |
| textual | 8.2.8 | MIT License | 通过 |
| tiktoken | 0.14.0 | MIT License | 通过 |
| tomli | 2.5.0 | MIT | 通过 |
| truststore | 0.10.5 | MIT | 通过 |
| typing-extensions | 4.16.0 | PSF-2.0 | 通过 |
| typing-inspection | 0.4.4 | MIT | 通过 |
| uiautomator2 | 3.7.1 | MIT License | 通过 |
| universal-pathlib | 0.3.10 | MIT | 通过 |
| urllib3 | 2.8.0 | MIT | 通过 |
| uvicorn | 0.54.0 | BSD-3-Clause | 通过 |
| wheel | 0.48.0 | MIT | 通过 |
| wrapt | 2.5.1 | BSD-2-Clause | 通过 |
| yarl | 1.25.1 | Apache-2.0 | 通过 |
| zipfile-zstd | 0.0.4 | MIT License | 通过 |
| zipp | 4.1.2 | MIT | 通过 |
| zstandard | 0.25.0 | BSD-3-Clause | 通过 |

</details>

<details><summary>构建与工具链：72 个</summary>

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
| click | 8.5.0 | BSD-3-Clause | 通过 |
| coverage | 7.17.0 | Apache-2.0 | 通过 |
| cyclonedx-bom | 7.5.0 | Apache Software License | 通过 |
| cyclonedx-python-lib | 11.12.0 | Apache Software License | 通过 |
| defusedxml | 0.7.1 | Python Software Foundation License | 通过 |
| filelock | 4.2.4 | MIT | 通过 |
| fqdn | 1.6.0 | MPL-2.0 | 通过 |
| idna | 3.20 | BSD-3-Clause | 通过 |
| importlib-metadata | 10.1.0 | Apache-2.0 | 通过 |
| iniconfig | 2.3.1 | MIT | 通过 |
| intellipandora | 1.11.0 | Apache-2.0 | 通过 |
| isoduration | 20.11.0 | ISC License (ISCL) | 通过 |
| jsonpointer | 3.4 | BSD License | 通过 |
| jsonschema | 4.26.0 | MIT | 通过 |
| jsonschema-specifications | 2025.9.1 | MIT | 通过 |
| lark | 1.3.1 | MIT License | 通过 |
| libcst | 1.9.0 | MIT License | 通过 |
| license-expression | 30.4.4 | Apache-2.0 | 通过 |
| linkify-it-py | 2.2.0 | MIT License | 通过 |
| lxml | 6.1.3 | BSD-3-Clause | 通过 |
| markdown-it-py | 4.2.0 | MIT License | 通过 |
| mdit-py-plugins | 0.6.1 | MIT License | 通过 |
| mdurl | 0.1.2 | MIT License | 通过 |
| msgpack | 1.2.3 | Apache-2.0 | 通过 |
| mutmut | 3.8.0 | BSD-3-Clause | 通过 |
| packageurl-python | 0.17.6 | MIT License | 通过 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 通过 |
| pip | 26.2.2 | MIT | 通过 |
| pip-api | 0.0.35 | Apache Software License | 通过 |
| pip-audit | 2.10.1 | Apache Software License | 通过 |
| pip-requirements-parser | 32.0.1 | MIT | 通过 |
| platformdirs | 4.13.5 | MIT | 通过 |
| pluggy | 1.7.0 | MIT License | 通过 |
| py-serializable | 2.1.0 | Apache Software License | 通过 |
| pygments | 2.21.0 | BSD-2-Clause | 通过 |
| pyparsing | 3.3.3 | MIT | 通过 |
| pyproject-hooks | 1.3.3 | MIT | 通过 |
| pytest | 9.1.1 | MIT | 通过 |
| python-dateutil | 2.9.0.post0 | BSD License / Apache Software License | 通过 |
| pyyaml | 6.0.3 | MIT License | 通过 |
| referencing | 0.37.0 | MIT | 通过 |
| requests | 2.34.2 | Apache Software License | 通过 |
| rfc3339-validator | 0.1.4 | MIT License | 通过 |
| rfc3986-validator | 0.1.1 | MIT License | 通过 |
| rfc3987-syntax | 1.1.0 | MIT | 通过 |
| rich | 15.0.0 | MIT License | 通过 |
| rpds-py | 2026.9.1 | MIT | 通过 |
| setproctitle | 1.3.8 | BSD-3-Clause | 通过 |
| setuptools | 84.2.1 | MIT | 通过 |
| six | 1.17.0 | MIT License | 通过 |
| sortedcontainers | 2.4.0 | Apache Software License | 通过 |
| stevedore | 5.9.1 | Apache-2.0 | 通过 |
| textual | 8.2.8 | MIT License | 通过 |
| tomli | 2.5.0 | MIT | 通过 |
| tomli-w | 1.2.0 | MIT License | 通过 |
| typing-extensions | 4.16.0 | PSF-2.0 | 通过 |
| tzdata | 2026.5 | Apache-2.0 | 通过 |
| uri-template | 1.3.0 | MIT License | 通过 |
| urllib3 | 2.8.0 | MIT | 通过 |
| uv | 0.13.4 | MIT OR Apache-2.0 | 通过 |
| webcolors | 25.10.0 | BSD License | 通过 |
| wheel | 0.48.0 | MIT | 通过 |
| zipp | 4.1.2 | MIT | 通过 |

</details>

## 怎么扫的

- **依赖漏洞**：pip-audit 2.10.1，对每个锁文件逐一扫描，查询 PyPI 漏洞库。扫的是锁文件本身（`--require-hashes`），也就是 CI 实际安装的每一个文件，而不是某台机器上碰巧装着的版本。
- **自身代码**：bandit 1.9.4，扫描 `src/` 下全部代码，任何级别的问题都会让扫描失败。
- **许可证**：读取环境中每个分发包的元数据，包括间接依赖，因为它们同样会被装到用户环境。
- **组件登记**：`setup.cfg`、`setup.py`、`requirements/*.in` 和工作流里引用的每个组件，都必须在登记表里出现且版本写法一致。
- **新版本冷静期**：锁文件只接受发布满 14 天的版本（`scripts/update_locks.py`），恶意版本通常在几天内就会被发现并撤下。

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
| 依赖漏洞 | `requirements/bench.txt`：Android 对比作业专用：框架的 android 组 + Appium 客户端（不安装到用户环境） | 通过：43 个包，0 个已知漏洞 |
| 依赖漏洞 | `bench/android/package-lock.json`：Android 对比作业专用：Appium 服务端与 UiAutomator2 驱动（npm，不安装到用户环境） | 通过：286 个包，2 个已知漏洞（均已登记例外） |
| 自身代码 | `src/`，bandit 静态扫描 | 通过：0 个未处理问题，32 处经评估标注（理由见下） |
| 许可证 | 运行环境 120 个分发包、工具链与对比作业 113 个（含间接依赖） | 通过：其余在白名单内，text-unidecode 经人工审查（见下） |
| npm 锁文件 | 286 个包（含间接依赖）：哈希、来源、许可证 | 通过：全部来自 npm 官方仓库、带 sha512；许可证在白名单内，BlueOak-1.0.0、CC-BY-3.0、MIT or GPL-2.0、WTFPL 经人工审查（见下） |
| 组件登记 | 37 个直接依赖与 CI 动作 | 通过：与代码声明一致 |
| 漏洞例外 | 例外登记表 | 通过：2 条 |

## 漏洞明细

| 编号 | 组件 | 版本 | 修复版本 | 锁文件 | 处理 |
|---|---|---|---|---|---|
| GHSA-3g3m-2fjr-6pw4 | glob | 13.0.6 | 不在 >=9.0.0 <=14.0.1 内的版本 | `bench/android/package-lock.json` | 已登记例外，2026-12-07 到期：只在 Android 对比作业（`android-bench.yml`）里用到，不随框架分发。漏洞是传入的 AbortSignal 超时后遍历不停；Appium 只用自己代码里写死的模式查找本机文件，不接收外部模式，也不在 CI 上以不可信输入调用。驱动包内那一份是打包进去的，覆盖不到，要等 8.x 出新版。2026-11-07 评估 |
| GHSA-g3hv-75wg-m249 | minimatch | 10.2.6 | 不在 >=7.0.0 <11.0.1 内的版本 | `bench/android/package-lock.json` | 已登记例外，2026-12-07 到期：同上。拒绝服务要攻击者能控制匹配模式；Appium 服务只监听 `127.0.0.1`，存活于一次 CI 作业，只接收我们自己脚本的命令。2026-11-07 评估 |

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
| B404 | `src/ipandora/core/chaosmesh.py` | kubectl runs as a list of arguments, never through a shell (_kubectl) |
| B404 | `src/ipandora/core/consistency.py` | the checker is a Java tool run as a child process, never through a shell |
| B404 | `src/ipandora/core/eval/coding.py` | the graders run git and the agent's tests as child processes, never through a shell |
| B404 | `src/ipandora/core/eval/testgen.py` | pytest and git, run in the work directory with argument lists, never a shell |
| B404 | `src/ipandora/core/netem.py` | docker runs as a list of arguments, never through a shell (_docker) |
| B404 | `src/ipandora/core/stack.py` | Docker Compose is run as a child process, never through a shell |
| B405 | `src/ipandora/core/android.py` | the tree comes from the uiautomator server on the device under test, not from a user |
| B405 | `src/ipandora/core/report/junit.py` | this module builds XML and never parses it |
| B603 | `src/ipandora/core/chaosmesh.py` | a list of arguments, no shell; the executable is kubectl, resolved on PATH or configured |
| B603 | `src/ipandora/core/consistency.py` | a java executable we located, asking its version; no shell |
| B603 | `src/ipandora/core/consistency.py` | the verified checker jar, our own arguments and file; no shell |
| B603 | `src/ipandora/core/eval/coding.py` | a fixed argument list with the git found on PATH; no shell |
| B603 | `src/ipandora/core/eval/coding.py` | this interpreter, our own script, the grader's own arguments; no shell |
| B603 | `src/ipandora/core/eval/testgen.py` | the task's own test command, split without a shell, in its work directory |
| B603 | `src/ipandora/core/netem.py` | a list of arguments, no shell; the executable is docker, resolved on PATH or configured |
| B603 | `src/ipandora/core/stack.py` | docker, located by full path; arguments are ours, no shell |
| B704 | `src/ipandora/core/report/render.py` | all text went through html.escape; only our own span tags are raw |

## 许可证

白名单为宽松许可证（MIT、BSD、Apache、ISC、MPL-2.0、PSF 等），不接受 GPL 系、SSPL、BUSL 等，理由见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md) §3。

<details><summary>运行环境（框架 + 全部可选组，即用户可能装上的全部）：120 个</summary>

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
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 通过 |
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
| pyee | 14.0.0 | MIT License | 通过 |
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

<details><summary>构建与工具链：69 个</summary>

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
| iniconfig | 2.3.1 | MIT | 通过 |
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
| python-dateutil | 3.0.0 | BSD License / Apache Software License | 通过 |
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

</details>

<details><summary>Android 对比作业专用（Python）：44 个</summary>

| 分发包 | 版本 | 许可证 | 结果 |
|---|---|---|---|
| adbutils | 2.12.0 | MIT | 通过 |
| appium-python-client | 6.0.8 | Apache-2.0 | 通过 |
| attrs | 26.1.0 | MIT | 通过 |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) | 通过 |
| cffi | 2.1.1 | MIT-0 | 通过 |
| charset-normalizer | 3.5.2 | MIT | 通过 |
| click | 8.5.0 | BSD-3-Clause | 通过 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | 通过 |
| decorator | 5.3.1 | BSD-2-Clause | 通过 |
| deprecation | 2.1.0 | Apache Software License | 通过 |
| h11 | 0.16.0 | MIT License | 通过 |
| idna | 3.20 | BSD-3-Clause | 通过 |
| iniconfig | 2.3.1 | MIT | 通过 |
| intellipandora | 1.11.0 | Apache-2.0 | 通过 |
| jinja2 | 3.1.6 | BSD License | 通过 |
| jsonschema | 4.26.0 | MIT | 通过 |
| jsonschema-specifications | 2025.9.1 | MIT | 通过 |
| lxml | 6.1.3 | BSD-3-Clause | 通过 |
| markupsafe | 3.0.4 | BSD-3-Clause | 通过 |
| outcome | 1.3.0.post0 | MIT License / Apache Software License | 通过 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 通过 |
| pillow | 13.0.0 | MIT-CMU | 通过 |
| pluggy | 1.7.0 | MIT License | 通过 |
| pycparser | 3.12 | BSD-3-Clause | 通过 |
| pygments | 2.21.0 | BSD-2-Clause | 通过 |
| pysocks | 1.7.1 | BSD | 通过 |
| pytest | 9.1.1 | MIT | 通过 |
| pyyaml | 6.0.3 | MIT License | 通过 |
| referencing | 0.37.0 | MIT | 通过 |
| requests | 2.34.2 | Apache Software License | 通过 |
| retry2 | 0.9.5 | Apache Software License | 通过 |
| rpds-py | 2026.9.1 | MIT | 通过 |
| selenium | 4.51.0 | Apache-2.0 | 通过 |
| setuptools | 84.2.1 | MIT | 通过 |
| sniffio | 1.3.1 | MIT License / Apache Software License | 通过 |
| sortedcontainers | 2.4.0 | Apache Software License | 通过 |
| trio | 0.34.0 | MIT OR Apache-2.0 | 通过 |
| trio-websocket | 0.12.2 | MIT License | 通过 |
| typing-extensions | 4.16.0 | PSF-2.0 | 通过 |
| uiautomator2 | 3.7.1 | MIT License | 通过 |
| urllib3 | 2.8.0 | MIT | 通过 |
| websocket-client | 1.9.2 | Apache-2.0 | 通过 |
| wheel | 0.48.0 | MIT | 通过 |
| wsproto | 1.3.2 | MIT | 通过 |

</details>

<details><summary>npm（Android 对比作业专用）：286 个</summary>

| 包 | 许可证 | 结果 |
|---|---|---|
| @appium/base-driver@10.8.2 | Apache-2.0 | 通过 |
| @appium/base-plugin@3.3.6 | Apache-2.0 | 通过 |
| @appium/css-locator-to-native@1.0.7 | Apache-2.0 | 通过 |
| @appium/docutils@3.0.2 | Apache-2.0 | 通过 |
| @appium/logger@2.0.12 | ISC | 通过 |
| @appium/schema@1.3.0 | Apache-2.0 | 通过 |
| @appium/support@7.2.9 | Apache-2.0 | 通过 |
| @appium/types@1.7.2 | Apache-2.0 | 通过 |
| @colors/colors@1.6.0 | MIT | 通过 |
| @colors/colors@1.6.1 | MIT | 通过 |
| @dabh/diagnostics@2.0.9 | MIT | 通过 |
| @sidvind/better-ajv-errors@5.0.0 | Apache-2.0 | 通过 |
| @so-ric/colorspace@1.1.6 | MIT | 通过 |
| @types/triple-beam@1.3.5 | MIT | 通过 |
| @xmldom/xmldom@0.9.12 | MIT | 通过 |
| abort-controller@3.0.0 | MIT | 通过 |
| accepts@2.0.0 | MIT | 通过 |
| agent-base@6.0.2 | MIT | 通过 |
| ajv-formats@3.0.1 | MIT | 通过 |
| ajv@8.20.0 | MIT | 通过 |
| ansi-regex@5.0.1 | MIT | 通过 |
| ansi-regex@6.4.0 | MIT | 通过 |
| ansi-styles@4.3.0 | MIT | 通过 |
| ansi-styles@6.2.3 | MIT | 通过 |
| appium-adb@16.1.2 | Apache-2.0 | 通过 |
| appium-android-driver@14.2.5 | Apache-2.0 | 通过 |
| appium-chromedriver@9.1.9 | Apache-2.0 | 通过 |
| appium-uiautomator2-driver@8.7.3 | Apache-2.0 | 通过 |
| appium-uiautomator2-server@10.7.6 | Apache-2.0 | 通过 |
| appium@3.9.0 | Apache-2.0 | 通过 |
| archiver@8.0.0 | MIT | 通过 |
| argparse@3.0.3 | PSF-2.0 | 通过 |
| async-lock@1.4.1 | MIT | 通过 |
| async@2.6.4 | MIT | 通过 |
| async@3.2.6 | MIT | 通过 |
| asyncbox@6.5.0 | Apache-2.0 | 通过 |
| asynckit@0.4.0 | MIT | 通过 |
| axios@1.20.0 | MIT | 通过 |
| axios@1.21.0 | MIT | 通过 |
| b4a@1.9.0 | Apache-2.0 | 通过 |
| balanced-match@4.0.4 | MIT | 通过 |
| bare-events@2.9.2 | Apache-2.0 | 通过 |
| bare-fs@4.8.4 | Apache-2.0 | 通过 |
| bare-path@3.1.2 | Apache-2.0 | 通过 |
| bare-stream@2.13.4 | Apache-2.0 | 通过 |
| bare-url@2.5.5 | Apache-2.0 | 通过 |
| base64-js@1.5.1 | MIT | 通过 |
| basic-auth@2.0.1 | MIT | 通过 |
| bl@4.1.0 | MIT | 通过 |
| bluebird@3.7.2 | MIT | 通过 |
| body-parser@2.4.0 | MIT | 通过 |
| bplist-creator@0.3.0 | MIT | 通过 |
| bplist-parser@0.5.0 | MIT | 通过 |
| brace-expansion@5.0.12 | MIT | 通过 |
| buffer-crc32@1.0.0 | MIT | 通过 |
| buffer@5.7.1 | MIT | 通过 |
| buffer@6.0.3 | MIT | 通过 |
| bytes@3.1.2 | MIT | 通过 |
| call-bind-apply-helpers@1.0.2 | MIT | 通过 |
| call-bound@1.0.4 | MIT | 通过 |
| chalk@4.1.2 | MIT | 通过 |
| cli-cursor@3.1.0 | MIT | 通过 |
| cli-spinners@2.9.2 | MIT | 通过 |
| cliui@9.0.1 | ISC | 通过 |
| clone@1.0.4 | MIT | 通过 |
| color-convert@2.0.1 | MIT | 通过 |
| color-convert@3.1.3 | MIT | 通过 |
| color-name@1.1.4 | MIT | 通过 |
| color-name@2.1.1 | MIT | 通过 |
| color-string@2.1.4 | MIT | 通过 |
| color@5.0.3 | MIT | 通过 |
| combined-stream@1.0.8 | MIT | 通过 |
| compare-versions@6.1.1 | MIT | 通过 |
| compress-commons@7.0.1 | MIT | 通过 |
| consola@3.4.2 | MIT | 通过 |
| content-disposition@1.1.0 | MIT | 通过 |
| content-type@1.0.5 | MIT | 通过 |
| content-type@2.1.0 | MIT | 通过 |
| cookie-signature@1.2.2 | MIT | 通过 |
| cookie@0.7.2 | MIT | 通过 |
| core-util-is@1.0.3 | MIT | 通过 |
| crc-32@1.2.2 | Apache-2.0 | 通过 |
| crc32-stream@7.0.1 | MIT | 通过 |
| css-selector-parser@3.3.0 | MIT | 通过 |
| dayjs@1.11.23 | MIT | 通过 |
| debug@2.6.9 | MIT | 通过 |
| debug@3.1.0 | MIT | 通过 |
| debug@3.2.7 | MIT | 通过 |
| debug@4.4.3 | MIT | 通过 |
| defaults@1.0.4 | MIT | 通过 |
| delayed-stream@1.0.0 | MIT | 通过 |
| depd@2.0.0 | MIT | 通过 |
| diff@9.0.0 | BSD-3-Clause | 通过 |
| dunder-proto@1.0.1 | MIT | 通过 |
| duplexer@0.1.2 | MIT | 通过 |
| ee-first@1.1.1 | MIT | 通过 |
| emoji-regex@10.6.0 | MIT | 通过 |
| enabled@2.0.0 | MIT | 通过 |
| encodeurl@2.0.0 | MIT | 通过 |
| encodeurl@2.0.1 | MIT | 通过 |
| es-define-property@1.0.1 | MIT | 通过 |
| es-errors@1.3.0 | MIT | 通过 |
| es-object-atoms@1.1.2 | MIT | 通过 |
| es-set-tostringtag@2.1.0 | MIT | 通过 |
| escalade@3.2.0 | MIT | 通过 |
| escape-html@1.0.3 | MIT | 通过 |
| etag@1.8.1 | MIT | 通过 |
| event-target-shim@5.0.1 | MIT | 通过 |
| events-universal@1.0.1 | Apache-2.0 | 通过 |
| events@3.3.0 | MIT | 通过 |
| express@5.2.1 | MIT | 通过 |
| fast-deep-equal@3.1.3 | MIT | 通过 |
| fast-fifo@1.3.2 | MIT | 通过 |
| fast-uri@3.1.9 | BSD-3-Clause | 通过 |
| fastest-levenshtein@1.0.16 | MIT | 通过 |
| fecha@4.2.3 | MIT | 通过 |
| finalhandler@2.1.1 | MIT | 通过 |
| fn.name@1.1.0 | MIT | 通过 |
| follow-redirects@1.16.2 | MIT | 通过 |
| form-data@4.0.6 | MIT | 通过 |
| forwarded@0.2.0 | MIT | 通过 |
| fresh@0.5.2 | MIT | 通过 |
| fresh@2.0.0 | MIT | 通过 |
| ftp-response-parser@1.0.1 | MIT | 通过 |
| function-bind@1.1.2 | MIT | 通过 |
| get-caller-file@2.0.5 | ISC | 通过 |
| get-east-asian-width@1.7.0 | MIT | 通过 |
| get-intrinsic@1.3.0 | MIT | 通过 |
| get-proto@1.0.1 | MIT | 通过 |
| glob@13.0.6 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| gopd@1.2.0 | MIT | 通过 |
| has-flag@4.0.0 | MIT | 通过 |
| has-symbols@1.1.0 | MIT | 通过 |
| has-tostringtag@1.0.2 | MIT | 通过 |
| hasown@2.0.4 | MIT | 通过 |
| hosted-git-info@9.0.3 | ISC | 通过 |
| http-errors@2.0.1 | MIT | 通过 |
| http-status-codes@2.3.0 | MIT | 通过 |
| https-proxy-agent@5.0.1 | MIT | 通过 |
| iconv-lite@0.7.3 | MIT | 通过 |
| ieee754@1.2.1 | BSD-3-Clause | 通过 |
| inherits@2.0.4 | ISC | 通过 |
| ini@6.0.0 | ISC | 通过 |
| io.appium.settings@8.4.5 | Apache-2.0 | 通过 |
| ipaddr.js@1.9.1 | MIT | 通过 |
| is-interactive@1.0.0 | MIT | 通过 |
| is-number-like@1.0.8 | ISC | 通过 |
| is-promise@4.0.0 | MIT | 通过 |
| is-stream@2.0.1 | MIT | 通过 |
| is-stream@4.0.1 | MIT | 通过 |
| is-unicode-supported@0.1.0 | MIT | 通过 |
| isarray@0.0.1 | MIT | 通过 |
| isarray@1.0.0 | MIT | 通过 |
| isexe@4.0.0 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| jsftp@2.1.3 | MIT | 通过 |
| json-schema-traverse@1.0.0 | MIT | 通过 |
| json-schema@0.4.0 | (AFL-2.1 OR BSD-3-Clause) | 通过 |
| klaw@4.1.0 | MIT | 通过 |
| kleur@4.1.5 | MIT | 通过 |
| kuler@2.0.0 | MIT | 通过 |
| lazystream@1.0.1 | MIT | 通过 |
| lilconfig@3.1.4 | MIT | 通过 |
| lockfile@1.0.4 | ISC | 通过 |
| lodash.isfinite@3.3.2 | MIT | 通过 |
| lodash@4.18.1 | MIT | 通过 |
| log-symbols@4.1.0 | MIT | 通过 |
| logform@2.7.0 | MIT | 通过 |
| lru-cache@11.5.3 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| math-intrinsics@1.1.0 | MIT | 通过 |
| media-typer@1.1.1 | MIT | 通过 |
| merge-descriptors@2.0.0 | MIT | 通过 |
| method-override@3.0.0 | MIT | 通过 |
| methods@1.1.2 | MIT | 通过 |
| mime-db@1.52.0 | MIT | 通过 |
| mime-db@1.54.0 | MIT | 通过 |
| mime-types@2.1.35 | MIT | 通过 |
| mime-types@3.0.2 | MIT | 通过 |
| mimic-fn@2.1.0 | MIT | 通过 |
| minimatch@10.2.6 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| minipass@7.1.3 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| morgan@1.12.1 | MIT | 通过 |
| ms@2.0.0 | MIT | 通过 |
| ms@2.1.3 | MIT | 通过 |
| negotiator@1.1.0 | MIT | 通过 |
| normalize-package-data@8.0.0 | BSD-2-Clause | 通过 |
| normalize-path@3.0.0 | MIT | 通过 |
| object-inspect@1.13.4 | MIT | 通过 |
| on-finished@2.4.2 | MIT | 通过 |
| on-headers@1.1.0 | MIT | 通过 |
| once@1.4.0 | ISC | 通过 |
| one-time@1.0.0 | MIT | 通过 |
| onetime@5.1.2 | MIT | 通过 |
| ora@5.4.1 | MIT | 通过 |
| p-limit@7.3.3 | MIT | 通过 |
| parse-listing@1.1.3 | MIT | 通过 |
| parseurl@1.3.3 | MIT | 通过 |
| path-scurry@2.0.2 | BlueOak-1.0.0 | 通过（人工审查：permissive, OSI approved; no copyleft, no attribution beyond the notice (isaacs: glob, minimatch, lru-cache, minipass, path-scurry, isexe). Reviewed 2026-11-07） |
| path-to-regexp@8.4.2 | MIT | 通过 |
| pend@1.2.0 | MIT | 通过 |
| plist@4.0.0 | MIT | 通过 |
| pluralize@8.0.0 | MIT | 通过 |
| portscanner@2.2.0 | MIT | 通过 |
| process-nextick-args@2.0.1 | MIT | 通过 |
| process@0.11.10 | MIT | 通过 |
| proxy-addr@2.0.8 | MIT | 通过 |
| proxy-from-env@2.1.0 | MIT | 通过 |
| qs@6.17.0 | BSD-3-Clause | 通过 |
| qs@6.17.1 | BSD-3-Clause | 通过 |
| range-parser@1.3.0 | MIT | 通过 |
| raw-body@3.0.2 | MIT | 通过 |
| readable-stream@1.1.14 | MIT | 通过 |
| readable-stream@2.3.8 | MIT | 通过 |
| readable-stream@3.6.2 | MIT | 通过 |
| readable-stream@4.8.0 | MIT | 通过 |
| readdir-glob@3.0.0 | Apache-2.0 | 通过 |
| require-from-string@2.0.2 | MIT | 通过 |
| restore-cursor@3.1.0 | MIT | 通过 |
| router@2.2.0 | MIT | 通过 |
| safe-buffer@5.1.2 | MIT | 通过 |
| safe-buffer@5.2.1 | MIT | 通过 |
| safe-stable-stringify@2.5.0 | MIT | 通过 |
| safer-buffer@2.1.2 | MIT | 通过 |
| sanitize-filename@1.6.4 | WTFPL OR ISC | 通过 |
| semver@7.8.5 | ISC | 通过 |
| send@1.2.1 | MIT | 通过 |
| serve-favicon@2.5.1 | MIT | 通过 |
| serve-static@2.2.1 | MIT | 通过 |
| setprototypeof@1.2.0 | ISC | 通过 |
| shell-quote@1.12.0 | MIT | 通过 |
| side-channel-list@1.0.1 | MIT | 通过 |
| side-channel-map@1.0.1 | MIT | 通过 |
| side-channel-weakmap@1.0.2 | MIT | 通过 |
| side-channel@1.1.1 | MIT | 通过 |
| signal-exit@3.0.7 | ISC | 通过 |
| spdx-correct@3.2.0 | Apache-2.0 | 通过 |
| spdx-exceptions@2.5.0 | CC-BY-3.0 | 通过（人工审查：spdx-exceptions: a JSON list of SPDX exception identifiers, data and not code; attribution only. Reviewed 2026-11-07） |
| spdx-expression-parse@3.0.1 | MIT | 通过 |
| spdx-license-ids@3.0.24 | CC0-1.0 | 通过 |
| stack-trace@0.0.10 | MIT | 通过 |
| statuses@2.0.2 | MIT | 通过 |
| stream-buffers@3.0.3 | Unlicense | 通过 |
| stream-combiner@0.2.2 | MIT | 通过 |
| streamx@2.28.1 | MIT | 通过 |
| string-width@7.2.0 | MIT | 通过 |
| string-width@8.3.0 | MIT | 通过 |
| string_decoder@0.10.31 | MIT | 通过 |
| string_decoder@1.1.1 | MIT | 通过 |
| string_decoder@1.3.0 | MIT | 通过 |
| strip-ansi@6.0.1 | MIT | 通过 |
| strip-ansi@7.2.0 | MIT | 通过 |
| supports-color@7.2.0 | MIT | 通过 |
| tagged-tag@1.0.0 | MIT | 通过 |
| tar-stream@3.2.2 | MIT | 通过 |
| teen_process@4.2.1 | Apache-2.0 | 通过 |
| teex@1.0.1 | MIT | 通过 |
| text-decoder@1.2.7 | Apache-2.0 | 通过 |
| text-hex@1.0.0 | MIT | 通过 |
| through@2.3.8 | MIT | 通过 |
| toidentifier@1.0.1 | MIT | 通过 |
| triple-beam@1.4.1 | MIT | 通过 |
| truncate-utf8-bytes@1.0.2 | WTFPL | 通过（人工审查：truncate-utf8-bytes: permissive, no conditions. Reviewed 2026-11-07） |
| type-fest@5.10.0 | (MIT OR CC0-1.0) | 通过 |
| type-is@2.1.0 | MIT | 通过 |
| unorm@1.6.0 | MIT or GPL-2.0 | 通过（人工审查：unorm: dual licensed; we take MIT, not the GPL. Reviewed 2026-11-07） |
| unpipe@1.0.0 | MIT | 通过 |
| utf8-byte-length@1.0.5 | (WTFPL OR MIT) | 通过 |
| util-deprecate@1.0.2 | MIT | 通过 |
| uuid@14.0.3 | MIT | 通过 |
| validate-npm-package-license@3.0.4 | Apache-2.0 | 通过 |
| vary@1.1.2 | MIT | 通过 |
| wcwidth@1.0.1 | MIT | 通过 |
| which@6.0.1 | ISC | 通过 |
| winston-transport@4.9.0 | MIT | 通过 |
| winston@3.19.0 | MIT | 通过 |
| wrap-ansi@9.0.2 | MIT | 通过 |
| wrappy@1.0.2 | ISC | 通过 |
| ws@8.22.0 | MIT | 通过 |
| xmlbuilder@15.1.1 | MIT | 通过 |
| xpath@0.0.36 | MIT | 通过 |
| y18n@5.0.8 | ISC | 通过 |
| yaml@2.9.1 | ISC | 通过 |
| yargs-parser@22.0.0 | ISC | 通过 |
| yargs@18.2.0 | MIT | 通过 |
| yauzl@3.4.0 | MIT | 通过 |
| yocto-queue@1.2.2 | MIT | 通过 |
| zip-stream@7.0.5 | MIT | 通过 |

</details>

## 怎么扫的

- **依赖漏洞**：pip-audit 2.10.1，对每个锁文件逐一扫描，查询 PyPI 漏洞库。扫的是锁文件本身（`--require-hashes`），也就是 CI 实际安装的每一个文件，而不是某台机器上碰巧装着的版本。
- **自身代码**：bandit 1.9.4，扫描 `src/` 下全部代码，任何级别的问题都会让扫描失败。
- **npm 依赖**：`npm audit --package-lock-only --omit=optional`，对每个 npm 锁文件扫描，查询 GitHub 漏洞库；只扫 `npm ci --omit=optional` 会装的包。锁文件里每个包的来源、sha512 和许可证由 `check_components.py` 离线核对。
- **许可证**：读取环境中每个分发包的元数据，包括间接依赖，因为它们同样会被装到用户环境。
- **组件登记**：`setup.cfg`、`setup.py`、`requirements/*.in` 和工作流里引用的每个组件，都必须在登记表里出现且版本写法一致。
- **新版本冷静期**：锁文件只接受发布满 14 天的版本（`scripts/update_locks.py`），恶意版本通常在几天内就会被发现并撤下。

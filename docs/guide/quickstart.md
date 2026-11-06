# 快速开始

五分钟：装好，生成一个项目，跑出第一份报告，接受第一份判定基线。

## 1. 安装

```shell
pip install intellipandora                 # 内核：HTTP、判定、报告
pip install "intellipandora[parallel]"     # 可选：并行执行、单条用例超时
pip install "intellipandora[web]"          # 可选：Web 自动化，之后 python -m playwright install chromium
pip install "intellipandora[visual]"       # 可选：图像判定
pip install "intellipandora[mcp]"          # 可选：给 agent 用的 MCP 入口
```

## 2. 生成项目

```shell
ipandora init my-tests                    # 或 --layout full：分层的用例库，见"组织用例库"
cd my-tests
```

生成的内容：

| 文件 | 作用 |
|---|---|
| `conf/config.yaml` | 项目配置，只写要改的键 |
| `conftest.py` | 一个本地演示服务，让示例用例不联网也能跑通。换成你的真实系统即可 |
| `tests/test_example.py` | 示例用例：通过框架调用接口，逐字段判定 |
| `AGENTS.md` | 给编写用例的 agent 的规则，每条都对应一个门禁或报告信号 |
| `.github/workflows/tests.yml` | CI 样例，开启了 `--fail-on-weakened` |
| `.github/CODEOWNERS` | 判定基线和基准图需要负责人审批 |

已有的文件不会被覆盖；需要覆盖时加 `--force`。

## 3. 跑起来

```shell
ipandora run tests
```

命令行会给出结论、通过率、判定数，以及报告的位置。报告里每条用例都列出它做了哪些判定、发了哪些请求、各自的响应是什么。

## 4. 接受判定基线

```shell
ipandora run tests --update-baseline
git add conf/judgements.json
```

`conf/judgements.json` 记录了每条用例实际做了哪些判定。之后每次运行都会和它比对：删掉断言、放宽范围、改了期望值、改成跳过，都会被列出来；`--fail-on-weakened` 会让这样的运行失败。基线文件的改动和用例改动一起提交，评审时看它的 diff，就知道判定变了什么。

## 接下来

- 写判定：[判定、零判定与基线](judgements.md)
- 接进 CI：[接入 CI](ci.md)
- 让 agent 写用例：[接入 agent](agents.md)

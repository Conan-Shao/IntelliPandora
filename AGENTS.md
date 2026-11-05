# AGENTS.md

写给在**这个仓库里开发框架本身**的 agent。在用例项目里写测试用例的规则不在这里，在 `ipandora init` 生成的 AGENTS.md 里（模板：`src/ipandora/templates/project/AGENTS.md`）。

先读 [架构](docs/design/architecture.md)。每条规则后面写明了是谁在检查它；没有门禁的规则，这里一条也不写。

## 改完之后跑什么

```shell
make install && make install-tools            # 与 CI 相同的锁定版本，逐个校验哈希
pytest test/                                  # 全量测试，不联网
python scripts/smoke_import.py                # 每个模块都能导入
python scripts/check_layering.py              # core/ 不依赖 ai/
python scripts/check_components.py            # 依赖与登记表一致
python scripts/check_docs.py                  # 文档链接有效，参考文档与代码一致
python scripts/check_packaging.py             # 必需的数据文件进了 wheel
git -c core.quotepath=false ls-files -z | xargs -0 python scripts/check_secrets.py
```

CI 上的全部作业都要通过，包括删掉 `src/ipandora/ai` 后的那一遍。**合入前确认 PR 的 CI 是绿的**：本地门禁全绿而 CI 是红的，这种情况在这个仓库里出现过。

## 规则

| 规则 | 谁来检查 |
|---|---|
| `core/` 不得 import `ai/`；LLM 不参与判定 | `check_layering.py`；CI 的 `test-without-ai` 作业 |
| 新增或升级第三方组件，先按 `docs/design/decisions/15` §3 做准入，在 `docs/security/components.md` 登记，再 `make locks` | `check_components.py` 拦下未登记或版本写法不一致的组件；锁文件只接受发布满 14 天的版本 |
| 依赖进可选组，不进内核，除非有充分理由 | 评审；`check_components.py` 按类别核对 |
| 改了 CLI 参数或 `src/ipandora/conf/config.yaml`，重新生成参考文档：`python scripts/check_docs.py --write` | `check_docs.py` |
| 用户手册（`docs/guide/`）里的 Python 代码要能运行；示例里 import 的名字必须存在 | `test/testdocs/` |
| bandit 报出的问题能修就修；确认不构成问题的，在该行标 `# nosec Bxxx`，并在**上一行**写 `# bandit Bxxx: 理由` | `security_report.py`：没有理由的标注会让扫描失败，每一处都公开列在安全报告里 |
| 新能力要有测试，测试要能在实现被改坏时失败 | 评审；`scripts/mutation.py` 做变异测试 |
| 并行时结论必须和串行一致：在用例进程里记录的东西，经报告的 `user_properties` 回传，不在主进程里直接读用例 | `test/testrunner/test_parallel.py` 逐字节比对判定清单 |
| 文档、代码注释、提交信息里不写真实的凭据、内网地址、真实邮箱 | `check_secrets.py` |
| 改了行为，在 `src/ipandora/CHANGELOG` 最上面那个版本下记一条 | 评审 |

## 文档放在哪

| 位置 | 写什么 |
|---|---|
| `docs/guide/` | 给使用者，按任务组织 |
| `docs/reference/` | 从代码生成，不要手改 |
| `docs/design/architecture.md` | 当前架构，随代码更新 |
| `docs/design/decisions/` | 决策记录。已有的不再改写，只在末尾追加修正 |
| `docs/security/` | 组件登记表、漏洞例外、安全报告（报告由脚本生成） |
| `docs/dev/` | 给框架开发者：开发环境、发布流程 |

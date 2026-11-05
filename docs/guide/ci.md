# 接入 CI

`ipandora init` 生成的 `.github/workflows/tests.yml` 就是下面这些内容的样例。

## 门禁

```shell
ipandora run tests --fail-on-weakened --junit-xml report.xml
```

- **退出码就是结论**：有用例失败，退出码就不是 0。
- **`--fail-on-weakened`**：判定比基线 `conf/judgements.json` 弱，就算运行失败。弱包括：删除判定、放宽范围、改了期望值、新增跳过或排除、通过了却没有任何判定。收紧和新增判定不受影响。
- **`--junit-xml`**：CI 能直接读的 JUnit XML。没有对应状态的结果，比如零判定、阻塞、缺口，写成 `<skipped>`，真实状态记在属性里，不会被算进通过数。
- **`--exclude-flaky`**：排除标了 `@pytest.mark.flaky(reason=...)` 的用例，报告里仍会点名。

## 基线的评审

基线文件由人接受，不由 agent 接受：

1. 有意改动判定时，在 PR 里说明原因，由负责人运行 `ipandora run --update-baseline`，并把 `conf/judgements.json` 的改动一起提交。
2. 用 `.github/CODEOWNERS` 要求负责人审批 `conf/judgements.json` 和 `__goldens__/`。
3. 在仓库设置里开启分支保护，要求测试检查通过才能合入。

## 并行与超时

```shell
ipandora run tests --workers auto --timeout 120
```

需要 `intellipandora[parallel]`。共用账号的用例用 `@pytest.mark.resource('account:...')` 声明，并行时不会同时执行。资源锁只在同一台机器内有效，多台 runner 共用账号时需要分别分配，见 [并行与并发](parallel.md)。

## Web 用例

```shell
pip install "intellipandora[web]"
python -m playwright install --with-deps chromium
```

浏览器版本由 Playwright 版本决定，不在 Python 依赖里。可以按 Playwright 版本缓存浏览器目录（默认 `~/.cache/ms-playwright`）。

## 图像判定

基准图按平台区分，请在 CI 运行的环境里生成：在 CI 里用 `--update-baseline` 跑一次，把生成的 `__goldens__/` 下载下来提交。在本地生成的基准图，到了 CI 上会失败。

## 报告

每次运行都会写出 HTML 报告、JSON 和 JUnit XML。在 CI 里把报告目录（`$IPANDORA_REPORTS_DIR`，默认 `~/.ipandora/reports`）作为制品上传，失败的截图、trace、基准图对比都在里面。

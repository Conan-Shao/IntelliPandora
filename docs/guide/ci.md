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

## 分片到多个 job

单台机器跑不完时，把用例按目录分到多个 job，每个 job 各出一份报告，最后一个 job 合并成一份报告、一个结论：

```yaml
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        shard: [tests/api, tests/web, tests/batch]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4     # 示例用标签；正式使用请固定到提交 SHA
      - run: pip install intellipandora
      - run: ipandora run ${{ matrix.shard }} --fail-on-weakened -d out --no-archive
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: report-${{ strategy.job-index }}
          path: out/

  verdict:
    needs: test
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4     # 为了读到 conf/judgements.json
      - run: pip install intellipandora
      - uses: actions/download-artifact@v4
        with:
          pattern: report-*
          path: shards
      - run: >
          ipandora merge shards/* -o merged --baseline conf/judgements.json
          --fail-on-weakened --junit-xml merged/ci.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: report-merged
          path: merged/
```

`ipandora merge` 的退出码规则和 `ipandora run` 相同，作为整条流水线的结论。合并时：

- **同一条用例出现在多个分片里只计一次**，报告写明去掉了几条重复。目录划分有重叠、某个分片被重跑后两次都上传了，都属于这种情况。
- **同一条用例在不同分片里结论不同，单独列为"分片之间结论不一致"**，合并后取更严重的结论：一个分片失败、另一个通过，合并后是失败，结论不会因为合并变绿。这通常意味着用例不稳定，或者各分片跑的代码不同。
- **各分片对比基线的结果会合并**；覆盖矩阵按全部分片重新计算。
- **`--baseline` 用来发现丢掉的用例**：单个分片只跑了一部分，看不出哪条用例没了。传入基线，就是声明"这些分片合起来是整个套件"：基线里通过、但没有任何分片报告的用例，记为"用例删除"，属于判定变弱。某个分片的报告没上传、整批用例消失，也会这样被发现。只有分片确实覆盖了整个套件时才传。
- **各分片运行的环境不同时拒绝合并**（例如一个跑 dev、一个跑 staging），确有需要时加 `--allow-mixed-env`。同一份报告传两次也会被拒绝。
- 想对比主分支上次的结果，给 `ipandora merge` 加 `--compare-with`，传主分支上次合并出的 `report.json`。

更新基线（`--update-baseline`）请在一次不分片的运行里做：多个分片同时写同一个基线文件会互相覆盖。

在 Python 里：

```python
from ipandora.core.report import merge_files, write

report, _ = merge_files(['shards/report-0', 'shards/report-1'])
write(report, 'merged/')
report.verdict['releasable']
report.merge_conflicts      # [{'nodeid': ..., 'status': 'FAIL', 'seen': [{'run_id': ..., 'status': ...}, ...]}]
```

## Web 用例

```shell
pip install "intellipandora[web]"
python -m playwright install --with-deps chromium
```

浏览器版本由 Playwright 版本决定，不在 Python 依赖里。可以按 Playwright 版本缓存浏览器目录（默认 `~/.cache/ms-playwright`）。

## 图像判定

基准图按平台区分，请在 CI 运行的环境里生成：在 CI 里用 `--update-baseline` 跑一次，把生成的 `__goldens__/` 下载下来提交。在本地生成的基准图，到了 CI 上会失败。

## 报告

CI 的容器每次都是新的，没有本机存档可比。想在报告里看到"比主分支新失败了哪些"，就把主分支上次运行的 `report.json` 下载下来，用 `--compare-with` 传进去；不传也没关系，"对比基线"这一栏不依赖任何历史，见[报告](reports.md#和什么比基线以及可选的一次运行)。

每次运行都会写出 HTML 报告、JSON 和 JUnit XML。在 CI 里把报告目录（`$IPANDORA_REPORTS_DIR`，默认 `~/.ipandora/reports`）作为制品上传，失败的截图、trace、基准图对比都在里面。

# Web 自动化

Playwright 原样使用，框架补上判定、失败现场和归因。

## Web 自动化

```shell
pip install intellipandora[web]
python -m playwright install chromium     # 浏览器版本由 Playwright 版本锁定
```

**直接写 Playwright。** 用 pytest-playwright 的 `page`、`context`、`browser` fixture，以及它自带的 `--browser`、`--headed`、`--device` 等选项，没有要另学的 API：

```python
from playwright.sync_api import Page, expect

def test_pay(page: Page):
    page.goto('/checkout')                                  # base_url 来自 conf
    page.get_by_role('button', name='付款').click()
    expect(page.locator('#amount')).to_have_text('100.50')
```

用 `ipandora run` 跑，框架会多做这几件事：

- **`expect` 算判定。** 每个成立的 `expect` 都会记为一条判定，进入判定清单，比如 `expect locator('#amount') to_have_text '100.50'`。所以只用 `expect` 写的用例不会被判为零判定；把期望值改弱了，基线比对也看得出来。失败的 `expect` 记为失败的判定，带着 Playwright 自己的报错信息。
- **失败现场。** 失败时自动截图并保留 trace。截图直接嵌在报告里，trace 给出打开命令 `playwright show-trace "<路径>"`。每次运行用自己的目录，归档的报告链接不会被下一次运行冲掉。
- **选择器失效还是元素真没了。** 选择器找不到元素时，框架不会一律算成用例的问题：
  - 用例通过时，会记住每个选择器指向的是什么元素（角色和无障碍名称，例如 `button "付款"`）。
  - 下次找不到时，在页面上按这个角色和名称再找一次。
  - **找到了**：说明元素还在，只是选择器过时了，归为用例自身的问题（harness），改选择器即可。
  - **找不到**：归为"待确认：可能是产品缺陷"，附截图。按钮被删、被改名，正是这种情况。
  - **从没记录过**：同样是"待确认"。
  - 拿不准的时候，结论不会往"不是产品的问题"那边归。
- **并行。** `--workers 4` 同样适用，每个进程一个浏览器，每条用例一个新的上下文，结论和串行一致。

**配置**（`conf/config.yaml` 或 `conf/<env>.yaml`）只是 pytest-playwright 选项的默认值；命令行显式给的 `--base-url` / `--browser`，以及用例项目 conftest 里的 `browser_context_args`，优先级更高：

```yaml
web:
  base_url: https://staging.example.com
  browser: chromium          # chromium | firefox | webkit
  viewport: {width: 1280, height: 720}
```

**页面上的值和接口的值用同一套判定**：`that(page.locator('#amount').inner_text(), '页面金额') == field(r, 'data.amount')`。

**需要知道的：**

- 浏览器是运行时下载的，默认来自微软的 CDN。内网环境用 `PLAYWRIGHT_DOWNLOAD_HOST` 指向镜像，或者用 `--browser-channel chrome` 改用系统安装的 Chrome。
- WebKit 不等于真正的 Safari。必须在真 Safari 上验证的场景，请用 Selenium + safaridriver，判定层（`that()`、判定清单、报告）照样能用。
- Python 版 Playwright 没有截图比对，图像判定在后续版本提供。
- 同步 API 不能在 asyncio 里用，会直接报错 "It looks like you are using Playwright Sync API inside the asyncio loop"。async 用例请用异步 API。
- 公开站点的完整示例见 `examples/web/test_todomvc.py`。

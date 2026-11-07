# Android 自动化

用 [uiautomator2](https://github.com/openatx/uiautomator2) 测 Android App：用例拿到的就是它的 `Device`，写法照它自己的文档；框架负责 App 的生命周期、同一台设备一次只给一条用例、失败时的证据，以及失败归因。设计依据见 [决策记录 14](../design/decisions/14-技术方案与实施计划.md) §5。

## 安装

```shell
pip install 'intellipandora[android]'
```

uiautomator2 带来 adbutils，adbutils 的 wheel 里自带 `adb`；也会用 PATH 里的 adb。设备可以是真机（打开 USB 调试），也可以是模拟器。第一次连接时，uiautomator2 会把它自带的设备端服务（`u2.jar`）推到设备上运行。

## 配置

在环境的 `conf/<env>.yaml`（或项目的 `conf/config.yaml`）里：

```yaml
android:
  serial: emulator-5554          # 不写：用 $ANDROID_SERIAL；都没有：连着的那一台
  package: com.example.shop      # 被测 App 的包名
  app_path: build/shop.apk       # 可选：每次会话开始时装一次，相对项目根目录
  clear_data: false              # true：每条用例前 pm clear，从干净的数据开始
  keep_app: false                # true：用例结束后不停 App
```

## 写用例

```python
def test_login(android):
    android(text='登录').click()
    android(resourceId='com.example.shop:id/user').set_text('alice')
    assert android(text='欢迎').exists
```

- `android` 是 `uiautomator2.Device`。每条用例开始前 App 已经启动（`clear_data` 时先清数据），结束后停掉。
- 需要会话范围的设备（比如在 fixture 里先登录一次），用 `android_device`：它不启动、不停止 App，也不加锁。
- `android(...)`、`android.xpath(...)`、`android.swipe(...)` 等都是 uiautomator2 自己的接口，框架不包一层。
- fixture 叫 `android` 而不是 `device`：pytest-playwright 已经有一个叫 `device` 的 fixture（浏览器的设备模拟），同名会让 Web 用例全部出错。

## 设备一次只给一条用例

`android` 在用例期间持有资源锁 `device:<serial>`。并行运行（`--workers`）时，用同一台设备的用例轮流跑，不会两条同时点同一个屏幕；同一台机器上的两次运行也一样。要并行，就接多台设备，每个 worker 用不同的 `serial`。

## 失败时的证据

用例失败的那一刻（App 还没被停掉），框架取下：

| 证据 | 内容 |
|---|---|
| 截图 | 失败时的屏幕，嵌在报告里 |
| 控件树 | `dump_hierarchy()` 的 XML，路径写在报告里 |
| logcat | 用例开始以来（按设备时间）被测 App 自己的日志行，以及所有崩溃（`AndroidRuntime`）和 ANR 行，凭据先脱敏，直接引用在报告里。最多 300 行：崩溃和 ANR 行总是保留，其余留给最近的行 |

每一项单独取：截图失败了，日志照样有。

## 失败归因

| 情况 | 归因 |
|---|---|
| logcat 里有被测 App 的 `FATAL EXCEPTION` 或 `ANR in <包名>` | **产品缺陷**（确定）。之后不论什么失败——控件找不到、超时——都是崩溃的后果。别的 App 崩溃不算 |
| 选择器什么也没找到，但当时控件树里有同名控件（文字、content-desc、resource-id 或 id 名相同） | 用例自身：选择器写错或过时（属性、层级、序号不对），App 没问题 |
| 选择器什么也没找到，控件树里也没有同名控件 | **待确认**：控件可能被删掉或改了名，也可能界面还没走到这一步。看截图和控件树 |

"同名"按选择器里的 `text`、`description`、`resourceId`（及其 `:id/` 后面的名字）比较，XPath 按其中引号里的值比较，不区分大小写。拿不准时不往"不是产品问题"那边判。

## 在 CI 上跑

GitHub Actions 的 Linux runner 支持 KVM，可以起 Android 模拟器（例如 `reactivecircus/android-emulator-runner`）；本框架自己的 CI 就这样跑 Android 的验收用例。没有 KVM 的机器上模拟器慢到不可用，改用真机或云真机。

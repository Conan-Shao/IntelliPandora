# 登录态：身份与提供者

接口要 token、要 cookie。用例里只写**身份**（买家、卖家、管理员），不碰凭据；凭据怎么拿，由**提供者**在 `conftest.py` 里写一次。设计依据见 [决策记录 17](../design/decisions/17-登录态与用例组织.md) §2。

## 三个概念

- **身份**：用例说的"谁"，例如 `buyer`、`seller`、`anonymous`。只是名字，可以出现在用例、报告和日志里。
- **凭据**：token、cookie、API key。只出现在请求里，报告里会脱敏。
- **提供者**：为一个身份拿到凭据的代码。每个系统登录方式不一样，所以用 Python 写。

## 用例怎么写

```python
from ipandora.core import auth
from ipandora.core.assertion import assert_all, status_is, status_ok


def test_buyer_cannot_see_other_orders(shop):
    with auth.identity('buyer'):
        r = shop.order_of_seller()
    assert_all(status_is(r, 403))


def test_two_roles_in_one_case(shop):
    with auth.identity('seller'):
        assert_all(status_ok(shop.ship(7)))
    with auth.identity('buyer'):
        assert_all(status_ok(shop.confirm(7)))
```

- 每个身份有自己的会话：自己的 cookie、自己的请求头。买家的登录不会出现在卖家的请求里。
- 不写 `identity(...)` 时，用的是原来的默认会话，行为和以前完全一样。
- `anonymous` 不带任何凭据，用来测未登录访问。
- `identity` 可以嵌套，也可以当装饰器用。`concurrently()` 启动的线程沿用调用方的身份；也可以在每个线程里各自 `with auth.identity(...)`，写"两个买家同时抢购"。

## 提供者怎么写

```python
# conftest.py
from ipandora.core import api, auth
from ipandora.core.assertion.http import json_body


class LoginApi:
    @api.http.post('https://shop.example/api/login')
    def login(self, user, password):
        return {'json': {'user': user, 'password': password}}


class ShopLogin(auth.Provider):
    def login(self, name, session):
        r = LoginApi().login(name, auth.secret(name.upper() + '_PASSWORD'))
        body, _ = json_body(r)
        return auth.Bearer(body['token'], expires_in=body['expires_in'])


auth.provider(ShopLogin())
```

- `login(name, session)` 返回凭据。`session` 是这个身份自己的 `requests.Session`。
- 用框架的接口类发登录请求（像上面那样），登录请求会进这条用例的证据，标为"登录"；直接用 `session.post` 也可以，只是证据里看不到。
- 口令从环境变量读：`auth.secret('BUYER_PASSWORD')`。没设置时报错并说明。不要写进 `conf/config.yaml`。
- 只有一个登录函数时，可以直接注册函数：`auth.provider(lambda name, session: ...)`。

凭据的几种形态：

| 写法 | 放进请求的方式 |
|---|---|
| `auth.Bearer(token, expires_in=秒)` | `Authorization: Bearer …`。没给 `expires_in` 而 token 是 JWT 时，读它的 `exp` |
| `auth.ApiKey(key)`、`auth.ApiKey(key, header='X-Token')`、`auth.ApiKey(key, param='key')` | 请求头或查询参数 |
| `auth.Cookies(...)`；或者 `login()` 里用 `session` 登录、什么都不返回 | cookie。不返回时，框架取登录后会话里的 cookie |
| 重写 `sign(name, credential, request)` | 每个请求现算签名，改 `request.kwargs` 里的头或参数 |

## 框架替你做的

- **用到时才登录**，每个进程每个身份只登录一次。登录接口常有频率限制；单会话的系统里，反复登录会把自己踢下线。
- **提前刷新**：有效期只剩 60 秒，或者只剩总有效期的五分之一（取较小者）时，先换新的再发请求。有刷新令牌的，重写 `refresh(name, credential, session)`；默认是重新登录。
- **被拒为"未登录"时重新登录，并把这一个请求重放一次**。两次请求都进证据，第二次标为"重新登录后重放"。
  - 默认按 HTTP 401 判断。用业务码表示未登录的系统，重写 `unauthenticated(response)`。
  - 请求体是文件或流时不重放。
  - 不想重放的，在提供者上设 `refresh_on_401 = False`。
- **用例自己写的凭据从不刷新**：请求上带了自己的 `Authorization`、`Cookie` 或 API key 头，框架不登录、不替换、不重放。所以"过期 token 应该被拒绝"这样的用例不会被框架悄悄修好。
- **运行结束清空**：提供者、凭据、各身份的会话都会清掉。MCP 服务跨多次运行常驻，上一次的 token 不会带到下一次。
- **证据记身份名，不记凭据**：报告里每个请求旁边标出是谁发的。越权类失败一眼能看出来。
- **登录失败不算产品缺陷**：账号、口令不对归为"测试数据"，登录接口连不上归为"环境"。

## Web 用例：`page_as`

```python
from playwright.sync_api import expect


def test_buyer_pays(page_as):
    page = page_as('buyer', '/orders/7')              # 带 buyer 登录态的新页面
    page.get_by_role('button', name='付款').click()
    expect(page.get_by_text('支付成功')).to_be_visible()


def test_two_roles(page_as):
    buyer, seller = page_as('buyer', '/orders/7'), page_as('seller', '/orders/7')   # 两个独立的浏览器上下文
```

`page_as` 是框架提供的 fixture（需要 `intellipandora[web]`）。每次调用新建一个浏览器上下文，所以一条用例里可以同时有两个角色。接口和页面共用同一个身份：先用接口给 `buyer` 造数，再用 `page_as('buyer')` 在页面上检查。

浏览器怎么拿到登录态，提供者选一种：

| 方式 | 提供者怎么写 | 适合 |
|---|---|---|
| **接口登录**（默认，推荐） | 只写 `login()`。`page_as` 用这个身份的 HTTP 会话登录，把会话里的 cookie 放进浏览器 | 登录走接口、凭据在 cookie 里的系统。最快，不打开登录页 |
| **页面登录** | 再写 `web_login(name, page)`，在页面上填表登录 | SSO 跳转，或者 token 存在 localStorage 的单页应用。每个进程每个身份登录一次，浏览器状态存在内存里复用 |

- **知道"已登录"**：在提供者上设 `login_url = r'/login'`（或者重写 `web_logged_in(page)`）。它是一个正则，和登录页 URL 的**路径**完整匹配：`/account/login-history`、`?next=/login` 都不算登录页。`page_as(name, url)` 打开页面后检查：被跳回登录页，就重新登录、再打开一次；还是不行，判为"测试数据"问题。不设的话，`page_as` 发现不了"登录了但页面没登录"。
- **token 在 sessionStorage 里**：浏览器状态不保存 sessionStorage。在 `web_prepare(name, credential, context)` 里用 `context.add_init_script(...)` 写回去，并返回 `True`，表示凭据已经交给浏览器。token 在 IndexedDB 里的（例如 Firebase），设 `web_indexed_db = True`。
- **token 在请求头里**：设 `web_headers = True`，浏览器的每个请求都会带上凭据的请求头，和用例在 `browser_context_args` 里设的请求头合并。默认关闭，因为页面加载的其他站点也会收到。
- **只能在浏览器里完成的登录**（SSO），接口用例也要用：提供者实现 `web_login`，用例里先 `page = page_as('buyer', '/')`，再 `web.share_with_api('buyer', page)`；之后以 `buyer` 发的接口请求都用这次浏览器登录的 cookie。token 在 localStorage 里的，加 `local_storage_key='token'`。不要在 `login()` 里自己启动浏览器：pytest-playwright 已经在同一线程里运行，第二个 Playwright 起不来。
- 页面登录用的浏览器上下文不录制 trace，输入的口令不会进失败现场。
- 接口登录转 cookie 时，没有域名的 cookie 用 `web.base_url` 的主机名补全。
- **trace 里有凭据**：Playwright 的 trace 记录请求头和请求体，没法脱敏。失败现场只作为私有制品保存；敏感环境在配置里设 `web.trace: off`。

## 还没做的

- 并行时多个 worker 共用一份凭据（单会话账号）和账号池：计划 A2。目前每个 worker 进程各登录一次，各自的浏览器登录态也各存一份。

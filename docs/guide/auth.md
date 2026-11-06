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

## 还没做的

- 并行时多个 worker 共用一份凭据（单会话账号）和账号池：计划 A2。目前每个 worker 进程各登录一次。
- Web 用例的登录态 `page_as('buyer')`：计划 A3。

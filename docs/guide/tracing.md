# 跨服务链路

一个请求失败，原因常常在下游第三个服务里。被测系统接了链路追踪（Jaeger、Tempo，或任何读 [W3C Trace Context](https://www.w3.org/TR/trace-context/) 的后端）时，打开链路，就能从用例直接跳到服务端那一次调用的完整记录。

## 打开

```yaml
# conf/config.yaml，或某个环境的 conf/<env>.yaml
tracing:
  enabled: true
  link: http://jaeger.test:16686/trace/{trace_id}
```

- `enabled: true`：用例发出的每个 HTTP 请求都带一个 `traceparent` 头。同一条用例的请求同属一个 trace（`concurrently()` 的线程里发出的也一样），每个请求是其中一个新的 span。默认关闭。
- `hosts`（可选）：除了 `web.base_url` 的主机，浏览器里还要带 `traceparent` 的主机，例如 `[api.shop.test, "api.shop.test:8443"]`。
- `link`：报告里把 trace id 变成链接，`{trace_id}` 处填入 trace id。只接受 `http://` / `https://` 地址。Tempo 用 Grafana 的 explore 链接，写法同理。

报告的用例详情里，"HTTP"一节开头列出这条用例的 trace，每个请求下面写着它的 trace id。连接失败、没有拿到响应的请求也有：请求可能已经到了某个服务，被记了下来。

## 规则

- **用例或埋点自己写的 `traceparent` 优先**：用例在请求头里或会话（session）上写了，或者装了 OpenTelemetry 的 requests 埋点、在发送时写了自己的，框架就不覆盖。证据里记的是实际发出去的那个，报告链接到的也是它。
- **签名覆盖它**：`traceparent` 在身份凭据和 `Provider.sign()` 之前加上，按全部请求头签名的方案不会因此失效。未登录被拒、重新登录后重放的请求是一个新的 span，同一个 trace。
- **框架不上报自己的 span**：不引入追踪 SDK，只发起 trace，由服务记录。后端会把服务的第一个 span 显示为根（有的后端会提示"缺少父 span"），不影响查看。
- `traceparent` 的采样标志是 1（请求采样）。后端按自己的采样策略决定是否保留；用例要看的 trace 被丢掉时，检查服务端的采样配置。压测时每个请求都会被要求采样，压测环境里一般关掉 `tracing.enabled`。
- 连接层的自动重试（幂等方法）沿用同一个请求头，几次重试是同一个 span。
- 报告只把 http(s) 地址渲染成链接，包括合并分片得到的报告。

## 浏览器里的请求

Web 用例里，页面自己发出的请求（页面、脚本、`fetch`）也带 `traceparent`，和同一条用例的 API 请求同属一个 trace，每个请求一个新的 span：

- **只发给被测应用**：`web.base_url` 的主机和 `tracing.hosts` 里列出的主机。CDN、统计服务、第三方登录页不是被测系统，不带。没有 `base_url` 也没有 `hosts` 时，浏览器请求不带。
- 页面自己的埋点已经写了 `traceparent` 的请求，保留它的。
- `page`、`context` 和 `page_as(...)` 打开的页面都覆盖。浏览器自己发起、不经过页面的请求（如 favicon）不带。上下文自己的请求头（`extra_http_headers`，比如 `page_as` 放进去的登录凭据）照常发出。
- 实现方式是 Playwright 的请求路由（`context.route`），打开链路后，这个浏览器上下文不再使用 Playwright 的 HTTP 缓存：页面每次都重新下载资源。只在 `tracing.enabled: true` 时这样。
- 只发生在浏览器里的 trace（这条用例没有 API 请求）也会写在报告里这条用例的"链路"一行。

## 范围

用例直接用 `requests` 发的请求不带：只有经框架 HTTP 层（`api.http`）和浏览器发出的请求带。

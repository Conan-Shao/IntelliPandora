# 依赖环境

用例要一整套环境才能跑：被测服务、它的数据库、消息队列、故障注入用的 Toxiproxy。项目里通常已经有一个 `compose.yaml` 用来本地开发；`stack.compose()` 直接用它，起好、等健康检查通过、用完一定关掉。设计依据见 [决策记录 19](../design/decisions/19-依赖环境编排.md)。

## 准备

装 Docker 和 Docker Compose v2.20 或更新的版本（`docker compose version`）。框架不安装、不分发它们；没有 Docker 时，用到环境的用例跳过并说明原因，不会被当成通过。

compose 文件里**只写容器端口**，让 Docker 分配宿主机端口，并行运行时不会冲突：

```yaml
services:
  api:
    image: registry.example.com/shop-api@sha256:...
    ports: ["8080"]                 # 不写 "8080:8080"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/health"]
      interval: 2s
      retries: 30
```

`up --wait` 按每个服务的健康检查等它就绪；没有健康检查的服务，只等到容器在运行。

## 用

```python
import pytest

from ipandora.core import stack


@pytest.fixture(scope='session')
def shop():
    with stack.compose('compose.yaml', wait=120) as s:
        yield s


def test_order(shop):
    base = shop.url('api', 8080)            # http://127.0.0.1:<Docker 分配的端口>
```

- `stack.compose(files, services=(), env=None, wait=120)`：`files` 可以是一个路径或几个；`services` 只起这些服务（和它们依赖的）；`env` 是 compose 文件里 `${...}` 用的变量；`wait` 是等健康检查的秒数，拉镜像的时间另算。
- `Stack.port(service, 容器端口)`、`address(...)`、`url(...)`：从这里访问那个端口的地址。
- `Stack.logs(service=None, since=None, tail=None)`：服务日志。

和 [故障注入](faults.md) 一起用：把 Toxiproxy 也写进 compose 文件，用 `shop.url('toxiproxy', 8474)` 作为 `faults.toxiproxy`，用 `faults.proxy('db', '0.0.0.0:8666', 'db:5432')` 在 compose 网络里建代理。

## 保证

- **一定关掉**：离开 `with` 块时 `down --volumes`，用例失败、抛异常也一样。进程被杀留下的环境，在这台机器上下一次起环境时清理。只清本机、进程已经不在的那些（项目名是 `ipandora-<主机>-<进程号>-<名字>`）。
- **每个进程一套**：并行运行（`--workers`）时，每个 worker 的会话级 fixture 起自己的一套环境。几个 worker 要共用一套，就在运行之前自己起好，用例只读地址。
- **起不来是环境问题**：健康检查不过、镜像拉不下来、端口被占用时，抛 `StackError`，消息里有没起来的服务和它们日志的最后几行，归因为"环境"。
- **失败时留下服务日志**：用例失败时，每个服务在这条用例期间（从用例开始算）写的日志，最后 80 行存成文件，并且写进报告的"失败现场"。日志先去掉凭据，规则和报告里的请求一样。

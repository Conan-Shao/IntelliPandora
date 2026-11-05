# 配置、环境与测试数据

`conf/` 目录、按环境叠加、Runtime、测试数据。

## 测试数据注入

```python
import os

from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface

# 端点地址可以写死，凭据不行：仓库是公开的。
ENDPOINTS = {
    "eventPlatform": {"url": "https://api.example.com",
                      "token": os.environ["EVENT_PLATFORM_TOKEN"],
                      "user": os.environ["EVENT_PLATFORM_USER"]}
}


class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return ENDPOINTS


PluginManager.endpoints(reg=EndPointPlugin())

```

## 配置文件与环境（`conf/`）

配置放在**你的用例项目**里，不用改装好的包：

```
your-suite/
├── conf/
│   ├── config.yaml      # 本项目的默认配置，覆盖框架自带默认值
│   ├── staging.yaml     # ipandora run -e staging 时叠加
│   └── prod.yaml
└── tests/
```

```yaml
# conf/config.yaml —— 只写要改的键，其余沿用框架默认
http:
  read_timeout: 60
```

```yaml
# conf/staging.yaml
base_url: https://staging.example.com    # 框架不认识的键，留给你的用例自己读
http:
  verify: false        # 只在这个一次性环境关
```

```shell
ipandora run tests -e staging
```

框架读取 `http`、`web`、`ai`、`mcp` 这几段。其他键（如上面的 `base_url`）原样留在 `Runtime.settings` 里，由你的端点插件（见 [2.2.1](#测试数据注入)）自己取：

```python
from ipandora.core.schedule.runtime import Runtime

class EndPointPlugin(EndPointsInterface):
    def endpoints(self, mark):
        return {"svc": {"url": Runtime.settings.get("base_url", "http://localhost:8080")}}
```

叠加顺序（后者覆盖前者）：

1. 框架自带 `ipandora/conf/config.yaml`
2. 项目目录 `conf/config.yaml`
3. 项目目录 `conf/<env>.yaml`（仅本次运行）

项目目录默认是**当前工作目录下的 `conf/`**；设了环境变量 `IPANDORA_CONFIG_DIR` 就用它（CI 里从别处取配置时用）。

几条行为：

- **深合并**：`staging.yaml` 写 `ai: {enabled: true}` 只改 `enabled`，`ai.model` 等其余键保留
- **只作用于这一次运行**：`run()` 结束后配置恢复原样。同一进程里连续跑（MCP server 就是这样），上一次的环境不会串到下一次
- **找不到环境文件会打 WARNING**，并列出找过的路径——`-e stagnig` 这种拼写错误不会悄悄用默认配置跑完
- `-e` 只接受名字，不接受路径
- 旧位置（装好的包目录里的 `conf/<env>.yaml`）仍然能读到，但会提示迁到项目目录

## 测试执行参数全局管理 Runtime

```python
import pytest
import os
from ipandora.core.schedule.runtime import Runtime

# 写入
# config 为pytest的配置对象，其他框架可以同理自定义
Runtime.settings = config.option.__dict__
Runtime.Option.project_path = os.path.dirname(os.path.abspath(__file__))

# 获取
_project_path = Runtime.Option.project_path
_os = Runtime.Ui.os
```

**配置是进程级懒缓存的** —— 首次读取后就记住了。测试里改过配置要还原，用 `reset`：

```python
Runtime.Http.verify = False
...
Runtime.reset('Http')     # 恢复该段默认值
Runtime.reset()           # 恢复全部
```

不还原的话，这个覆盖会泄漏给后面所有测试。

## 用例步骤记录

`Runtime.Case` 的状态是 **thread-local** 的，并发跑用例不会互相串号：

```python
Runtime.Case.cur_case_name = 'test_send'
Runtime.Case.steps = [url, headers, params, body]   # 追加一条

Runtime.Case.steps          # 读取，非破坏性
Runtime.Case.drain_steps()  # 取走并清空
Runtime.Case.clear()        # 清掉当前线程的全部记录
```

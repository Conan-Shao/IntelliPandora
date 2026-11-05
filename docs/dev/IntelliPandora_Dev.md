# 开发手册

## 1.基础
- **语言**
> **PYTHON 3.10+**（代码用了 PEP 604 的 `int | list[int]`，3.7 从来跑不起来）

- **版本管理**
> ***CHANGELOG*** 内按格式添加版本内容

- **编译发布**
> 本地deploy需配置pypirc, 或者通过ci发布
  - 编译打包
    ```shell script
    python3 setup.py bdist_wheel
    ```
  - 
    ```shell script
    twine upload -r local dist/*.whl
    ```

## 2.开发规范

###  **目录结构**
```shell
.
├── src
│   └── ipandora                # 包名是 ipandora，发行名才是 intellipandora
│       ├── CHANGELOG
│       ├── ai/                 # 可选 LLM 支持，可整包删除
│       ├── common/
│       ├── conf/               # config.yaml 与报告模板
│       ├── core/
│       ├── run/                # 命令行
│       ├── utils/
│       └── version.py
├── scripts                     # 门禁：smoke_import / layering / secrets / packaging / mutation
├── docs
│   ├── design/                 # 设计与返工记录
│   ├── dev/
│   └── usr/
└── test
```

###  **说明**
代码都在 **`src/ipandora`**（注意：包名 `ipandora`，发行名 `intellipandora`）。

  * **core**: 核心能力
    * **protocol**: 协议层。目前只有 `http/`——传输策略、响应解析、回放适配
    * **assertion**: 断言层。`Check` / `assert_all` / `require` / `gap`
    * **runner**: 库可调用的执行入口；CLI 与 MCP 都是它的薄壳
    * **report**: ReportData → HTML / JSON / JUnit XML + 历史归档
    * **cassette**: 流量录制回放、差异引擎、HAR/nginx/envoy 导入
    * **triage**: 失败归因，规则优先，LLM 可选
    * **evidence**: 请求响应证据采集
    * **mcp**: agent 入口
    * **plugin** / **schedule**: 插件注册、Runtime 配置
    * **engine/crypto**: 配置加密；密钥存放在 `~/.ipandora/crypto`，不在包内
  * **common** / **utils**: 工具
  * **run**: 命令行
  * **conf**: 配置与报告模板

### 框架设计

* 架构（入口 / 执行 / 资产 / 评测四层）

![架构](./static/architecture.svg)

* 日常工作流

![工作流](./static/workflow.svg)

> 旧的 `framework_architecture.jpg` 与 `business_flow.png` 已删除：它们画的是还有平台数据上报、还有 pandora runner、还有代码自动生成的时代，那三样都已归档。

### **开发手册**
  * [IntelliPandora开发手册(完善中)](./Python_Dev_Standard.md)

## 3.单元测试
> test目录下编写单元测试用例
> 参考 test/testhttp/test_http_get.py
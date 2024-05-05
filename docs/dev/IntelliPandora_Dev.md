# 开发手册

### 1.基础
- **语言**
> **PYTHON3.7+**

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

### 2.开发规范
* **目录结构**
```shell
.
├── src
│   └── intellipandora
│       ├── CHANGELOG
│       ├── __init__.py
│       ├── common
│       ├── conf
│       ├── core
│       ├── run
│       ├── utils
│       └── version.py
└── test
    └── __init__.py
```

* **说明**
    > 代码都在***src/intellipandora***
  * **core**: 提供自动化核心能力接口
  * **common**: 基础方法封装，提供自动化
  * **run**: 框架的命令行模块
  * **utils**: 框架基础功能，如log、error...
  * **conf**: 配置文件

* **开发手册**
  * [IntelliPandora开发手册(完善中)](./Python_Dev_Standard.md)

### 3.单元测试
> test目录下编写单元测试用例
> 参考 test/testhttp/test_http_get.py
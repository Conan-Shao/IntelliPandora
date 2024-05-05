# 代码和制品管理配置

## 一、PYPI配置
### 1. 登陆gitlab获取 access token.(以gitlab为例)
> 用户设置————访问令牌(access token)————添加token

### 2. 本地创建pypi配置文件 (***.pypirc***)
> 文件中添加 \<user> , \<access token>
* 步骤
```shell
touch ~/.pypirc
vim ~/.pypirc
```
* 配置内容
> 根据需求配置repository地址，需要跟*twine -r* 指定 匹配
```shell
[distutils]
index-servers = local

[local]
repository = https://gitlab.example.com/api/v4/projects/<project_id>/packages/pypi
username = <your_personal_access_token_name>
password = <your_personal_access_token>
```

## 二、pip配置

### 1. 本地创建pip配置文件
> **Window: pip.ini**
> 
> **linux/Mac: pip.conf**

* 步骤
```shell
touch ~/.pip/pip.conf   # linux/mac
New-Item -Type File -Force ~/pip/pip.ini     # powershow, windows
```

* 配置内容
> 公司内部私服user, token 同pypic中配置
```config
[global]
index-url=http://<user_name>:<your_personal_token>@<ip>/api/v4/<project_id>/43/packages/pypi/simple
extra-index-url=
        http://mirrors.aliyun.com/pypi/simple/
        https://pypi.tuna.tsinghua.edu.cn/simple/

[install]
trusted-host= 
        pypi.tuna.tsinghua.edu.cn
        mirrors.aliyun.com
```
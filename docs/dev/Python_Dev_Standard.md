# Python Develop Standard
> Python开发中的命名规范是编写清晰、易维护代码的重要部分。以下是根据PEP 8 — Python官方的风格指南—所提供的一些关键命名规范：
> [Python PEP8 中文](https://github.com/kernellmd/Knowledge/blob/master/Translation/PEP%208%20%E4%B8%AD%E6%96%87%E7%BF%BB%E8%AF%91.md)

## 规范：命名规约

### 避免的命名
不要使用小写l（el），大写O（oh）或者大写I（eye）作为单字符变量名。某些字体中，这些字符和数字0、1无法区分。如果想用l，可以用L代替。

### 包和模块命名
模块名要简短并且全部小写。如果能提高可读性，也可以在模块名中加下划线。Python 包名称也要简短和小写，但不鼓励使用下划线。
```shell
mypackage
```

### 类命名
类命名应使用驼峰命名法。
```shell
class MyClass:
    pass
```

### 函数和变量名
函数名应该小写，必要时可使用下划线分隔单词来提高可读性。
变量名和函数名遵循相同的规约。
```shell
def this_is_demo_function():
    this_is_variable = 10
```

### 函数和方法参数
实例方法的第一参数永远都是self。
类方法的第一个参数永远都是cls。

### 方法命名和实例变量
使用函数命名规约：单词小写，必要时以下划线分隔。
非公共方法和实例变量以下划线打头。

### 常量
常量通常是在模块级别定义的，并且全部采用大写字母，单词之间以下划线分隔。例如：TOTAL MAX_OVERFLOW。
```shell
MAX_OVERFLOW = 100
```

### 异常命名
因为异常也是类，所以类命名规约也使用于异常。但是，如果异常实际上是抛出错误时，那么异常名后应该加上"Error"。
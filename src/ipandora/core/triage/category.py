# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : category.py
@Time  : 2026-08-01
"""


class Category:
    """
    What kind of problem a failure is.

    The distinction that matters operationally is "is this the system under
    test being wrong" versus "is this our harness, our data, or the network".
    A suite that cannot separate those trains people to ignore red builds.
    """

    DEFECT = 'defect'
    """The system under test answered wrongly. Someone should look at the code."""

    CONTRACT = 'contract'
    """The response no longer matches its schema -- an interface changed."""

    ENVIRONMENT = 'environment'
    """Could not reach or talk to the system. Nothing was tested."""

    DATA = 'data'
    """Preconditions were unmet: no test account, no seed data, missing fixture."""

    HARNESS = 'harness'
    """The test itself is broken -- setup blew up, a fixture is missing."""

    INJECTED = 'injected'
    """
    A fault the case injected on purpose (core/faults.py) and the system -- or
    the case's own client -- did not withstand. Not the environment: nothing
    was down that the test did not take down itself.
    """

    UNKNOWN = 'unknown'
    """Not enough signal to say. Deliberately not guessed at."""


class Confidence:
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'


# Whether a category means the system under test is implicated. Everything
# else is our own problem and should not be reported as a product defect.
BLAMES_SYSTEM_UNDER_TEST = {Category.DEFECT, Category.CONTRACT}

NEXT_STEP = {
    Category.DEFECT: '对照需求核对实际值，确认后提缺陷',
    Category.CONTRACT: '确认接口是否改了；重新生成客户端或 schema',
    Category.ENVIRONMENT: '确认被测服务在线、网络可达，然后重跑',
    Category.DATA: '检查这条用例依赖的账号、夹具或数据状态',
    Category.HARNESS: '修测试代码本身——这次没有真正测到被测系统',
    Category.INJECTED: '这是用例自己注入的故障：确认被测系统的重试、超时、降级是否该扛住它，或者用例本该预期这个失败',
    Category.UNKNOWN: '用 explain_failure 看完整的失败原文',
}

LABEL = {
    Category.DEFECT: '产品缺陷',
    Category.CONTRACT: '接口契约',
    Category.ENVIRONMENT: '环境',
    Category.DATA: '测试数据',
    Category.HARNESS: '测试代码',
    Category.INJECTED: '注入的故障',
    Category.UNKNOWN: '待确认',
}
"""What a reader sees. The codes above are what programs compare."""

CONFIDENCE_LABEL = {Confidence.HIGH: '高置信', Confidence.MEDIUM: '中置信',
                    Confidence.LOW: '低置信'}

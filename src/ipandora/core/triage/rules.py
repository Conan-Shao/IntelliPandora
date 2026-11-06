# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : rules.py
@Time  : 2026-08-01

Deterministic failure classification.

Rules first, model second: this runs on every failure, costs nothing, is
reproducible, and covers the cases that have a clear signature. The optional
LLM pass (see ipandora.ai.triage) only ever adds prose on top -- it never
decides a category.
"""
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from ipandora.core.triage.category import (BLAMES_SYSTEM_UNDER_TEST, Category, Confidence,
                                           NEXT_STEP)

# Assertion sources, emitted by the assertion layer as "[FAIL] name (src) | expr"
# Horizontal space only after '|': with \s, a check with an empty expr took
# the next line of the message as its expr. And the expr part is optional.
CHECK_LINE = re.compile(r'\[FAIL\][ \t]*(?P<name>.*?)[ \t]*\((?P<src>\w+)\)(?:[ \t]*\|[ \t]*(?P<expr>.*))?$',
                        re.MULTILINE)

TRANSPORT_MARKERS = ('HttpTimeoutError', 'HttpConnectionError', 'TransportError',
                     'ConnectionError', 'ReadTimeout', 'ConnectTimeout',
                     'could not connect', 'timed out')

# A transport exception that was raised -- its type starting a line of the
# message, as an exception does -- as opposed to the same words quoted inside
# a judgement or a response body.
RAISED_TRANSPORT = re.compile(
    r'^(?:E\s+)?(?:[\w.]+\.)?(HttpTimeoutError|HttpConnectionError|TransportError|'
    r'ConnectionError|ReadTimeout|ConnectTimeout)\b', re.MULTILINE)

# The same exception types named anywhere -- inside an eventually() expr
# that recorded what each read raised. Not the bare phrases: "timed out" in
# a judgement is usually a response body quoting its own upstream.
TRANSPORT_TYPE = re.compile(
    r'\b(HttpTimeoutError|HttpConnectionError|TransportError|ConnectionError|ReadTimeout|'
    r'ConnectTimeout)\b')

# A case that ran out of time, or waited too long for a shared resource, says
# nothing about the system yet. Checked before everything else: a lock timeout
# fails in setup, and would otherwise read as a broken harness.
CASE_TIMEOUT_MARKER = 'Timeout (>'          # pytest-timeout: "Failed: Timeout (>5.0s) from pytest-timeout."
RESOURCE_WAIT_MARKER = 'ipandora: gave up waiting for resource'   # core/runner/plugin.py
LOGIN_MARKER = 'ipandora: login failed'                          # core/auth.py

HARNESS_MARKERS = ('fixture', 'not found', 'ImportError', 'ModuleNotFoundError',
                   'AttributeError', 'TypeError', 'NameError')


@dataclass
class Finding:
    nodeid: str
    category: str
    confidence: str
    reason: str
    """Why this category -- the evidence, not a restatement of the label."""
    next_step: str = ''
    check_sources: List[str] = field(default_factory=list)
    """Which assertion dimensions failed (api/schema/derived/...)."""

    @property
    def blames_system_under_test(self) -> bool:
        return self.category in BLAMES_SYSTEM_UNDER_TEST

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def failed_check_sources(message: str) -> List[str]:
    """
    The `src` of every failed check in an assert_all message.

    This is the payoff from tagging checks with a source: if everything that
    failed is `schema`, the interface drifted; if it is `derived`, business
    logic is wrong. That distinction is free here because it was recorded at
    assertion time.
    """
    _seen = []
    for _match in CHECK_LINE.finditer(message or ''):
        _src = _match.group('src')
        if _src not in _seen:
            _seen.append(_src)
    return _seen


def classify(nodeid: str, outcome: str, message: str, locator_failures=None) -> Finding:
    """
    Classify one case. Pure function of its outcome, its message and, for web
    cases, what core/web.py found out about selectors that matched nothing.
    """
    _message = message or ''

    def _finding(category, confidence, reason, sources=None):
        return Finding(nodeid=nodeid, category=category, confidence=confidence,
                       reason=reason, next_step=NEXT_STEP.get(category, ''),
                       check_sources=sources or [])

    if LOGIN_MARKER in _message:
        # the provider could not log in: the login endpoint is down, or the
        # account is wrong -- either way the system under test was not tested
        if TRANSPORT_TYPE.search(_message) or any(_t in _message for _t in TRANSPORT_MARKERS):
            return _finding(Category.ENVIRONMENT, Confidence.HIGH,
                            '登录没有完成：登录接口连不上，用例没有执行到被测系统')
        return _finding(Category.DATA, Confidence.HIGH,
                        '登录没有完成：账号、口令或登录流程不对（见失败信息），不是被测系统的缺陷')
    if RESOURCE_WAIT_MARKER in _message:
        return _finding(Category.ENVIRONMENT, Confidence.HIGH,
                        '没有开始执行：它声明的共享资源在整个等待期间都被别的用例或运行占着')
    if CASE_TIMEOUT_MARKER in _message and 'pytest-timeout' in _message:
        return _finding(Category.ENVIRONMENT, Confidence.MEDIUM,
                        '用例超过了时间上限。通常是某个依赖不再响应；如果是被测系统自己卡住，那是缺陷')

    _failed_checks = list(CHECK_LINE.finditer(_message))
    _asserted = bool(_failed_checks) or 'AssertionError' in _message \
        or any(_l.lstrip().startswith('assert ') for _l in _message.splitlines())

    _locator = _locator_finding(locator_failures, _message, _asserted)
    if _locator:
        return _finding(*_locator)

    # Nothing reached the system under test. Only when no judgement failed:
    # a failed check means a response came back and was judged, and the words
    # "timed out" inside its expr or the body it quotes ("upstream timed
    # out") are what the system said, not a transport failure. Before, any
    # such message blamed the environment and hid a real defect. A check
    # whose every read was itself a transport error -- eventually() against
    # a node that never answered -- is still the environment.
    _exprs = [(_m.group('expr') or '') for _m in _failed_checks]
    _raised = RAISED_TRANSPORT.search(_message)
    _transport = _raised.group(1) if _raised else \
        next((_m for _m in TRANSPORT_MARKERS if _m in _message), None)
    if _transport and (_raised or not _asserted or (_exprs and all(
            TRANSPORT_TYPE.search(_e) for _e in _exprs))):
        return _finding(Category.ENVIRONMENT, Confidence.HIGH,
                        '传输失败（{}）：没有收到响应，被测系统实际上什么都没测到'.format(_transport))

    # A skipped test is a precondition that was not met, by design -- see
    # require() in the assertion layer.
    if outcome == 'skipped':
        return _finding(Category.DATA, Confidence.HIGH,
                        '前置条件不满足，用例没有执行：{}'.format(
                            _message.strip().splitlines()[0] if _message.strip() else 'skipped'))

    # Setup or teardown blew up: the harness is broken, not the product.
    if outcome == 'error':
        _marker = next((_m for _m in HARNESS_MARKERS if _m in _message), '')
        return _finding(Category.HARNESS, Confidence.HIGH,
                        '用例在测试体之外出错{}，没有调用到被测系统'.format(
                            '（{}）'.format(_marker) if _marker else ''))

    _sources = failed_check_sources(_message)
    if _sources:
        # Only schema checks failed -> the shape changed, not the value.
        if set(_sources) == {'schema'}:
            return _finding(Category.CONTRACT, Confidence.HIGH,
                            '不成立的判定全是 schema 判定：响应不再符合声明的契约', _sources)
        return _finding(Category.DEFECT, Confidence.HIGH,
                        '{} 上的判定不成立：被测系统返回的值与判定不符'.format('/'.join(_sources)), _sources)

    if 'AssertionError' in _message:
        return _finding(Category.DEFECT, Confidence.MEDIUM,
                        '一条普通 assert 不成立；改用 assert_all，失败时会带上实际值和请求证据')

    return _finding(Category.UNKNOWN, Confidence.LOW,
                    '失败信息里没有可识别的特征')


def _locator_finding(failures, message: str = '', asserted: bool = False):
    """
    A selector found nothing. Stale selector, or a missing element?

    Decided where the failure happened, while the page was still there
    (core/web.py): the element the selector used to point at -- its role and
    accessible name, remembered from a passing run -- was searched for.

    Only a selector the failure is about. A locator error the test caught
    and handled -- `try: page.click('#cookie-banner') except Error: pass` --
    is recorded too, and the first one recorded used to decide the verdict:
    a case failing on a wrong total was blamed on a stale cookie-banner
    selector. Playwright names the selector in its error, so the selector
    has to appear in the failure message; failing that, the latest locator
    failure is used only when no judgement failed for some other reason.
    """
    if not failures:
        return None
    _named = [_f for _f in failures if _f.get('selector') and _f['selector'] in (message or '')]
    if _named:
        _f = _named[-1]
    elif not asserted:
        _f = failures[-1]
    else:
        return None
    _selector = _f.get('selector', '?')
    _identity = _f.get('identity') or {}
    _what = '{} "{}"'.format(_identity.get('role', '?'), _identity.get('name', '?'))
    if _f.get('verdict') == 'stale_selector':
        return (Category.HARNESS, Confidence.HIGH,
                '选择器 {!r} 失效：它什么也没找到，但页面上仍有 {}，就是它上次通过时指向的元素。'
                '改选择器即可，产品没有问题'.format(_selector, _what))
    if _f.get('verdict') == 'missing':
        return (Category.DEFECT, Confidence.LOW,
                '待确认：{!r} 什么也没找到，页面上也没有 {}，而这条用例上次通过时它还在。'
                '可能被删掉或改了名：除非是有意的改动，否则是产品缺陷。请看截图'.format(
                    _selector, _what))
    return (Category.UNKNOWN, Confidence.LOW,
            '待确认：{!r} 什么也没找到，而且没有它在通过的运行里指向什么的记录，'
            '分不清是选择器失效还是元素真的没了。请看截图'.format(_selector))


@dataclass
class TriageReport:
    findings: List[Finding] = field(default_factory=list)
    analysis: str = ''
    """Optional natural-language root cause. Empty unless AI triage ran."""

    @property
    def by_category(self) -> Dict[str, int]:
        _counts = {}
        for _f in self.findings:
            _counts[_f.category] = _counts.get(_f.category, 0) + 1
        return _counts

    @property
    def product_failures(self) -> List[Finding]:
        """Failures that implicate the system under test rather than us."""
        return [_f for _f in self.findings if _f.blames_system_under_test]

    def headline(self) -> str:
        if not self.findings:
            return 'nothing to triage'
        _parts = ['{} {}'.format(_n, _c) for _c, _n in sorted(self.by_category.items())]
        return ', '.join(_parts)

    def to_dict(self) -> Dict[str, Any]:
        _out = {
            'headline': self.headline(),
            'by_category': self.by_category,
            'blames_system_under_test': len(self.product_failures),
            'findings': [_f.to_dict() for _f in self.findings],
        }
        if self.analysis:
            _out['analysis'] = self.analysis
        return _out


def triage(result, include_skipped: bool = False) -> TriageReport:
    """
    Classify every failure in a RunResult.

    Deterministic and offline. Accepts anything exposing `failures` with
    nodeid/outcome/message, so it does not bind the triage rules to the runner.

    :param include_skipped: also classify skipped cases. Off by default -- a
        skip is a met design goal, not a failure -- but a suite that is mostly
        skipping is worth looking at, and this surfaces that.
    """
    _cases = list(getattr(result, 'failures', []))
    if include_skipped:
        _cases += [_c for _c in getattr(result, 'cases', [])
                   if _c.outcome == 'skipped']
    return TriageReport(findings=[
        classify(_c.nodeid, _c.outcome, _c.message,
                 locator_failures=getattr(_c, 'locator_failures', None))
        for _c in _cases])

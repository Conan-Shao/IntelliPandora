#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Measure uiautomator2 against Appium (UiAutomator2 driver) on one device and one screen.

Usage: bench_android.py [--serial S] [--appium URL] [--package P] [--activity A]
                        [--rounds N] [--reps N] [--out JSON] [--markdown PATH]

M5c in docs/design/decisions/14: the framework drives Android through
uiautomator2 and keeps Appium as the alternative backend. Vendors who sell one
or the other publish per-call figures; this measures both on the same
emulator, screen and operations, in CI (.github/workflows/android-bench.yml).

What is measured, per tool, with the client the user would write:

- session: from nothing to the app on screen. uiautomator2: connect, wait
  for the device service, start the app. Appium: create the session with
  appPackage/appActivity, which starts the app. The first round is reported
  apart: it installs the device-side services (u2.jar; Appium's two server
  APKs and io.appium.settings).
- find (present) / find (absent): one lookup by text, no waiting. Absent is
  the cost of a check that fails -- what every "is it there yet" poll pays.
- read text: find the widget and read its text, as one would in a test.
  uiautomator2 does it in one call; Appium in two (find, then getText).
- hierarchy: the whole UI tree as XML.
- screenshot: the image, as each client hands it over: uiautomator2 a
  decoded PIL image (the device sends a JPEG), Appium PNG bytes.

Every result is checked (present is found, absent is not, the text read is
the text looked for, the XML is a hierarchy, the PNG is a PNG): a fast wrong
answer is not a measurement. The tools take turns, a block each per round,
so drift on the device (caches, thermal, the emulator's own load) falls on
both. They cannot run at the same time: Android lets one process hold
UiAutomation, so each block stops the other tool's device service first.
"""
import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
import xml.etree.ElementTree as ET

SETTINGS = 'com.android.settings'
SETTINGS_ACTIVITY = '.Settings'
ABSENT = 'ipandora-no-such-widget'
OPERATIONS = ('find (present)', 'find (absent)', 'read text', 'hierarchy', 'screenshot')
PNG = b'\x89PNG\r\n\x1a\n'
APPIUM_SERVER_PACKAGES = ('io.appium.uiautomator2.server', 'io.appium.uiautomator2.server.test')


class BenchError(Exception):
    """A tool gave a wrong answer, or could not be measured."""


# -- statistics ----------------------------------------------------------------

def percentile(samples, q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty sequence."""
    _s = sorted(samples)
    if not _s:
        raise ValueError('no samples')
    return _s[max(0, math.ceil(q / 100.0 * len(_s)) - 1)]


def stats(samples) -> dict:
    """n, median, p90, mean, min and max of millisecond samples, rounded to 0.1 ms."""
    if not samples:
        raise ValueError('no samples')
    return {'n': len(samples), 'median': round(statistics.median(samples), 1),
            'p90': round(percentile(samples, 90), 1), 'mean': round(statistics.fmean(samples), 1),
            'min': round(min(samples), 1), 'max': round(max(samples), 1)}


# -- measuring -----------------------------------------------------------------

def timed(fn, check, clock=time.perf_counter):
    """(milliseconds, result) of one call; BenchError if check(result) is false."""
    _t0 = clock()
    _result = fn()
    _ms = (clock() - _t0) * 1000.0
    if not check(_result):
        raise BenchError('wrong answer: {!r}'.format(_result if not isinstance(_result, (bytes, str))
                                                      else _result[:80]))
    return _ms, _result


def measure(fn, check, reps: int, warmup: int = 3, clock=time.perf_counter):
    """Millisecond samples of `reps` checked calls, after `warmup` checked calls that are not kept."""
    for _ in range(warmup):
        timed(fn, check, clock)
    return [timed(fn, check, clock)[0] for _ in range(reps)]


def checks(name: str) -> dict:
    """operation -> predicate on its result, for the widget text `name`."""
    return {
        'find (present)': bool,
        'find (absent)': lambda r: r is False or r == [],
        'read text': lambda r: r == name,
        'hierarchy': lambda r: isinstance(r, str) and '<hierarchy' in r,
        'screenshot': lambda r: (bytes(r[:8]) == PNG if isinstance(r, (bytes, bytearray))
                                 else getattr(r, 'size', (0, 0))[0] > 0),
    }


def run_rounds(clients, rounds: int, reps: int, warmup: int = 3, clock=time.perf_counter,
               log=lambda _m: None):
    """
    {tool: {'session_cold': ms, 'session': [ms...], op: [ms...]}} over
    `rounds` rounds, each client taking one block per round, in turn.

    A client is an object with `name`, `prepare()` (stop whatever would hold
    the device), `start()` (open a session; returns nothing), `ops(name)`
    ({operation: callable}) and `stop()`. The widget text is found by the
    first client's `discover()` and used by all of them.
    """
    if rounds < 1 or reps < 1:
        raise ValueError('rounds and reps must be at least 1')
    _out = {_c.name: {'session': []} for _c in clients}
    _name = None
    for _round in range(rounds):
        for _c in clients:
            _c.prepare()
            _ms, _ = timed(_c.start, lambda _r: True, clock)
            if _round == 0:
                _out[_c.name]['session_cold'] = _ms
            else:
                _out[_c.name]['session'].append(_ms)
            try:
                if _name is None:
                    _name = _c.discover()
                    log('widget text used: {!r}'.format(_name))
                _ops, _checks = _c.ops(_name), checks(_name)
                for _op in OPERATIONS:
                    _out[_c.name].setdefault(_op, []).extend(
                        measure(_ops[_op], _checks[_op], reps, warmup, clock))
                    log('{} round {} {}: done'.format(_c.name, _round + 1, _op))
            finally:
                _c.stop()
    return _out, _name


def summarize(raw) -> dict:
    """{tool: {op: stats}} with the cold session as a single value."""
    _out = {}
    for _tool, _ops in raw.items():
        _out[_tool] = {}
        for _op, _samples in _ops.items():
            if _op == 'session_cold':
                _out[_tool][_op] = round(_samples, 1)
            elif _samples:
                _out[_tool][_op] = stats(_samples)
    return _out


def markdown(summary, meta) -> str:
    """The comparison table, in Chinese like the rest of the docs."""
    _tools = list(summary)
    _base, _other = (_tools + [None])[:2]
    _lines = ['## uiautomator2 与 Appium 实测对比', '',
              '设备：{device}；每项每轮 {reps} 次（先热身 {warmup} 次不计），共 {rounds} 轮，两者轮流。'
              '单位毫秒，中位数（p90）。'.format(**meta), '',
              '| 操作 | {} |'.format(' | '.join(_tools)) + (' {} / {} |'.format(_other, _base) if _other else ''),
              '|---|' + '---|' * (len(_tools) + (1 if _other else 0))]
    for _op in ('session',) + OPERATIONS:
        _cells = []
        for _t in _tools:
            _s = summary[_t].get(_op)
            _cells.append('{} ({})'.format(_s['median'], _s['p90']) if _s else '—')
        _row = '| {} | {} |'.format('会话（热）' if _op == 'session' else _op, ' | '.join(_cells))
        if _other:
            _a, _b = summary[_other].get(_op), summary[_base].get(_op)
            _row += ' {} |'.format('{:.1f}×'.format(_a['median'] / _b['median'])
                                   if _a and _b and _b['median'] else '—')
        _lines.append(_row)
    _lines.append('| 会话（冷，第一轮） | {} |'.format(' | '.join(
        str(summary[_t].get('session_cold', '—')) for _t in _tools)) + (' — |' if _other else ''))
    return '\n'.join(_lines) + '\n'


# -- the two clients -------------------------------------------------------------

def unique_text(xml: str, package: str) -> str:
    """A widget text of `package` that occurs exactly once on screen, usable in a UiSelector."""
    # the device's own UI dump, from the device under test
    _root = ET.fromstring(xml)
    _texts = [(_n.get('text') or '').strip() for _n in _root.iter('node') if _n.get('package') == package]
    for _t in _texts:
        if _t and _texts.count(_t) == 1 and '"' not in _t and '\\' not in _t:
            return _t
    raise BenchError('no widget text on screen occurs exactly once')


def adb(serial):
    import adbutils
    return adbutils.adb.device(serial) if serial else adbutils.adb.device()


def device_name(serial) -> str:
    """Model, Android version and API level, read with getprop: no UiAutomation needed."""
    _d = adb(serial)
    _get = lambda _k: _d.shell(['getprop', _k]).strip()  # noqa: E731
    return '{} (Android {}, API {})'.format(_get('ro.product.model'), _get('ro.build.version.release'),
                                            _get('ro.build.version.sdk'))


class U2:
    name = 'uiautomator2'

    def __init__(self, serial, package, activity):
        self.serial, self.package, self.activity, self.d = serial, package, activity, None

    def prepare(self):
        # Appium's server keeps UiAutomation after the session ends; uiautomator2 could not start
        for _p in APPIUM_SERVER_PACKAGES + (self.package,):
            adb(self.serial).shell(['am', 'force-stop', _p])

    def start(self):
        import uiautomator2
        self.d = uiautomator2.connect(self.serial)
        self.d.info                                     # the device service is up
        self.d.app_start(self.package, self.activity, wait=True)
        if not self.d(packageName=self.package).wait(timeout=30):
            raise BenchError('{} did not come up'.format(self.package))

    def discover(self):
        return unique_text(self.d.dump_hierarchy(), self.package)

    def ops(self, name):
        _d = self.d
        return {
            'find (present)': lambda: _d(text=name).exists,
            'find (absent)': lambda: _d(text=ABSENT).exists,
            'read text': lambda: _d(text=name).get_text(),
            'hierarchy': lambda: _d.dump_hierarchy(),
            'screenshot': lambda: _d.screenshot(),
        }

    def stop(self):
        if self.d is not None:
            self.d.stop_uiautomator()
            self.d = None


class Appium:
    name = 'Appium'

    def __init__(self, url, serial, package, activity):
        self.url, self.serial, self.package, self.activity, self.driver = url, serial, package, activity, None

    def prepare(self):
        # uiautomator2's device service is gone: U2.stop() waits until it no longer answers
        adb(self.serial).shell(['am', 'force-stop', self.package])

    def start(self):
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        _o = UiAutomator2Options()
        if self.serial:
            _o.udid = self.serial
        _o.app_package, _o.app_activity = self.package, self.activity
        _o.no_reset = True
        _o.new_command_timeout = 300
        # an emulator in CI installs the server APKs slowly the first time
        _o.uiautomator2_server_install_timeout = 120000
        _o.uiautomator2_server_launch_timeout = 120000
        _o.adb_exec_timeout = 120000
        self.driver = webdriver.Remote(self.url, options=_o)
        self.driver.implicitly_wait(0)

    def discover(self):
        return unique_text(self.driver.page_source, self.package)

    def ops(self, name):
        from appium.webdriver.common.appiumby import AppiumBy
        _d = self.driver
        _by = AppiumBy.ANDROID_UIAUTOMATOR
        _present = 'new UiSelector().text("{}")'.format(name)
        _absent = 'new UiSelector().text("{}")'.format(ABSENT)
        return {
            'find (present)': lambda: _d.find_elements(_by, _present),
            'find (absent)': lambda: _d.find_elements(_by, _absent),
            'read text': lambda: _d.find_element(_by, _present).text,
            'hierarchy': lambda: _d.page_source,
            'screenshot': lambda: _d.get_screenshot_as_png(),
        }

    def stop(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None


def versions() -> dict:
    from importlib import metadata
    _out = {'python': platform.python_version()}
    for _dist in ('uiautomator2', 'adbutils', 'Appium-Python-Client', 'selenium'):
        try:
            _out[_dist] = metadata.version(_dist)
        except metadata.PackageNotFoundError:
            _out[_dist] = None
    return _out


def main(argv) -> int:
    _p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    _p.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL') or None)
    _p.add_argument('--appium', default='http://127.0.0.1:4723')
    _p.add_argument('--package', default=SETTINGS)
    _p.add_argument('--activity', default=SETTINGS_ACTIVITY)
    _p.add_argument('--rounds', type=int, default=3)
    _p.add_argument('--reps', type=int, default=30)
    _p.add_argument('--warmup', type=int, default=3)
    _p.add_argument('--out', default=None, help='write raw samples and the summary here, as JSON')
    _p.add_argument('--markdown', default=None, help='append the table here (e.g. $GITHUB_STEP_SUMMARY)')
    _opts = _p.parse_args(argv)

    _clients = [U2(_opts.serial, _opts.package, _opts.activity),
                Appium(_opts.appium, _opts.serial, _opts.package, _opts.activity)]
    _raw, _name = run_rounds(_clients, _opts.rounds, _opts.reps, _opts.warmup,
                             log=lambda _m: print(_m, flush=True))
    _meta = {'device': device_name(_opts.serial),
             'rounds': _opts.rounds, 'reps': _opts.reps, 'warmup': _opts.warmup,
             'widget_text': _name, 'versions': versions()}
    _summary = summarize(_raw)
    _table = markdown(_summary, _meta)
    print(_table)
    if _opts.out:
        with open(_opts.out, 'w', encoding='utf-8') as _f:
            json.dump({'meta': _meta, 'summary': _summary, 'raw': _raw}, _f, ensure_ascii=False, indent=1)
    if _opts.markdown:
        with open(_opts.markdown, 'a', encoding='utf-8') as _f:
            _f.write(_table)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

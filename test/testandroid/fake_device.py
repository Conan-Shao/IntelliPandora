# -*- coding: utf-8 -*-
"""
A stand-in for uiautomator2.Device: the parts core/android.py and a test's
`device(text=...)` reach. Selectors are uiautomator2's own UiObject and
Selector, so what is patched is the real code; only the device answers.
"""
from types import SimpleNamespace

from uiautomator2._selector import Selector, UiObject

PACKAGE = 'com.example.shop'

HIERARCHY = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.example.shop" text="" content-desc="" resource-id="">
    <node class="android.widget.TextView" text="Welcome" content-desc="" resource-id="com.example.shop:id/title"/>
    <node class="android.widget.Button" text="" content-desc="Login" resource-id="com.example.shop:id/sign_in"/>
  </node>
</hierarchy>'''

APP_LOG = '''11-07 12:00:01.100  4242  4242 I ShopActivity: onCreate token=abc
11-07 12:00:01.200  1111  1111 I OtherApp: not ours
11-07 12:00:01.300  4242  4250 D ShopNetwork: GET /cart Authorization: Bearer sk-live-should-not-leak
'''

CRASH_LOG = APP_LOG + '''11-07 12:00:02.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main
11-07 12:00:02.000  4242  4242 E AndroidRuntime: Process: com.example.shop, PID: 4242
11-07 12:00:02.000  4242  4242 E AndroidRuntime: java.lang.NullPointerException: cart was null
11-07 12:00:02.000  4242  4242 E AndroidRuntime: 	at com.example.shop.Cart.total(Cart.java:42)
'''


class _Rpc:
    def __init__(self, device):
        self.device = device

    def waitForExists(self, selector, ms, http_timeout=None):
        return self.device.present(selector)

    def exist(self, selector):
        return self.device.present(selector)

    def waitUntilGone(self, selector, ms, http_timeout=None):
        return not self.device.present(selector)


DEVICES = []
"""Every stand-in made, in order: what a test reads back after a run."""


class FakeDevice:

    def __init__(self, serial='emulator-5554'):
        DEVICES.append(self)
        self.serial = serial
        self.wait_timeout = 0.01
        self.jsonrpc = _Rpc(self)
        self.calls = []
        self.timeouts = []
        self.shown = {'Welcome'}
        self.log = APP_LOG
        self.hierarchy = HIERARCHY
        self.fail_screenshot = False

    def __call__(self, **kwargs):
        return UiObject(self, Selector(**kwargs))

    def present(self, selector) -> bool:
        return any(selector.get(_k) in self.shown for _k in ('text', 'description'))

    def shell(self, args, timeout=60):
        self.calls.append(('shell', tuple(args)))
        self.timeouts.append(timeout)
        if args[:1] == ['date']:
            return SimpleNamespace(output='1762516800\n', exit_code=0)
        if args[:1] == ['pidof']:
            return SimpleNamespace(output='4242\n', exit_code=0)
        if args[:1] == ['logcat']:
            return SimpleNamespace(output=self.log, exit_code=0)
        return SimpleNamespace(output='', exit_code=0)

    def app_install(self, path):
        self.calls.append(('install', path))

    def app_start(self, package, activity=None, wait=False, stop=False):
        self.calls.append(('start', package, stop))

    def app_stop(self, package):
        self.calls.append(('stop', package))

    def app_clear(self, package):
        self.calls.append(('clear', package))

    def screenshot(self, filename=None):
        if self.fail_screenshot:
            raise RuntimeError('screencap failed')
        with open(filename, 'wb') as _f:
            _f.write(b'\x89PNG\r\n\x1a\n' + b'0' * 16)

    def dump_hierarchy(self, *args, **kwargs):
        return self.hierarchy

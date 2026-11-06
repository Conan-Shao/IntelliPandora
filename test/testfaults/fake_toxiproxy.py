# -*- coding: utf-8 -*-
"""
A stand-in for Toxiproxy, for tests: the HTTP API subset core/faults.py uses,
and real TCP forwarding that honours latency (either stream), reset_peer, timeout and a
disabled proxy. Not a product: just enough to see a fault take effect.
"""
import json
import re
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Proxy:
    def __init__(self, name, listen, upstream):
        self.name, self.upstream, self.enabled, self.toxics = name, upstream, True, []
        _host, _port = listen.rsplit(':', 1)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((_host or '127.0.0.1', int(_port)))
        self.sock.listen(16)
        self.listen = '{}:{}'.format(*self.sock.getsockname())
        threading.Thread(target=self._accept, daemon=True).start()

    def toxic(self, kind):
        return next((_t for _t in self.toxics if _t['type'] == kind), None)

    def _accept(self):
        while True:
            try:
                _client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(_client,), daemon=True).start()

    def _serve(self, client):
        if not self.enabled:
            client.close()
            return
        _reset = self.toxic('reset_peer')
        if _reset:
            time.sleep(_reset['attributes'].get('timeout', 0) / 1000.0)
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            client.close()                      # RST
            return
        _timeout = self.toxic('timeout')
        if _timeout:
            _ms = _timeout['attributes'].get('timeout', 0)
            time.sleep(_ms / 1000.0 if _ms else 30)
            client.close()
            return
        _host, _port = self.upstream.rsplit(':', 1)
        _up = socket.create_connection((_host, int(_port)))
        threading.Thread(target=self._pipe, args=(client, _up, 'upstream'), daemon=True).start()
        self._pipe(_up, client, 'downstream')

    def _pipe(self, src, dst, stream):
        try:
            while True:
                _data = src.recv(65536)
                if not _data:
                    break
                _lat = next((_t for _t in self.toxics if _t['type'] == 'latency'
                             and _t.get('stream', 'downstream') == stream), None)
                if _lat:
                    time.sleep(_lat['attributes'].get('latency', 0) / 1000.0)
                dst.sendall(_data)
        except OSError:
            pass
        finally:
            for _s in (src, dst):
                try:
                    _s.close()
                except OSError:
                    pass

    def as_dict(self):
        return {'name': self.name, 'listen': self.listen, 'upstream': self.upstream, 'enabled': self.enabled,
                'toxics': list(self.toxics)}


class FakeToxiproxy:
    def __init__(self):
        self.proxies = {}
        self.calls = []
        _fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, code, body=None):
                _data = json.dumps(body).encode() if body is not None else b''
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(_data)))
                self.end_headers()
                self.wfile.write(_data)

            def _body(self):
                _n = int(self.headers.get('Content-Length') or 0)
                return json.loads(self.rfile.read(_n) or b'{}')

            def do_GET(self):
                _fake.calls.append(('GET', self.path))
                if self.path == '/version':
                    _data = b'fake-2.0'
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(_data)))
                    self.end_headers()
                    return self.wfile.write(_data)
                if self.path == '/proxies':
                    return self._reply(200, {_n: _p.as_dict() for _n, _p in _fake.proxies.items()})
                return self._reply(404, {'error': 'not found'})

            def do_POST(self):
                _body = self._body()
                _fake.calls.append(('POST', self.path, _body))
                if self.path == '/proxies':
                    _p = _Proxy(_body['name'], _body['listen'], _body['upstream'])
                    _fake.proxies[_p.name] = _p
                    return self._reply(201, _p.as_dict())
                _m = re.fullmatch(r'/proxies/([^/]+)/toxics', self.path)
                if _m:
                    _p = _fake.proxies.get(_m.group(1))
                    if _p is None:
                        return self._reply(404, {'error': 'proxy not found'})
                    if any(_t['name'] == _body['name'] for _t in _p.toxics):
                        return self._reply(409, {'error': 'toxic already exists'})
                    _p.toxics.append(_body)
                    return self._reply(200, _body)
                _m = re.fullmatch(r'/proxies/([^/]+)', self.path)
                if _m and _m.group(1) in _fake.proxies:
                    _p = _fake.proxies[_m.group(1)]
                    if 'enabled' in _body:
                        _p.enabled = bool(_body['enabled'])
                    if 'upstream' in _body:
                        _p.upstream = _body['upstream']
                    return self._reply(200, _p.as_dict())
                return self._reply(404, {'error': 'not found'})

            def do_DELETE(self):
                _fake.calls.append(('DELETE', self.path))
                _m = re.fullmatch(r'/proxies/([^/]+)/toxics/([^/]+)', self.path)
                if _m and _m.group(1) in _fake.proxies:
                    _p = _fake.proxies[_m.group(1)]
                    _before = len(_p.toxics)
                    _p.toxics = [_t for _t in _p.toxics if _t['name'] != _m.group(2)]
                    return self._reply(204 if len(_p.toxics) < _before else 404)
                _m = re.fullmatch(r'/proxies/([^/]+)', self.path)
                if _m and _m.group(1) in _fake.proxies:
                    _fake.proxies.pop(_m.group(1)).sock.close()
                    return self._reply(204)
                return self._reply(404)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:{}'.format(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        for _p in self.proxies.values():
            _p.sock.close()

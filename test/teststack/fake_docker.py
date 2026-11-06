# -*- coding: utf-8 -*-
"""
A stand-in for the docker CLI, for the unit tests of core/stack.py: answers
the few commands the module runs from a JSON behaviour file ($FAKE_DOCKER)
and appends each call -- arguments and working directory -- to its log.
Not a product: just enough to see what the module asks for and how it reads
the answers, without starting a container.
"""
import json
import os
import sys
import time


def main(argv):
    with open(os.environ['FAKE_DOCKER'], encoding='utf-8') as _f:
        _b = json.load(_f)
    with open(_b['log'], 'a', encoding='utf-8') as _f:
        _f.write(json.dumps({'args': argv, 'cwd': os.getcwd(),
                             'env': {_k: os.environ.get(_k, '') for _k in _b.get('record_env', [])}}) + '\n')
    if argv[:1] == ['info']:
        print(_b.get('daemon', '29.9.2'))
        return 0 if _b.get('daemon', '29.9.2') else 1
    if argv[:1] == ['sleep']:
        time.sleep(float(argv[1]))
        return 0
    if argv[:1] != ['compose']:
        return 2
    _rest = argv[1:]
    while _rest[:1] in (['-p'], ['-f']):
        _rest = _rest[2:]
    _verb = _rest[0] if _rest else ''
    if _verb == 'version':
        print(_b.get('version', '2.29.1'))
        return 0
    if _verb == 'ls':
        print(json.dumps(_b.get('projects', [])) if 'projects_text' not in _b else _b['projects_text'])
        return 0
    if _verb == 'up':
        if _b.get('up_rc', 0):
            sys.stderr.write(_b.get('up_stderr', 'dependency failed to start'))
        return _b.get('up_rc', 0)
    if _verb == 'ps':
        for _row in _b.get('ps', []):
            print(json.dumps(_row))
        return 0
    if _verb == 'logs':
        _service = _rest[-1] if _rest[-1] in _b.get('logs', {}) else ''
        sys.stdout.write(_b.get('logs', {}).get(_service, ''))
        return 0
    if _verb == 'config':
        print('\n'.join(_b.get('services', ['web'])))
        return 0
    if _verb == 'port':
        _answer = _b.get('ports', {}).get('{}:{}'.format(_rest[-2], _rest[-1]))
        if _answer is None:
            sys.stderr.write('no port {} for {}'.format(_rest[-1], _rest[-2]))
            return 1
        print(_answer)
        return 0
    if _verb == 'down':
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

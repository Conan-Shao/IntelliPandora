# -*- coding: utf-8 -*-
"""
A stand-in docker for core/netem.py: `docker run ... --entrypoint tc IMAGE qdisc ...`
against qdiscs kept in a JSON file ($FAKE_DOCKER_STATE), per container and
interface. The file's `containers` are the ones that exist; `behaviour` can
be fail-replace (tc refuses) or not-shown (tc show prints no netem).
"""
import json
import os
import sys


def main(argv):
    _path = os.environ['FAKE_DOCKER_STATE']
    _state = json.load(open(_path, encoding='utf-8')) if os.path.exists(_path) else {}
    _state.setdefault('qdiscs', {})
    _state.setdefault('calls', []).append(argv)
    _state.setdefault('containers', [])
    try:
        if argv[:2] != ['run', '--rm'] or '--entrypoint' not in argv:
            print('unexpected: {}'.format(argv), file=sys.stderr)
            return 2
        _target = argv[argv.index('--network') + 1].split(':', 1)[1]
        if '--cap-add' not in argv or argv[argv.index('--cap-add') + 1] != 'NET_ADMIN':
            print('RTNETLINK answers: Operation not permitted', file=sys.stderr)
            return 2
        if _target not in _state['containers']:
            print('docker: Error response from daemon: No such container: {}.'.format(_target), file=sys.stderr)
            return 125
        _tc = argv[argv.index('--entrypoint') + 3:]          # after 'tc' and the image
        _verb, _dev = _tc[1], _tc[3]
        _key = '{}/{}'.format(_target, _dev)
        _behaviour = _state.get('behaviour', '')
        if _verb == 'replace':
            if _behaviour == 'fail-replace':
                print('Error: Exclusivity flag on, cannot modify.', file=sys.stderr)
                return 2
            _state['qdiscs'][_key] = _tc[_tc.index('netem') + 1:]
            return 0
        if _verb == 'show':
            if _key in _state['qdiscs'] and _behaviour != 'not-shown':
                print('qdisc netem 8001: root refcnt 2 limit 1000 {}'.format(' '.join(_state['qdiscs'][_key])))
            else:
                print('qdisc noqueue 0: root refcnt 2')
            return 0
        if _verb == 'del':
            if _key not in _state['qdiscs']:
                print('Error: Cannot delete qdisc with handle of zero.', file=sys.stderr)
                return 2
            del _state['qdiscs'][_key]
            return 0
        print('unknown tc {}'.format(_tc), file=sys.stderr)
        return 2
    finally:
        with open(_path, 'w', encoding='utf-8') as _f:
            json.dump(_state, _f)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

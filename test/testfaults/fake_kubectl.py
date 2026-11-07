# -*- coding: utf-8 -*-
"""
A stand-in kubectl for core/chaosmesh.py: the Chaos objects live in a JSON
file ($FAKE_KUBECTL_STATE). What Chaos Mesh would do is set by the file's
`behaviour`: inject (AllInjected), never (stays not injected), noselect (no
pod matches), fail-apply / fail-delete (kubectl errors).

Run as: python fake_kubectl.py --context CTX <verb> ...
"""
import json
import os
import sys


def _load(path):
    if not os.path.exists(path):
        return {'objects': {}, 'calls': [], 'behaviour': 'inject'}
    with open(path, encoding='utf-8') as _f:
        return json.load(_f)


def _save(path, state):
    with open(path, 'w', encoding='utf-8') as _f:
        json.dump(state, _f)


def _key(resource, namespace, name):
    return '{}/{}/{}'.format(resource, namespace, name)


def main(argv):
    _path = os.environ['FAKE_KUBECTL_STATE']
    _state = _load(_path)
    _state['calls'].append(argv)
    if argv[:1] != ['--context']:
        _save(_path, _state)
        print('no --context', file=sys.stderr)
        return 2
    _args = argv[2:]
    _verb = _args[0]
    _behaviour = _state.get('behaviour', 'inject')
    try:
        if _verb == 'apply':
            if _behaviour == 'fail-apply':
                print('error: admission webhook denied the request', file=sys.stderr)
                return 1
            _obj = json.loads(sys.stdin.read())
            _resource = {'NetworkChaos': 'networkchaos', 'PodChaos': 'podchaos'}[_obj['kind']]
            _obj['status'] = {'conditions': [
                {'type': 'Selected', 'status': 'False' if _behaviour == 'noselect' else 'True'},
                {'type': 'AllInjected', 'status': 'True' if _behaviour == 'inject' else 'False'}]}
            _state['objects'][_key(_resource, _obj['metadata']['namespace'], _obj['metadata']['name'])] = _obj
            print('{}.chaos-mesh.org/{} created'.format(_resource, _obj['metadata']['name']))
            return 0
        if _verb == 'get' and '-A' in _args:
            _resources = _args[1].split(',')
            _label = _args[_args.index('-l') + 1]
            _k, _v = _label.split('=', 1)
            _items = [_o for _key_, _o in sorted(_state['objects'].items())
                      if _key_.split('/')[0] in _resources and (_o['metadata'].get('labels') or {}).get(_k) == _v]
            print(json.dumps({'items': _items}))
            return 0
        if _verb == 'get':
            _resource, _name = _args[1], _args[2]
            _ns = _args[_args.index('-n') + 1]
            _obj = _state['objects'].get(_key(_resource, _ns, _name))
            if _obj is None:
                print('Error from server (NotFound)', file=sys.stderr)
                return 1
            print(json.dumps(_obj))
            return 0
        if _verb == 'delete':
            if _behaviour == 'fail-delete':
                print('error: the server is currently unable to handle the request', file=sys.stderr)
                return 1
            _resource, _name = _args[1], _args[2]
            _ns = _args[_args.index('-n') + 1]
            _state['objects'].pop(_key(_resource, _ns, _name), None)
            return 0
        print('unknown verb {}'.format(_verb), file=sys.stderr)
        return 2
    finally:
        _save(_path, _state)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

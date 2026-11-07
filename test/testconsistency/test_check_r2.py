# -*- coding: utf-8 -*-
"""
@File  : test_check_r2.py
@Time  : 2026-11-07

Gaps found by mutation testing core/consistency.py (R2): what History.check()
asks elle-cli for, what its judgement is called -- the claim is what the
judgement inventory compares, so it must change when the model or the
consistency models do -- and the evidence of each verdict. The checker
itself is replaced here; test_consistency.py runs the real one.
"""
import json
import re
import os
import subprocess

import pytest

from ipandora.core import consistency
from ipandora.core.consistency import History


class Checker:
    """Stands in for `java -jar elle-cli`: records the command, its file and its options."""

    def __init__(self, monkeypatch, result=None, stdout=None, returncode=0, stderr='', raises=None):
        self.calls = []
        monkeypatch.setattr(consistency, 'checker', lambda: ('/opt/java', '/opt/elle-cli.jar'))

        def _run(cmd, **kw):
            self.calls.append({'cmd': cmd, 'kw': kw, 'file': open(cmd[-1], encoding='utf-8').read(),
                               'cwd_is_files_dir': kw.get('cwd') == os.path.dirname(cmd[-1])})
            if raises:
                raise raises
            return subprocess.CompletedProcess(cmd, returncode, json.dumps(result) if stdout is None else stdout,
                                               stderr)
        monkeypatch.setattr(consistency.subprocess, 'run', _run)


def _history(*ops):
    _h = History()
    for _f, _v in ops or [('write', 1)]:
        _h.call(_f, _v, lambda: None)
    return _h


class TestWhatIsAsked:

    def test_the_command_model_options_and_file(self, monkeypatch):
        _c = Checker(monkeypatch, {'valid?': True})
        _h = _history(('append', [[consistency.append(1, 2)]]))
        _h.check('list-append', consistency_models=['serializable', 'strict-serializable'], anomalies=['G0', 'G1c'])
        _call = _c.calls[0]
        assert _call['cmd'][:-1] == ['/opt/java', '-jar', '/opt/elle-cli.jar', '--model', 'list-append',
                                     '--output', 'json',
                                     '--consistency-models', 'serializable', '--consistency-models',
                                     'strict-serializable', '--anomalies', 'G0', '--anomalies', 'G1c']
        assert os.path.basename(_call['cmd'][-1]) == 'history.edn' and _call['file'] == _h.to_edn()
        assert _call['cwd_is_files_dir'] and _call['kw']['timeout'] == 300
        assert _call['kw']['capture_output'] is True and _call['kw']['text'] is True
        assert 'shell' not in _call['kw']
        assert not os.path.exists(os.path.dirname(_call['cmd'][-1]))       # the work directory is removed

    def test_no_options_without_models_or_anomalies(self, monkeypatch):
        _c = Checker(monkeypatch, {'valid?': True})
        _history().check('cas-register', timeout=7)
        assert _c.calls[0]['cmd'][3:-1] == ['--model', 'cas-register', '--output', 'json']
        assert _c.calls[0]['kw']['timeout'] == 7

    def test_an_unknown_model_names_the_known_ones(self):
        with pytest.raises(ValueError) as _e:
            History().check('linearizable')
        assert str(_e.value) == "unknown model 'linearizable'; one of {}".format(', '.join(consistency.MODELS))


class TestWhatItIsCalled:

    def test_name_and_claim_carry_the_model_and_the_consistency_models(self, monkeypatch):
        Checker(monkeypatch, {'valid?': True})
        _plain = _history().check('cas-register')
        assert (_plain.name, _plain.claim) == ('历史符合 cas-register 模型', 'history consistent under cas-register')
        _models = _history().check('rw-register', consistency_models=['serializable', 'snapshot-isolation'])
        assert _models.name == '历史符合 rw-register 模型（serializable、snapshot-isolation）'
        assert _models.claim == 'history consistent under rw-register serializable,snapshot-isolation'
        assert _plain.src == _models.src == consistency.CONSISTENCY == 'consistency'

    def test_an_empty_history_fails_saying_so(self):
        _c = History().check('counter', consistency_models=['x'])
        assert (_c.ok, _c.is_gap, _c.expr, _c.src) == (False, False, '历史是空的：没有记录任何操作', 'consistency')
        assert (_c.name, _c.claim) == ('历史符合 counter 模型（x）', 'history consistent under counter x')


class TestVerdicts:

    def test_consistent(self, monkeypatch):
        Checker(monkeypatch, {'valid?': True})
        _c = _history(('write', 1), ('write', 2)).check('counter')
        assert (_c.ok, _c.is_gap, _c.expr) == (True, False, '2 个操作，检查器判定一致')

    def test_inconsistent_gives_the_counterexample(self, monkeypatch):
        Checker(monkeypatch, {'valid?': False, 'anomaly-types': ['G1c'], 'not': ['serializable']})
        _c = _history().check('list-append')
        assert (_c.ok, _c.is_gap, _c.expr) == (False, False, '异常：G1c；不满足 serializable')
        assert (_c.name, _c.claim) == ('历史符合 list-append 模型', 'history consistent under list-append')

    @pytest.mark.parametrize('valid', ['unknown', None])
    def test_undecided_is_a_gap(self, monkeypatch, valid):
        Checker(monkeypatch, {'valid?': valid} if valid else {'x': 1})
        _c = _history().check('counter')
        assert _c.is_gap and _c.expr == '检查器无法判定（{}）'.format(valid) and _c.name == '历史符合 counter 模型'
        assert _c.src == 'consistency'

    def test_a_timeout_is_a_gap_naming_the_limit_and_the_history_is_kept(self, monkeypatch, tmp_path):
        from ipandora.core.evidence import recorder
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        _c = Checker(monkeypatch, raises=subprocess.TimeoutExpired('java', 2.5))
        _h = _history()
        recorder.begin('t::slow')
        try:
            _gap = _h.check('counter', consistency_models=['m'], timeout=2.5)
        finally:
            _evidence = recorder.end('t::slow')
        assert _gap.is_gap and _gap.expr == '检查器 2.5 秒内没有给出结论，无法判定' and _gap.src == 'consistency'
        assert _gap.name == '历史符合 counter 模型（m）'
        assert [(_a['kind'], _a['group']) for _a in _evidence.artifacts] == [('history', 'counter')]
        assert '--consistency-models m "' in _evidence.artifacts[0]['command']
        assert not os.path.exists(os.path.dirname(_c.calls[0]['cmd'][-1]))   # removed after a timeout too
        assert os.path.basename(os.path.dirname(_c.calls[0]['cmd'][-1])).startswith('ipandora-history-')

    def test_operations_are_counted_by_their_invocations(self, monkeypatch):
        Checker(monkeypatch, {'valid?': True})
        _h = _history(('write', 1))
        with pytest.raises(KeyError):
            _h.call('write', 2, lambda: {}['x'])
        _h.ops.append({'process': 9, 'type': consistency.K('invoke'), 'f': consistency.K('read'), 'value': None})
        assert _h.check('counter').expr == '3 个操作，检查器判定一致'

    def test_no_result_is_an_error_with_the_exit_code_and_the_end_of_stderr(self, monkeypatch):
        Checker(monkeypatch, stdout='Exception in thread main', returncode=3, stderr='x' * 600 + ' boom\n')
        with pytest.raises(RuntimeError) as _e:
            _history().check('counter')
        assert str(_e.value).startswith('elle-cli gave no result (exit 3): x')
        assert str(_e.value).endswith(' boom') and len(str(_e.value)) == len('elle-cli gave no result (exit 3): ') + 500
        Checker(monkeypatch, stdout='only stdout here', returncode=1)
        with pytest.raises(RuntimeError, match=r'\(exit 1\): only stdout here$'):
            _history().check('counter')

    def test_the_result_is_kept_on_the_history(self, monkeypatch):
        Checker(monkeypatch, stdout='Picked up JAVA_TOOL_OPTIONS\n{"valid?": true, "n": 1}')
        _h = _history()
        _h.check('counter')
        assert _h.result == {'valid?': True, 'n': 1}


class TestCounterexample:

    def test_anomalies_alone(self):
        assert consistency.counterexample({'anomaly-types': ['G0', 'G1c']}) == '异常：G0、G1c'
        assert consistency.counterexample({'anomaly-types': ['G0'], 'not': ['a', 'b']}) == '异常：G0；不满足 a、b'

    def test_the_operation_no_order_explains(self):
        _paths = [[{'op': {'process': 0, 'f': 'write', 'value': 1}, 'model': {'msg': 'first'}},
                   {'op': {'process': 2, 'f': 'read', 'value': 7}, 'model': {'msg': "can't read 7"}}],
                  [{'op': {'process': 9, 'f': 'x', 'value': 0}}]]
        assert consistency.counterexample({'final-paths': _paths}) == \
            "没有任何顺序能解释这个操作：进程 2 的 read 7（can't read 7）"
        _paths[0][-1].pop('model')
        assert consistency.counterexample({'final-paths': _paths}) == '没有任何顺序能解释这个操作：进程 2 的 read 7（）'

    def test_a_long_value_is_cut_and_so_is_the_sentence(self):
        _paths = [[{'op': {'process': 1, 'f': 'read', 'value': 'v' * 200}, 'model': {'msg': 'm'}}]]
        _text = consistency.counterexample({'final-paths': _paths})
        assert 'v' * 200 not in _text and len(_text) < 150
        assert len(consistency.counterexample({'final-paths': _paths}, limit=20)) == 20

    def test_counter_errors_at_most_three(self):
        _errors = [[0, 5, 1], [1, 6, 2], [2, 7, 3], [3, 8, 4]]
        _text = consistency.counterexample({'errors': _errors})
        assert _text.count('读到') == 3 and '读到 8' not in _text
        assert _text.split('；')[1] == '读到 6，按已确认的操作应在 1 到 2 之间'

    def test_other_shapes(self):
        assert consistency.counterexample({'errors': [{'op': 1}]}) == "不一致的读：[{'op': 1}]"
        assert consistency.counterexample({'lost': [1], 'unexpected': [2]}) == '丢失 [1]，多出 [2]'
        assert consistency.counterexample({'lost': [1]}) == '丢失 [1]，多出 None'
        assert consistency.counterexample({'unexpected': [2]}) == '丢失 None，多出 [2]'
        assert consistency.counterexample({'valid?': False, 'odd': 1}) == "检查器判定不一致：{'valid?': False, 'odd': 1}"
        assert consistency.counterexample({'final-paths': [[]], 'lost': [3]}) == '丢失 [3]，多出 None'


# -- the checker: where Java comes from, and what a refusal says ----------------------------------

JAVA21 = '#!/bin/sh\necho \'openjdk version "21.0.4" 2024-07-16\' >&2\n'
JAVA17 = '#!/bin/sh\necho \'openjdk version "17.0.2"\' >&2\n'


def _java(path, script=JAVA21):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def no_java(monkeypatch, tmp_path):
    """No Java anywhere, and an admitted jar: each test adds the one Java it is about."""
    for _var in ('IPANDORA_JAVA', 'JAVA_HOME', 'JAVA_HOME_21_X64', 'ELLE_CLI_JAR'):
        monkeypatch.delenv(_var, raising=False)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty-path'))
    _jar = tmp_path / 'elle-cli.jar'
    _jar.write_bytes(b'jar')
    _settings = {'elle_cli': str(_jar), 'elle_cli_sha256': __import__('hashlib').sha256(b'jar').hexdigest()}
    monkeypatch.setattr(consistency, '_settings', lambda: _settings)
    consistency._VERIFIED.clear()
    return _settings


class TestFindingJava:

    @pytest.mark.parametrize('where', ['setting', 'IPANDORA_JAVA', 'JAVA_HOME_21_X64', 'JAVA_HOME', 'PATH'])
    def test_each_place(self, no_java, monkeypatch, tmp_path, where):
        _home = tmp_path / 'jdk'
        _bin = _java(_home / 'bin' / 'java')
        if where == 'setting':
            no_java['java'] = _bin
        elif where == 'PATH':
            monkeypatch.setenv('PATH', str(_home / 'bin'))
        elif where.startswith('JAVA_HOME'):
            monkeypatch.setenv(where, str(_home))
        else:
            monkeypatch.setenv(where, _bin)
        assert consistency.checker() == (_bin, no_java['elle_cli'])

    def test_the_order_and_a_java_too_old_is_passed_over(self, no_java, monkeypatch, tmp_path):
        _setting = _java(tmp_path / 's' / 'java')
        _env = _java(tmp_path / 'e' / 'java')
        _old = tmp_path / 'old'
        _java(_old / 'bin' / 'java', JAVA17)
        _home = tmp_path / 'home'
        _new = _java(_home / 'bin' / 'java')
        no_java['java'] = _setting
        monkeypatch.setenv('IPANDORA_JAVA', _env)
        assert consistency.checker()[0] == _setting
        del no_java['java']
        assert consistency.checker()[0] == _env
        monkeypatch.delenv('IPANDORA_JAVA')
        monkeypatch.setenv('JAVA_HOME_21_X64', str(_old))       # Java 17: not enough
        monkeypatch.setenv('JAVA_HOME', str(_home))
        assert consistency.checker()[0] == _new

    @pytest.mark.expects_skip
    def test_no_java_skips_saying_where_to_set_it(self, no_java, tmp_path):
        no_java['java'] = _java(tmp_path / 'old' / 'java', JAVA17)
        with pytest.raises(pytest.skip.Exception) as _e:
            consistency.checker()
        assert '有 Java 21+' in str(_e.value)
        assert '需要 Java 21 或更新的版本；没有找到。设置 IPANDORA_JAVA 或 consistency.java' in str(_e.value)

    @pytest.mark.expects_skip
    def test_no_jar_skips_saying_which_one(self, no_java, tmp_path):
        no_java['java'] = _java(tmp_path / 'j' / 'java')
        no_java['elle_cli'] = str(tmp_path / 'nowhere.jar')
        with pytest.raises(pytest.skip.Exception) as _e:
            consistency.checker()
        assert '有一致性检查器 elle-cli' in str(_e.value)
        assert '设置 ELLE_CLI_JAR 或 consistency.elle_cli 指向 elle-cli-{}-standalone.jar（{}）'.format(
            consistency.ELLE_CLI_VERSION, consistency.ELLE_CLI_URL) in str(_e.value)

    def test_the_jar_from_the_environment(self, no_java, monkeypatch, tmp_path):
        no_java['java'] = _java(tmp_path / 'j' / 'java')
        monkeypatch.setenv('ELLE_CLI_JAR', no_java.pop('elle_cli'))
        assert consistency.checker()[1] == os.environ['ELLE_CLI_JAR']

    def test_a_refusal_names_the_jar_and_both_hashes(self, no_java, tmp_path):
        no_java['java'] = _java(tmp_path / 'j' / 'java')
        no_java['elle_cli_sha256'] = 'AB' * 32                  # compared in lower case
        with pytest.raises(RuntimeError) as _e:
            consistency.checker()
        _actual = __import__('hashlib').sha256(b'jar').hexdigest()
        assert str(_e.value) == ('{} has SHA-256 {}, not the admitted {}: refusing to run it. A different build '
                                 'needs its own admission and `consistency.elle_cli_sha256`'.format(
                                     no_java['elle_cli'], _actual, 'ab' * 32))

    def test_the_jar_is_hashed_once_while_it_is_unchanged(self, no_java, monkeypatch, tmp_path):
        no_java['java'] = _java(tmp_path / 'j' / 'java')
        _hashed = []
        _real = consistency.hashlib.sha256
        monkeypatch.setattr(consistency.hashlib, 'sha256', lambda data: _hashed.append(1) or _real(data))
        consistency.checker()
        consistency.checker()
        assert len(_hashed) == 1


class TestJavaVersion:

    def test_versions(self, tmp_path):
        assert consistency._java_version(_java(tmp_path / 'a', JAVA21)) == 21
        assert consistency._java_version(_java(tmp_path / 'b', JAVA17)) == 17
        assert consistency._java_version(_java(tmp_path / 'c', '#!/bin/sh\necho \'java version "1.8.0_402"\'\n')) == 1
        assert consistency._java_version(_java(tmp_path / 'd', '#!/bin/sh\necho no version here\n')) == 0
        assert consistency._java_version(str(tmp_path / 'missing')) == 0

    def test_a_java_that_hangs_is_given_thirty_seconds(self, monkeypatch):
        _seen = {}

        def _run(cmd, **kw):
            _seen.update(kw, cmd=cmd)
            raise subprocess.TimeoutExpired(cmd, kw['timeout'])
        monkeypatch.setattr(consistency.subprocess, 'run', _run)
        assert consistency._java_version('/x/java') == 0
        assert _seen['cmd'] == ['/x/java', '-version'] and _seen['timeout'] == 30


def test_the_settings_are_the_consistency_section(monkeypatch):
    from ipandora.core.schedule.runtime import Runtime
    monkeypatch.setattr(Runtime, 'settings', {'consistency': {'java': '/j'}, 'other': {}})
    assert consistency._settings() == {'java': '/j'}
    monkeypatch.setattr(Runtime, 'settings', {'other': {}})
    assert consistency._settings() == {}


# -- evidence, completions, EDN -------------------------------------------------------------------

class TestEvidenceFiles:

    def _keep(self, monkeypatch, tmp_path, nodeid, result):
        from ipandora.core.evidence import recorder
        monkeypatch.setenv('IPANDORA_ARTIFACTS_DIR', str(tmp_path))
        Checker(monkeypatch, result)
        _h = self._last = _history(('write', '值'), ('read', None))
        recorder.begin(nodeid)
        try:
            _h.check('cas-register', anomalies=['G0'])
        finally:
            _evidence = recorder.end(nodeid)
        return _evidence.artifacts

    def test_the_command_reruns_the_kept_file_and_the_result_reads_as_written(self, monkeypatch, tmp_path):
        _history_file, _result = self._keep(monkeypatch, tmp_path, 'test_a.py::test_b[x y]', {'valid?': True, 'm': '值'})
        assert _history_file['command'].endswith(' --anomalies G0 "{}"'.format(_history_file['path']))
        assert _history_file['path'].endswith('.edn') and _result['path'] == _history_file['path'][:-4] + '.json'
        assert _result['group'] == 'cas-register'
        _text = open(_result['path'], encoding='utf-8').read()
        assert '"m": "值"' in _text and _text.startswith('{\n "valid?": true')     # readable: indented, not escaped
        assert open(_history_file['path'], encoding='utf-8').read() == History.to_edn(self._last)

    def test_the_file_name(self, monkeypatch, tmp_path):
        _a = self._keep(monkeypatch, tmp_path, 'dir/test_a.py::test_b[x y]', {'valid?': True})[0]
        _name = os.path.basename(_a['path'])
        assert re.fullmatch(r'dir_test_a\.py_test_b_x_y_-cas-register-[0-9a-f]{8}\.edn', _name), _name
        _long = self._keep(monkeypatch, tmp_path, 'Z' * 200, {'valid?': True})[0]
        assert os.path.basename(_long['path']).startswith('Z' * 120 + '-cas-register-')
        _none = self._keep(monkeypatch, tmp_path, '', {'valid?': True})[0]
        assert os.path.basename(_none['path']).startswith('case-cas-register-')


class TestCompletions:

    def test_fail_and_info_keep_the_value_and_an_error_is_cut_at_200(self):
        _h = History()
        _h.call('cas', [1, 2], lambda: 409, fail=lambda r: r == 409)
        _h.call('write', 3, lambda: 503, ok=lambda r: r == 200)
        with pytest.raises(ValueError):
            _h.call('write', 4, lambda: (_ for _ in ()).throw(ValueError('e' * 300)))
        assert [(str(_o['type']), _o['value']) for _o in _h.ops] == [
            ('invoke', [1, 2]), ('fail', [1, 2]), ('invoke', 3), ('info', 3), ('invoke', 4), ('info', 4)]
        assert _h.ops[-1]['error'] == ('ValueError: ' + 'e' * 300)[:200]


class TestEdnCorners:

    def test_values(self):
        assert consistency.edn(False) == 'false' and consistency.edn(True) == 'true'
        assert consistency.edn('值') == '"值"'
        assert consistency.edn({'name': 'a', consistency.K('k'): 2}) == '{:name "a", :k 2}'
        for _bad in (float('inf'), float('-inf'), float('nan')):
            with pytest.raises(ValueError, match='finite number, not {}'.format(_bad)):
                consistency.edn(_bad)
        with pytest.raises(TypeError, match="cannot write 'set' as EDN"):
            consistency.edn({1})


class TestCaveats:

    def test_reads_of_nil_are_counted_for_register_and_mutex_only(self, monkeypatch):
        Checker(monkeypatch, {'valid?': True})
        _h = History()
        _h.call('read', None, lambda: None, result=lambda r: r)
        _h.call('read', None, lambda: 5, result=lambda r: r)
        _h.call('write', None, lambda: None)                       # not a read
        _h.call('read', None, lambda: 409, fail=lambda r: True)     # not ok
        for _model in ('cas-register', 'mutex'):
            assert _h.check(_model).expr.endswith('；1 个读到空值（None），检查器不据此判定：先把初始值写进历史')
        assert '空值' not in _h.check('counter').expr

    def test_every_fault_is_named_once(self, monkeypatch):
        Checker(monkeypatch, {'valid?': True})
        _h = History()
        _h.ops = [{'process': 0, 'type': 'invoke', 'f': 'w', 'value': 1, 'faults': ['a']},
                  {'process': 0, 'type': 'ok', 'f': 'w', 'value': 1, 'faults': ['a', 'b']},
                  {'process': 1, 'type': 'invoke', 'f': 'w', 'value': 2},
                  {'process': 1, 'type': 'ok', 'f': 'w', 'value': 2, 'faults': ['c']}]
        assert _h.check('counter').expr.endswith('；其中 2 个操作发生在注入的故障期间（a、b、c）')

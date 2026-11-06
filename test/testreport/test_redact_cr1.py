# -*- coding: utf-8 -*-
"""
Redaction defects found in code review CR1 (docs/design/reviews/01-CR1.md, F2).
Each test fails on the code before the fix.
"""
from ipandora.core.assertion.check import brief
from ipandora.core.eval import AgentResult, dataset, evaluate
from ipandora.core.eval import report as eval_report
from ipandora.core.eval.annotate import samples
from ipandora.core.assertion.check import Check
from ipandora.core.report.redact import MASK, redact, redact_text
from ipandora.core.report.render import highlight_json, to_curl
from ipandora.core.runner.result import CaseResult, RunResult

JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ'
PEM = ('-----BEGIN PRIVATE KEY-----\n' + 'MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n' * 6  # pragma: allowlist secret
       + '-----END PRIVATE KEY-----')
WORDS = 'abandon ability able about above absent absorb abstract absurd abuse access accident'


class TestTextShapes:
    def test_dict_repr_in_a_message(self):
        _out = redact_text("request was {'username': 'alice', 'password': 'hunter2'}")  # pragma: allowlist secret
        assert 'hunter2' not in _out and 'alice' in _out

    def test_yaml_and_json_fragments(self):
        assert 'hunter2' not in redact_text('password: hunter2')
        assert 'abc123' not in redact_text('got {"api_key": "abc123", "n": 1}')  # pragma: allowlist secret

    def test_header_line_in_text(self):
        _out = redact_text('> Cookie: sid=abc; theme=dark\n> Accept: */*')
        assert 'sid=abc' not in _out and 'Accept: */*' in _out

    def test_ordinary_colons_are_left_alone(self):
        for _text in ('time: 12:30', 'checks: 3 passed', "token: ''"):
            assert redact_text(_text) == _text

    def test_deep_structure_is_masked_not_published(self):
        _deep = {'password_hint': 'x', 'value': 'hunter2-' + 'a1' * 4}
        for _ in range(30):
            _deep = {'n': _deep}
        assert 'hunter2' not in str(redact(_deep))


class TestBriefMasksBeforeCutting:
    def test_pem_cut_before_its_end_line(self):
        _out = brief('key ' + PEM, limit=80)
        assert 'MIIEvQIBADANBgkqhkiG9w0BAQEFAASC' not in _out

    def test_jwt_cut_after_a_dot(self):
        _out = brief('t ' + JWT, limit=len(JWT) - 10)
        assert 'eyJzdWIiOiIxMjM0NTY3ODkwIn0' not in _out

    def test_mnemonic_cut_short(self):
        _out = brief(WORDS + ' and more text after it', limit=60)
        assert 'abandon ability able' not in _out

    def test_short_values_are_untouched(self):
        assert brief('password: x') == repr('password: x')


class TestRenderHelpers:
    def test_highlight_json_accepts_non_text(self):
        assert '42' in highlight_json(42)
        assert '&quot;a&quot;' in highlight_json({'a': 1})

    def test_curl_sends_a_dict_body_as_json(self):
        _cmd = to_curl({'method': 'POST', 'url': 'http://x', 'request_body': {'a': True}})
        assert '{"a": true}' in _cmd


class TestAgentFacingOutput:
    def test_summary_nodeid_is_masked(self):
        _key = 'a1' * 32
        _run = RunResult(run_id='r', cases=[CaseResult(
            nodeid='t.py::test_sign[{}]'.format(_key), outcome='failed', message='bad')])
        assert _key not in str(_run.summary())


def _eval_run():
    _data = dataset.from_records([{'id': 't1', 'input': 'x', 'expected': 'y'}], name='d')

    def _agent(task):
        return AgentResult(output={'reply': 'done', 'password': 'hunter2'},  # pragma: allowlist secret
                           trajectory=[{'kind': 'tool', 'text': 'read env: token=' + JWT}],
                           cost={'tokens_in': 120, 'usd': 0.01})

    def _grade(task, result):
        return [Check(name='reply', ok=False, expr="got {'password': 'hunter2'}")]  # pragma: allowlist secret

    return evaluate(_data, _agent, _grade, trials=1)


class TestEvalReport:
    def test_html_and_json_are_masked(self, tmp_path):
        _paths = eval_report.write(_eval_run(), str(tmp_path))
        for _path in _paths.values():
            _text = open(_path, encoding='utf-8').read()
            assert 'hunter2' not in _text and JWT not in _text, _path

    def test_cost_numbers_survive(self):
        _out = eval_report.to_dict(_eval_run())
        assert _out['trials'][0]['cost'] == {'tokens_in': 120, 'usd': 0.01}

    def test_labelling_samples_are_masked(self):
        _rows = samples(_eval_run(), include_deterministic=True)
        assert 'hunter2' not in str(_rows)

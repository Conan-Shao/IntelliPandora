# -*- coding: utf-8 -*-
"""
cases(): data files as pytest parameters (docs/design/decisions/17 §3.5, plan L2).

Acceptance: dims written in the data file reach the coverage matrix.
"""
import textwrap

import pytest

from ipandora.core.cases import Case, cases
from ipandora.core.report import build
from ipandora.core.runner import plugin, run

# `dims` is registered by the runner's plugin; this module calls cases()
# outside a run, where pytest does not know the marker yet
pytestmark = pytest.mark.filterwarnings('ignore::pytest.PytestUnknownMarkWarning')


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')
    return str(path)


class TestReading:
    def test_yaml_rows_become_params_with_ids_and_dims(self, tmp_path):
        _f = write(tmp_path / 'amounts.yaml', '''
            - id: whole
              amount: '100.00'
              dims: {role: buyer, channel: api}
            - id: fen
              amount: '100.50'
        ''')
        _params = cases(_f)
        assert [_p.id for _p in _params] == ['whole', 'fen']
        assert _params[0].values[0] == {'id': 'whole', 'amount': '100.00'}
        assert _params[0].values[0].amount == '100.00'
        assert _params[0].marks[0].name == 'dims'
        assert _params[0].marks[0].kwargs == {'role': 'buyer', 'channel': 'api'}
        assert not _params[1].marks

    def test_csv_columns_named_dims_dot_become_dims(self, tmp_path):
        _f = write(tmp_path / 'a.csv', '''\
            id,amount,dims.role,dims.channel
            one,1.00,buyer,api
            two,2.00,,
        ''')
        _params = cases(_f)
        assert _params[0].marks[0].kwargs == {'role': 'buyer', 'channel': 'api'}
        assert not _params[1].marks
        assert _params[1].values[0] == {'id': 'two', 'amount': '2.00'}

    def test_json_and_a_cases_key(self, tmp_path):
        _f = write(tmp_path / 'a.json', '{"cases": [{"x": 1}, {"x": 2}]}')
        assert [_p.id for _p in cases(_f)] == ['a-1', 'a-2']

    def test_found_from_the_callers_directory_upwards(self, tmp_path, monkeypatch):
        write(tmp_path / 'data' / 'rows.yaml', '- {id: r1}\n')
        _caller = tmp_path / 'tests' / 'api' / 'test_x.py'
        write(_caller, '''
            from ipandora.core.cases import cases
            FOUND = cases('data/rows.yaml')
        ''')
        monkeypatch.chdir(tmp_path / 'tests')
        _ns = {}
        exec(compile(_caller.read_text(), str(_caller), 'exec'), _ns)
        assert [_p.id for _p in _ns['FOUND']] == ['r1']

    @pytest.mark.parametrize('text, problem', [
        ('- {id: a}\n- {id: a}\n', 'duplicate id'),
        ('[]\n', 'no cases'),
        ('- 1\n', 'must be a mapping'),
        ('- {id: a, dims: buyer}\n', 'dims must be a mapping'),
        ('{a: [1\n', 'not valid YAML'),
    ])
    def test_problems_are_named(self, tmp_path, text, problem):
        with pytest.raises(ValueError, match=problem):
            cases(write(tmp_path / 'bad.yaml', text))

    def test_a_missing_field_says_what_there_is(self):
        with pytest.raises(AttributeError, match='amount'):
            Case(amount=1).ammount


def test_dims_in_the_data_file_fill_the_coverage_matrix(tmp_path, monkeypatch):
    monkeypatch.setenv('IPANDORA_CONFIG_DIR', str(tmp_path / 'no-conf'))
    monkeypatch.setenv(plugin.LOCK_DIR_VAR, str(tmp_path / 'locks'))
    write(tmp_path / 'proj' / 'data' / 'refunds.yaml', '''
        - id: buyer-api
          amount: '1.00'
          dims: {role: buyer, channel: api}
        - id: seller-web
          amount: '2.00'
          dims: {role: seller, channel: web}
    ''')
    _suite = write(tmp_path / 'proj' / 'tests' / 'test_refunds.py', '''
        import pytest
        from ipandora.core.cases import cases
        from ipandora.core.assertion import assert_all, that

        COVERAGE = [{'role': ['buyer', 'seller'], 'channel': ['api', 'web']}]

        @pytest.mark.parametrize('case', cases('data/refunds.yaml'))
        def test_refund(case):
            assert_all(that(case.amount, 'amount').decimal() > 0)
    ''')
    _result = run(_suite, persist=False, quiet=True, baseline='')
    assert _result.ok, [_c.message for _c in _result.cases]
    assert [_c.name for _c in _result.cases] == ['test_refund[buyer-api]', 'test_refund[seller-web]']
    _grid = build(_result).coverage_matrix[0]
    assert (_grid['filled'], _grid['total']) == (2, 4)

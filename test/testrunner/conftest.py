# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : conftest.py
@Time  : 2026-08-01
"""
import textwrap

import pytest

# A tiny suite covering each outcome the runner has to classify. Written to a
# temp dir so the outer pytest run never collects it.
SAMPLE_SUITE = '''
    import pytest

    def test_that_passes():
        assert True

    def test_that_fails():
        assert 1 == 2, "one is not two"

    def test_that_skips():
        pytest.skip("nothing to do")

    def test_setup_error(no_such_fixture):
        pass
'''


@pytest.fixture
def sample_suite(tmp_path):
    _file = tmp_path / 'test_sample_suite.py'
    _file.write_text(textwrap.dedent(SAMPLE_SUITE), encoding='utf-8')
    return str(_file)


@pytest.fixture
def passing_suite(tmp_path):
    _file = tmp_path / 'test_passing_suite.py'
    _file.write_text('def test_ok():\n    assert True\n', encoding='utf-8')
    return str(_file)


@pytest.fixture(autouse=True)
def isolated_run_store(tmp_path, monkeypatch):
    """Keep runs out of the developer's real ~/.ipandora/runs."""
    monkeypatch.setenv('IPANDORA_RUNS_DIR', str(tmp_path / 'runs'))

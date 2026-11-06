# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_docs_examples.py
@Time  : 2026-11-05

The documentation's code works.

Three levels, cheapest first:

- every Python block in the guide, the README and both AGENTS.md files parses,
  and every name it imports from ipandora exists. This is the failure that
  actually happened: the concurrency section imported `field` from
  ipandora.core.assertion.field, where there is no such name, and nothing
  noticed;
- a block marked `<!-- run -->` on the line before it runs as written;
- the quick start's own steps -- `ipandora init`, then a run -- work: the
  generated project passes, offline.

Most blocks are fragments (they use a `resp` the reader is expected to have),
so they are only held to the first level. Mark a block runnable when it is
complete.
"""
import ast
import glob
import importlib
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = sorted(glob.glob(os.path.join(REPO, 'docs', 'guide', '*.md'))) + [
    os.path.join(REPO, _f) for _f in ('README.md', 'AGENTS.md',
                                      'src/ipandora/templates/project/AGENTS.md')]
BLOCK = re.compile(r'(?P<mark><!--\s*run\s*-->\s*\n)?^```python\n(?P<code>.*?)^```', re.S | re.M)


def blocks():
    for _path in DOCS:
        _text = open(_path, encoding='utf-8').read()
        for _m in BLOCK.finditer(_text):
            _line = _text[:_m.start('code')].count('\n')
            yield pytest.param(_m.group('code'), bool(_m.group('mark')),
                               id='{}:{}'.format(os.path.relpath(_path, REPO), _line))


ALL = list(blocks())


def _imports(tree):
    for _node in ast.walk(tree):
        if isinstance(_node, ast.ImportFrom) and (_node.module or '').startswith('ipandora'):
            yield _node.module, [_a.name for _a in _node.names]
        elif isinstance(_node, ast.Import):
            for _a in _node.names:
                if _a.name.startswith('ipandora'):
                    yield _a.name, []


@pytest.mark.parametrize('code, runnable', ALL)
def test_every_block_parses_and_imports_names_that_exist(code, runnable):
    _tree = ast.parse(code)
    for _module, _names in _imports(_tree):
        try:
            _mod = importlib.import_module(_module)
        except ImportError as exc:
            _missing = getattr(exc, 'name', '') or ''
            if _missing == 'ipandora.ai' or _missing.startswith('ipandora.ai.'):
                pytest.skip('ai/ is removed in this run: {}'.format(exc))
            if _missing.startswith('ipandora'):
                raise          # the docs name a module that does not exist
            pytest.skip('needs an optional extra: {}'.format(exc))
        for _name in _names:
            if not hasattr(_mod, _name):
                importlib.import_module('{}.{}'.format(_module, _name))   # a submodule, or fail


@pytest.mark.parametrize('code, runnable', [_b for _b in ALL if _b.values[1]])
def test_runnable_blocks_run(code, runnable, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exec(compile(code, '<doc block>', 'exec'), {'__name__': '__doc_example__'})


def test_there_is_at_least_one_runnable_block():
    assert any(_b.values[1] for _b in ALL)


def test_the_quick_start_works(tmp_path):
    """`ipandora init my-tests && cd my-tests && ipandora run tests`, as documented."""
    _env = dict(os.environ, IPANDORA_RUNS_DIR=str(tmp_path / 'home' / 'runs'),
                IPANDORA_REPORTS_DIR=str(tmp_path / 'home' / 'reports'))
    _env.pop('IPANDORA_CONFIG_DIR', None)
    _cli = [sys.executable, '-m', 'ipandora.run']
    subprocess.run(_cli + ['init', 'my-tests'], cwd=str(tmp_path), env=_env, check=True,
                   capture_output=True)
    _project = tmp_path / 'my-tests'
    for _f in ('AGENTS.md', 'conf/config.yaml', 'conftest.py', 'tests/test_example.py',
               '.github/workflows/tests.yml', '.github/CODEOWNERS', '.gitignore'):
        assert (_project / _f).is_file(), _f
    _run = subprocess.run(_cli + ['run', 'tests', '--no-report'], cwd=str(_project), env=_env,
                          capture_output=True, text=True)
    assert _run.returncode == 0, _run.stdout[-2000:] + _run.stderr[-2000:]
    assert 'PASS' in _run.stdout and '没有任何判定' not in _run.stdout

    # step 4: accept the baseline, then the gate passes on an unchanged suite
    _accept = subprocess.run(_cli + ['run', 'tests', '--no-report', '--update-baseline'],
                             cwd=str(_project), env=_env, capture_output=True, text=True)
    assert _accept.returncode == 0 and (_project / 'conf' / 'judgements.json').is_file()
    _gate = subprocess.run(_cli + ['run', 'tests', '--no-report', '--fail-on-weakened'],
                           cwd=str(_project), env=_env, capture_output=True, text=True)
    assert _gate.returncode == 0, _gate.stdout[-2000:]

    # and the gate does fail when an agent weakens a judgement
    _test = _project / 'tests' / 'test_example.py'
    _test.write_text(_test.read_text(encoding='utf-8').replace(
        "field(r, 'data.fee') <= 100", "field(r, 'data.fee') <= 1000"), encoding='utf-8')
    _weak = subprocess.run(_cli + ['run', 'tests', '--no-report', '--fail-on-weakened'],
                           cwd=str(_project), env=_env, capture_output=True, text=True)
    assert _weak.returncode == 1, _weak.stdout[-2000:]


def test_init_never_overwrites_without_force(tmp_path):
    from ipandora.run.commands.init import generate
    (tmp_path / 'conftest.py').write_text('# mine\n', encoding='utf-8')
    _written, _kept = generate(str(tmp_path))
    assert 'conftest.py' in _kept and (tmp_path / 'conftest.py').read_text() == '# mine\n'
    assert 'AGENTS.md' in _written
    _written, _kept = generate(str(tmp_path), force=True)
    assert 'conftest.py' in _written and 'pytest' in (tmp_path / 'conftest.py').read_text()


def test_the_generated_ci_installs_the_version_that_generated_it(tmp_path):
    from ipandora.run.commands.init import generate
    from ipandora.version import get_latest_version
    generate(str(tmp_path))
    _ci = (tmp_path / '.github' / 'workflows' / 'tests.yml').read_text(encoding='utf-8')
    assert 'intellipandora=={}'.format(get_latest_version()) in _ci
    assert '--fail-on-weakened' in _ci
    assert '{{' not in _ci


def test_the_generated_gitignore_keeps_environment_overlays_out(tmp_path):
    # CR1: AGENTS.md says credentials go in an uncommitted conf/<env>.yaml,
    # and nothing ignored it -- `git add .` committed them
    from ipandora.run.commands.init import generate
    generate(str(tmp_path))
    subprocess.run(['git', 'init', '-q'], cwd=str(tmp_path), check=True)
    (tmp_path / 'conf' / 'staging.yaml').write_text('password: x\n', encoding='utf-8')  # pragma: allowlist secret
    _ignored = subprocess.run(['git', 'check-ignore', 'conf/staging.yaml', 'conf/config.yaml'],
                              cwd=str(tmp_path), capture_output=True, text=True).stdout.split()
    assert _ignored == ['conf/staging.yaml']


def test_the_demo_service_bypasses_a_lowercase_proxy_setting(tmp_path):
    # CR1: requests reads no_proxy before NO_PROXY; only NO_PROXY was extended
    _env = dict(os.environ, IPANDORA_RUNS_DIR=str(tmp_path / 'home' / 'runs'),
                http_proxy='http://127.0.0.1:9', HTTP_PROXY='http://127.0.0.1:9',
                no_proxy='.corp.example', NO_PROXY='.corp.example')
    _env.pop('IPANDORA_CONFIG_DIR', None)
    _cli = [sys.executable, '-m', 'ipandora.run']
    subprocess.run(_cli + ['init', 'p'], cwd=str(tmp_path), env=_env, check=True, capture_output=True)
    _run = subprocess.run(_cli + ['run', 'tests', '--no-report', '--no-baseline'],
                          cwd=str(tmp_path / 'p'), env=_env, capture_output=True, text=True)
    assert _run.returncode == 0, _run.stdout[-2000:] + _run.stderr[-2000:]

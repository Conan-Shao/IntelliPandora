# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_gates.py
@Time  : 2026-11-05

The security gates: scripts/check_components.py and scripts/security_report.py.

What they are for is to stop something, so what these cases pin is each way
they could quietly stop nothing: a license check that a dual license or an
empty field slips through, an exception that never expires, an action pinned
to a tag that reads as pinned, a vulnerability under an exception that still
blocks (or one without that does not), a `# nosec` without a reason, and a
report whose date moves on every run so the day it mattered is lost.

All offline: the scanners themselves are replaced, the logic around them is not.
"""
import datetime
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

import check_components as cc  # noqa: E402
import security_report as sr  # noqa: E402

TODAY = datetime.date(2026, 11, 5)


# -- check_components --------------------------------------------------------

@pytest.mark.parametrize('line, expected', [
    ('requests>=2.31,<3', ('requests', '>=2.31,<3')),
    ('PyYAML >= 6.0, < 7', ('pyyaml', '>=6.0,<7')),
    ('mcp>=2.0,<3 ; python_version >= "3.10"  # comment', ('mcp', '>=2.0,<3')),
    ('uvicorn[standard]==0.30', ('uvicorn', '==0.30')),
    ('Jinja2', ('jinja2', '')),
])
def test_requirement_lines_are_split_into_name_and_spec(line, expected):
    assert cc.split_req(line) == expected


@pytest.mark.parametrize('text', ['MIT', 'Apache-2.0 OR BSD-3-Clause', 'Apache Software License',
                                  'Mozilla Public License 2.0 (MPL 2.0)', 'PSF-2.0'])
def test_permissive_licenses_pass(text):
    assert cc.license_ok(text)


@pytest.mark.parametrize('text', [
    'GPL-3.0-only',
    'LGPLv3',
    # a dual license naming a copyleft option is not admitted automatically:
    # someone has to decide which one we take, and write it down
    'MIT OR GPL-2.0',
    'SSPL-1.0',
    # no license stated is not "probably fine"
    '',
    'Proprietary',
])
def test_copyleft_unknown_and_missing_licenses_fail(text):
    assert not cc.license_ok(text)


def _exceptions(tmp_path, monkeypatch, rows):
    _path = tmp_path / 'exceptions.md'
    _path.write_text('| 漏洞编号 | 组件 | 理由 | 到期日 |\n|---|---|---|---|\n' + ''.join(
        '| {} |\n'.format(' | '.join(_r)) for _r in rows), encoding='utf-8')
    monkeypatch.setattr(cc, 'EXCEPTIONS', str(_path))


def test_an_expired_exception_fails_and_is_no_longer_passed_to_pip_audit(tmp_path, monkeypatch):
    _exceptions(tmp_path, monkeypatch, [('GHSA-old', 'x', 'no fix yet', '2026-11-04'),
                                        ('GHSA-new', 'y', 'not reachable', '2026-11-05')])
    _problems = cc.check_exceptions(TODAY)
    assert len(_problems) == 1 and 'GHSA-old' in _problems[0] and 'expired' in _problems[0]
    assert cc.ignore_args(TODAY) == ['--ignore-vuln', 'GHSA-new']


def test_an_exception_without_reason_or_date_fails(tmp_path, monkeypatch):
    _exceptions(tmp_path, monkeypatch, [('GHSA-a', 'x', '', '2027-01-01'),
                                        ('GHSA-b', 'x', 'why', 'someday')])
    _problems = cc.check_exceptions(TODAY)
    assert any('GHSA-a' in _p and 'reason' in _p for _p in _problems)
    assert any('GHSA-b' in _p and 'expiry' in _p for _p in _problems)


def _fake_repo(tmp_path, workflow):
    (tmp_path / 'requirements').mkdir()
    (tmp_path / 'requirements' / 'build.in').write_text('', encoding='utf-8')
    (tmp_path / 'requirements' / 'tools.in').write_text('', encoding='utf-8')
    (tmp_path / 'setup.cfg').write_text('[options]\ninstall_requires =\n    requests>=2.31,<3\n',
                                        encoding='utf-8')
    (tmp_path / 'setup.py').write_text("setup(extras_require={'ai': ['anthropic>=0.40,<1']})\n",
                                       encoding='utf-8')
    (tmp_path / '.github' / 'workflows').mkdir(parents=True)
    (tmp_path / '.github' / 'workflows' / 'ci.yml').write_text(workflow, encoding='utf-8')
    return tmp_path


def _registry(tmp_path, monkeypatch, rows):
    _path = tmp_path / 'components.md'
    _path.write_text('| 组件 | 类别 | 版本范围 | 用途 | 许可证 | 运行期行为 | 审查日期 |\n'
                     '|---|---|---|---|---|---|---|\n' + ''.join(
                         '| {} | {} | {} | u | MIT | - | 2026-11-05 |\n'.format(*_r) for _r in rows),
                     encoding='utf-8')
    monkeypatch.setattr(cc, 'REGISTRY', str(_path))


SHA = 'a' * 40


def test_the_registry_must_match_the_code_in_both_directions(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, 'REPO', str(_fake_repo(
        tmp_path, '    steps:\n      - uses: actions/checkout@{}  # v7.0.1\n'
                  '      - uses: ./.github/actions/local\n'.format(SHA))))
    _registry(tmp_path, monkeypatch, [('requests', 'runtime', '>=2.31,<3'),
                                      ('anthropic', 'extra:ai', '>=0.40,<2'),   # wrong spec
                                      ('actions/checkout', 'action', 'v7.0.1@' + SHA),
                                      ('left-pad', 'runtime', '>=1')])          # no longer used
    _problems = cc.check_registry()
    assert len(_problems) == 2, _problems
    assert any('anthropic' in _p and '>=0.40,<1' in _p for _p in _problems)
    assert any('no longer used: left-pad' in _p for _p in _problems)


@pytest.mark.parametrize('line', [
    '      - uses: actions/checkout@v4',
    # looks pinned, is not: a branch name
    '      - uses: actions/checkout@main',
    # a SHA without the version comment cannot be checked against the registry
    '      - uses: actions/checkout@' + SHA,
])
def test_an_action_not_pinned_to_a_sha_with_its_version_fails(tmp_path, monkeypatch, line):
    monkeypatch.setattr(cc, 'REPO', str(_fake_repo(tmp_path, line + '\n')))
    _registry(tmp_path, monkeypatch, [('requests', 'runtime', '>=2.31,<3'),
                                      ('anthropic', 'extra:ai', '>=0.40,<1')])
    assert any('not pinned' in _p for _p in cc.check_registry())


# -- security_report ---------------------------------------------------------

def _scanners(monkeypatch, vulns=(), bandit_results=(), annotations=(), skipped=None,
              licenses=None, exceptions=()):
    def audit(lock):
        return [('requests', '2.32.0', list(vulns) if lock.endswith('ci.txt') else []),
                ('urllib3', '2.5.0', [])]
    monkeypatch.setattr(sr, 'audit', audit)
    monkeypatch.setattr(sr, 'bandit', lambda: (list(bandit_results),
                                              len(annotations) if skipped is None else skipped))
    monkeypatch.setattr(sr, 'annotations', lambda: list(annotations))
    _lic = licenses or {'requests': {'version': '2.32.0', 'license': 'Apache-2.0',
                                     'allowed': True}}
    monkeypatch.setattr(sr, 'licenses', lambda python: _lic)
    monkeypatch.setattr(sr.check_components, 'exceptions', lambda: list(exceptions))
    monkeypatch.setattr(sr.check_components, 'check_registry', lambda: [])
    monkeypatch.setattr(sr.check_components, 'declared', lambda: {'requests': ('runtime', '')})
    monkeypatch.setattr(sr, 'tool_versions', lambda: {'pip-audit': '2.10.1', 'bandit': '1.9.4'})
    monkeypatch.setattr(sr, 'locked', lambda lock: set(_lic) - {'pip'})


VULN = {'id': 'PYSEC-2026-1', 'aliases': ['GHSA-xxxx', 'CVE-2026-1'], 'fix_versions': ['2.33.0']}


def test_a_vulnerability_blocks_and_is_named_in_the_report(monkeypatch):
    _scanners(monkeypatch, vulns=[VULN])
    _s = sr.assess('python', TODAY)
    assert _s['blocking'] == ['requests 2.32.0 (requirements/ci.txt): PYSEC-2026-1']
    _md = sr.render(_s, TODAY.isoformat())
    assert '| 依赖漏洞 | `requirements/ci.txt`' in _md and '**未通过**' in _md
    assert 'PYSEC-2026-1（CVE-2026-1、GHSA-xxxx） | requests | 2.32.0 | 2.33.0' in _md
    assert '**待处理**' in _md


def test_an_exception_matches_by_alias_and_does_not_block_until_it_expires(monkeypatch):
    _exc = {'id': 'GHSA-xxxx', 'component': 'requests', 'reason': 'not reachable',
            'expires': '2026-12-01'}
    _scanners(monkeypatch, vulns=[VULN], exceptions=[_exc])
    _s = sr.assess('python', TODAY)
    assert _s['blocking'] == []
    _md = sr.render(_s, TODAY.isoformat())
    assert '已登记例外，2026-12-01 到期：not reachable' in _md and '均已登记例外' in _md

    # the day after it expires, the same advisory blocks again
    assert sr.assess('python', datetime.date(2026, 12, 2))['blocking']


def test_a_nosec_without_a_reason_blocks(monkeypatch):
    _scanners(monkeypatch, annotations=[('B110', 'src/x.py', 'reporting must never fail'),
                                        ('B311', 'src/y.py', None)])
    _blocking = sr.assess('python', TODAY)['blocking']
    assert len(_blocking) == 1 and 'B311' in _blocking[0] and 'src/y.py' in _blocking[0]


def test_a_nosec_in_a_form_the_report_cannot_see_blocks(monkeypatch):
    # bandit skipped three, the report found two: one annotation is invisible
    # to the published list, so the list would be incomplete
    _scanners(monkeypatch, annotations=[('B110', 'src/x.py', 'r'), ('B110', 'src/x.py', 'r')],
              skipped=3)
    assert any('expected form' in _b for _b in sr.assess('python', TODAY)['blocking'])


def test_a_code_finding_and_a_disallowed_license_block(monkeypatch):
    _scanners(monkeypatch, bandit_results=[{'test_id': 'B602', 'issue_severity': 'HIGH',
                                            'filename': 'src/z.py', 'issue_text': 'shell=True'}],
              licenses={'gplthing': {'version': '1', 'license': 'GPL-3.0', 'allowed': False}})
    _blocking = sr.assess('python', TODAY)['blocking']
    assert any('B602' in _b for _b in _blocking)
    assert any('gplthing' in _b for _b in _blocking)


def test_the_report_keeps_its_date_until_the_status_changes(monkeypatch, tmp_path):
    _scanners(monkeypatch)
    _path = str(tmp_path / 'report.md')
    assert sr.write(sr.assess('python', TODAY), _path, TODAY)
    _first = open(_path, encoding='utf-8').read()
    assert '状态日期：2026-11-05' in _first

    # a week of daily scans with nothing new: not a single byte changes
    _later = datetime.date(2026, 11, 12)
    assert not sr.write(sr.assess('python', _later), _path, _later)
    assert open(_path, encoding='utf-8').read() == _first

    # an advisory appears: the report changes and carries that day's date
    _scanners(monkeypatch, vulns=[VULN])
    assert sr.write(sr.assess('python', _later), _path, _later)
    assert '状态日期：2026-11-12' in open(_path, encoding='utf-8').read()


def test_the_report_does_not_depend_on_the_machine_that_ran_it(monkeypatch):
    # CI's venv seeds pip 25.0.1, a laptop's 24.0. Neither is in a lock file;
    # listing it made the first scan on main propose a report change.
    def _env(pip):
        return {'requests': {'version': '2.32.0', 'license': 'Apache-2.0', 'allowed': True},
                'pip': {'version': pip, 'license': 'MIT', 'allowed': True}}
    _scanners(monkeypatch, licenses=_env('24.0'))
    _a = sr.render(sr.assess('python', TODAY), TODAY.isoformat())
    _scanners(monkeypatch, licenses=_env('25.0.1'))
    _b = sr.render(sr.assess('python', TODAY), TODAY.isoformat())
    assert _a == _b and '| pip |' not in _a


def test_an_unlocked_distribution_is_still_license_checked(monkeypatch):
    _scanners(monkeypatch, licenses={
        'requests': {'version': '2.32.0', 'license': 'Apache-2.0', 'allowed': True},
        'pip': {'version': '25.0.1', 'license': 'GPL-3.0', 'allowed': False}})
    assert any('pip' in _b for _b in sr.assess('python', TODAY)['blocking'])


def test_text_from_advisories_and_comments_cannot_inject_markup(monkeypatch):
    _scanners(monkeypatch, annotations=[('B704', 'src/r.py', 'only our own <span> tags | raw')])
    _md = sr.render(sr.assess('python', TODAY), TODAY.isoformat())
    assert 'only our own &lt;span&gt; tags \\| raw' in _md


def test_a_scan_that_cannot_run_writes_nothing(monkeypatch, tmp_path):
    _scanners(monkeypatch)

    def _down(lock):
        raise sr.ScanError('pip-audit: connection refused')
    monkeypatch.setattr(sr, 'audit', _down)
    _path = tmp_path / 'report.md'
    _path.write_text('published', encoding='utf-8')
    assert sr.main(['--out', str(_path), '--summary', '']) == 2
    assert _path.read_text(encoding='utf-8') == 'published'


def test_the_published_report_is_current():
    """docs/security/report.md says what the code is. A PR that adds a
    dependency, an annotation or an exception regenerates it in the same PR,
    so the published page never describes code that no longer exists.

    Only the parts that need no network are compared here; the vulnerability
    rows are the daily job's to keep current."""
    _md = open(os.path.join(REPO, 'docs', 'security', 'report.md'), encoding='utf-8').read()
    for _id, _path, _reason in sr.annotations():
        assert '| {} | `{}` | {} |'.format(_id, _path, sr._cell(_reason)) in _md, (
            'regenerate docs/security/report.md: scripts/security_report.py')
    assert '| 组件登记 | {} 个直接依赖与 CI 动作 |'.format(len(cc.declared())) in _md, (
        'regenerate docs/security/report.md: scripts/security_report.py')

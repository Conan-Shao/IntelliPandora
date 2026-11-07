#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run every security scan and write the public report, docs/security/report.md.

Usage: security_report.py [--runtime-python PY] [--out PATH] [--summary PATH]

Run it with the interpreter of an environment installed from
requirements/tools.txt (it calls pip-audit and bandit as modules of that
interpreter). --runtime-python names one installed from requirements/ci.txt,
whose licenses are what ships to users; it defaults to the same interpreter.

What it checks, and what blocks (exit 1):

- **dependency vulnerabilities**, per lock file, with pip-audit. The audit
  runs against the hashed lock, not the installed environment, so it covers
  the exact files CI installs and nothing else. An advisory listed in
  docs/security/exceptions.md and not expired is reported but does not block;
- **our own code**, src/, with bandit. Any finding blocks. An accepted one is
  annotated `# nosec Bxxx` *and* carries a `# bandit Bxxx: <reason>` line
  directly above -- an annotation without a reason blocks too, because the
  report lists every one with its reason;
- **npm dependencies**, per package-lock.json under bench/, with `npm audit`
  (same exception rules), and each lock's hashes, sources and licenses;
- **licenses** of the runtime and tool environments (and, with
  --bench-python, the comparison job's), against the allowlist in
  check_components.py;
- **the component registry** and **the exception list**, by
  check_components.py.

The report changes only when the status does. Its date is the date the status
last changed, not the date of the last scan -- a report that changed every day
would bury the day it mattered, and the daily job would open a PR every day.

If a scan cannot run at all (no network, a tool crashed), nothing is written
and the exit code is 2: "could not check" must never be published as a result.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_components  # noqa: E402

REPO = check_components.REPO
REPORT = os.path.join(REPO, 'docs', 'security', 'report.md')
ACTIONS = 'https://github.com/Conan-Shao/IntelliPandora/actions/workflows/security.yml'

def _label(output: str) -> str:
    """
    What a lock holds, read from update_locks.py -- the file that decides it.
    Written out by hand here, the report said ci.txt held "ai, mcp, system,
    test" long after parallel, visual and web had joined it.
    """
    import update_locks
    _extras = update_locks.LOCKS[output][1]
    if not _extras:
        return '构建与工具链（不安装到用户环境）'
    if output == 'bench.txt':
        return 'Android 对比作业专用：框架的 android 组 + Appium 客户端（不安装到用户环境）'
    _missing = [_e for _e in ('ai',) if _e not in _extras]
    return '框架 + 可选组 {}{}'.format('、'.join(_extras),
                                    '，不含 AI 组' if _missing else '')


# lock file -> what it is, in the report's words
LOCKS = tuple(('requirements/' + _name, _label(_name))
              for _name in ('ci.txt', 'ci-noai.txt', 'tools.txt', 'bench.txt'))


class ScanError(Exception):
    """A scan could not run. Distinct from a scan that ran and found something."""


def _run(cmd):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


# -- scans -------------------------------------------------------------------

def audit(lock: str):
    """[(name, version, [vuln dicts])] for one lock file."""
    _proc = _run([sys.executable, '-m', 'pip_audit', '-r', lock, '--no-deps', '--disable-pip',
                  '--require-hashes', '--progress-spinner', 'off', '-f', 'json'])
    # exit 1 means "vulnerabilities found" and still prints the JSON
    try:
        _data = json.loads(_proc.stdout)
    except ValueError:
        raise ScanError('pip-audit on {} did not produce a result (exit {}):\n{}'.format(
            lock, _proc.returncode, _proc.stderr.strip()[-2000:]))
    _out = []
    for _dep in _data.get('dependencies', []):
        if 'skip_reason' in _dep:
            raise ScanError('pip-audit skipped {} in {}: {}'.format(
                _dep['name'], lock, _dep['skip_reason']))
        # the PyPI service can list one advisory twice; once per package is enough
        _vulns = list({_v['id']: _v for _v in _dep.get('vulns', [])}.values())
        _out.append((check_components.norm(_dep['name']), _dep['version'],
                     sorted(_vulns, key=lambda v: v['id'])))
    return sorted(_out, key=lambda d: (d[0], d[1]))


def npm_audit(project: str, npm: str = 'npm'):
    """
    [(name, versions, [vuln dicts])] for one npm project, from its lock alone
    (`--package-lock-only`) and only what `npm ci --omit=optional` installs.
    Vuln dicts carry the same keys as pip-audit's (id, aliases, fix_versions),
    so exceptions and the report treat both alike.
    """
    _proc = _run([npm, 'audit', '--package-lock-only', '--omit=optional', '--json',
                  '--prefix', project])
    try:
        _data = json.loads(_proc.stdout)
        _vulns = _data['vulnerabilities']
    except (ValueError, KeyError, TypeError):
        raise ScanError('npm audit on {} did not produce a result (exit {}):\n{}'.format(
            project, _proc.returncode, (_proc.stderr or _proc.stdout).strip()[-2000:]))
    _lock = json.load(open(os.path.join(REPO, project, 'package-lock.json'), encoding='utf-8'))
    # every installed package, vulnerable or not, as pip-audit lists them
    _by_name = {(check_components.norm(_k.rsplit('node_modules/', 1)[-1]), _e.get('version', '?')): {}
                for _k, _e in _lock.get('packages', {}).items()
                if _k and not _e.get('optional') and not _e.get('link')}
    for _entry in _vulns.values():
        for _via in _entry.get('via') or []:
            if not isinstance(_via, dict):
                continue            # a dependent of a vulnerable package: its advisory is listed there
            _id = str(_via.get('url', '')).rstrip('/').rsplit('/', 1)[-1] or str(_via.get('source'))
            _versions = sorted({_lock['packages'].get(_n, {}).get('version', '?')
                                for _n in _entry.get('nodes') or []})
            _key = (check_components.norm(_via['name']), ', '.join(_versions))
            _by_name.setdefault(_key, {})[_id] = {
                'id': _id, 'aliases': [], 'title': _via.get('title', ''),
                'fix_versions': ['不在 {} 内的版本'.format(_via['range'])] if _via.get('range') else []}
    return sorted(((_n, _v, sorted(_d.values(), key=lambda v: v['id']))
                   for (_n, _v), _d in _by_name.items()), key=lambda d: (d[0], d[1]))


def bandit():
    """(results, skipped count) for src/."""
    _proc = _run([sys.executable, '-m', 'bandit', '-r', 'src', '-f', 'json', '-q'])
    try:
        _data = json.loads(_proc.stdout)
    except ValueError:
        raise ScanError('bandit did not produce a result (exit {}):\n{}'.format(
            _proc.returncode, _proc.stderr.strip()[-2000:]))
    if _data.get('errors'):
        raise ScanError('bandit could not scan: {}'.format(_data['errors']))
    return _data['results'], _data['metrics']['_totals'].get('skipped_tests', 0)


def annotations():
    """[(test id, path, reason or None)] for every `# nosec` under src/."""
    _out = []
    for _root, _dirs, _files in os.walk(os.path.join(REPO, 'src')):
        _dirs[:] = sorted(d for d in _dirs if d != '__pycache__')
        for _file in sorted(f for f in _files if f.endswith('.py')):
            _path = os.path.join(_root, _file)
            _lines = open(_path, encoding='utf-8').read().splitlines()
            for _i, _line in enumerate(_lines):
                _m = re.search(r'#\s*nosec\b\s*(B\d+)?', _line)
                if not _m:
                    continue
                _id = _m.group(1) or '(all)'
                _above = _lines[_i - 1].strip() if _i else ''
                _r = re.match(r'#\s*bandit\s+' + re.escape(_id) + r':\s*(.+)$', _above)
                _out.append((_id, os.path.relpath(_path, REPO), _r.group(1) if _r else None))
    return _out


def licenses(python: str):
    _proc = _run([python, os.path.join('scripts', 'check_components.py'), '--licenses-json'])
    if _proc.returncode:
        raise ScanError('license scan failed with {}:\n{}'.format(python, _proc.stderr[-2000:]))
    return json.loads(_proc.stdout)


def locked(lock: str):
    """Names a lock file pins. The report lists these and nothing else: an
    environment also holds what created it -- the venv's own pip, at whatever
    version that machine's Python seeds -- and a report that listed it would
    change with the machine that ran the scan, not with the code."""
    _out = set()
    for _line in open(os.path.join(REPO, lock), encoding='utf-8'):
        _m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)==', _line)
        if _m:
            _out.add(check_components.norm(_m.group(1)))
    return _out


def tool_versions():
    _out = {}
    for _line in open(os.path.join(REPO, 'requirements', 'tools.txt'), encoding='utf-8'):
        _m = re.match(r'^(pip-audit|bandit)==(\S+)', _line)
        if _m:
            _out[_m.group(1)] = _m.group(2)
    return _out


# -- assessment --------------------------------------------------------------

NPM_LABELS = {
    'bench/android': 'Android 对比作业专用：Appium 服务端与 UiAutomator2 驱动（npm，不安装到用户环境）',
}


def assess(runtime_python: str, today: datetime.date, npm: str = 'npm', bench_python: str = None):
    _excepted = check_components.active_exceptions(today)

    _s = {'locks': [], 'vulns': [], 'blocking': []}
    _scans = [(_lock, _label, audit) for _lock, _label in LOCKS] + [
        (os.path.join(_project, 'package-lock.json'), NPM_LABELS.get(_project, 'npm'),
         lambda _l: npm_audit(os.path.dirname(_l), npm))
        for _project in check_components.npm_projects()]
    for _lock, _label, _scan in _scans:
        _deps = _scan(_lock)
        _open = 0
        for _name, _version, _vulns in _deps:
            for _v in _vulns:
                _ids = [_v['id']] + list(_v.get('aliases') or [])
                _exc = next((_excepted[_i] for _i in _ids if _i in _excepted), None)
                _s['vulns'].append({'id': _v['id'], 'aliases': sorted(_v.get('aliases') or []),
                                    'name': _name, 'version': _version, 'lock': _lock,
                                    'fix': ', '.join(_v.get('fix_versions') or []) or '暂无',
                                    'exception': _exc})
                if not _exc:
                    _open += 1
                    _s['blocking'].append('{} {} ({}): {}'.format(_name, _version, _lock, _v['id']))
        _s['locks'].append({'lock': _lock, 'label': _label, 'packages': len(_deps),
                            'vulns': sum(len(_v) for _, _, _v in _deps), 'open': _open})

    _results, _skipped = bandit()
    _s['bandit'] = sorted((_r['test_id'], _r['issue_severity'], _r['filename'],
                           _r['issue_text']) for _r in _results)
    _s['annotations'] = annotations()
    for _t, _sev, _f, _text in _s['bandit']:
        _s['blocking'].append('bandit {} ({}) in {}: {}'.format(_t, _sev, _f, _text))
    for _id, _path, _reason in _s['annotations']:
        if not _reason:
            _s['blocking'].append('`# nosec {}` in {} has no `# bandit {}: <reason>` line '
                                  'directly above it'.format(_id, _path, _id))
    if _skipped != len(_s['annotations']):
        _s['blocking'].append('bandit skipped {} findings but {} annotations were found: an '
                              'annotation is not in the expected form'.format(
                                  _skipped, len(_s['annotations'])))

    # Every distribution in either environment is checked; only the locked
    # ones (and the framework itself) are listed, see locked().
    _s['licenses'] = {}
    _envs = [('runtime', runtime_python, 'requirements/ci.txt'),
             ('tools', sys.executable, 'requirements/tools.txt')]
    if bench_python:
        _envs.append(('bench', bench_python, 'requirements/bench.txt'))
    for _env, _python, _lock in _envs:
        _dists = licenses(_python)
        for _name, _d in _dists.items():
            if not _d['allowed']:
                _s['blocking'].append('license not on the allowlist ({}): {} {} ({})'.format(
                    _env, _name, _d['version'], _d['license'] or 'none stated'))
        _keep = locked(_lock) | {'intellipandora'}
        # Listed: the locked ones. Judged: all of them -- a disallowed license
        # on something unlocked (a seeded pip, a stray setuptools) blocks the
        # scan, and the verdict line used to say "passed" beside a failing job
        # because it only looked at the listed ones.
        _s['licenses'][_env] = {_n: _d for _n, _d in _dists.items()
                                if _n in _keep or not _d['allowed']}

    # npm: what `npm ci --omit=optional` installs, read from the lock (hashes,
    # registry, licenses). Not from an installed tree: there is none in this job.
    _s['npm_problems'], _s['npm_licenses'] = check_components.check_npm_locks()
    _s['blocking'] += _s['npm_problems']

    _s['registry'] = check_components.check_registry()
    _s['components'] = len(check_components.declared())
    _s['exception_problems'] = check_components.check_exceptions(today)
    _s['exceptions'] = check_components.exceptions()
    _s['blocking'] += _s['registry'] + _s['exception_problems']
    _s['tools'] = tool_versions()
    return _s


# -- report ------------------------------------------------------------------

def _verdict(ok: bool) -> str:
    return '通过' if ok else '**未通过**'


def _cell(text: str) -> str:
    # GitHub renders raw HTML inside Markdown: a reason that mentions <span>
    # would vanish from the page, an advisory text could inject markup.
    return ((text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('|', '\\|').replace('\n', ' '))


def render(s, date: str) -> str:
    _bandit_ok = not s['bandit'] and all(_r for _, _, _r in s['annotations'])
    _lic = s['licenses']
    _bad_lic = [(_e, _n) for _e, _d in _lic.items() for _n, _v in _d.items() if not _v['allowed']]
    _out = [
        '# 安全报告',
        '',
        '> 本页由 `scripts/security_report.py` 生成。每个 PR、每次合入 main、以及每天定时都会扫描一次'
        '（[`security.yml`]({})）。'.format(ACTIONS),
        '> 只有结论变化时才会更新本页，所以下面的日期是**状态最近一次变化的日期**，不是最近一次扫描的日期。'
        '最近一次扫描的结果见 [Actions]({})。'.format(ACTIONS),
        '>',
        '> 组件如何准入见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md)，'
        '已准入的组件见 [组件登记表](components.md)，已登记的漏洞例外见 [例外登记](exceptions.md)。',
        '',
        '状态日期：{}'.format(date),
        '',
        '## 结论',
        '',
        '| 检查 | 范围 | 结果 |',
        '|---|---|---|',
    ]
    for _l in s['locks']:
        _res = '{}：{} 个包，{} 个已知漏洞'.format(_verdict(not _l['open']), _l['packages'],
                                           _l['vulns'])
        if _l['vulns'] and not _l['open']:
            _res += '（均已登记例外）'
        _out.append('| 依赖漏洞 | `{}`：{} | {} |'.format(_l['lock'], _l['label'], _res))
    _out.append('| 自身代码 | `src/`，bandit 静态扫描 | {}：{} 个未处理问题，{} 处经评估标注（理由见下） |'.format(
        _verdict(_bandit_ok), len(s['bandit']), len(s['annotations'])))
    _reviewed = sorted({_n for _d in _lic.values() for _n, _v in _d.items() if _v.get('reviewed')})
    _lic_text = ('：{} 个不在白名单'.format(len(_bad_lic)) if _bad_lic
                 else '：全部在白名单内' if not _reviewed
                 else '：其余在白名单内，{} 经人工审查（见下）'.format('、'.join(_reviewed)))
    _out.append('| 许可证 | 运行环境 {} 个分发包、工具链与对比作业 {} 个（含间接依赖） | {} |'.format(
        len(_lic['runtime']), len(_lic['tools']) + len(_lic.get('bench', {})),
        _verdict(not _bad_lic) + _lic_text))
    if s['npm_licenses'] or s['npm_problems']:
        _npm_reviewed = sorted({_t for _t in s['npm_licenses'].values()
                                if _t in check_components.NPM_REVIEWED_LICENSES})
        _out.append('| npm 锁文件 | {} 个包（含间接依赖）：哈希、来源、许可证 | {} |'.format(
            len(s['npm_licenses']), _verdict(not s['npm_problems']) + (
                '：{} 处问题'.format(len(s['npm_problems'])) if s['npm_problems']
                else '：全部来自 npm 官方仓库、带 sha512；许可证在白名单内{}'.format(
                    '，{} 经人工审查（见下）'.format('、'.join(_npm_reviewed)) if _npm_reviewed else ''))))
    _out.append('| 组件登记 | {} 个直接依赖与 CI 动作 | {} |'.format(
        s['components'], _verdict(not s['registry']) + (
            '：与代码声明一致' if not s['registry'] else '：{} 处不一致'.format(len(s['registry'])))))
    _out.append('| 漏洞例外 | 例外登记表 | {}：{} 条{} |'.format(
        _verdict(not s['exception_problems']), len(s['exceptions']),
        '' if not s['exception_problems'] else '，{} 条已过期或不完整'.format(
            len(s['exception_problems']))))
    _out += ['', '## 漏洞明细', '']
    if not s['vulns']:
        _out.append('无。所有锁定版本均没有已公开的漏洞。')
    else:
        _out += ['| 编号 | 组件 | 版本 | 修复版本 | 锁文件 | 处理 |', '|---|---|---|---|---|---|']
        for _v in sorted(s['vulns'], key=lambda v: (v['name'], v['id'], v['lock'])):
            _ids = _v['id'] + ('（{}）'.format('、'.join(_v['aliases'])) if _v['aliases'] else '')
            _how = ('已登记例外，{} 到期：{}'.format(_v['exception']['expires'],
                                             _cell(_v['exception']['reason']))
                    if _v['exception'] else '**待处理**')
            _out.append('| {} | {} | {} | {} | `{}` | {} |'.format(
                _ids, _v['name'], _v['version'], _v['fix'], _v['lock'], _how))
    _out += ['', '## 自身代码的标注', '',
             'bandit 报出、经评估不构成问题的地方，在源码里标注 `# nosec` 并在上一行写明理由。'
             '没有理由的标注会让扫描失败。', '']
    if s['bandit']:
        _out += ['未处理的问题：', '', '| 规则 | 级别 | 文件 | 说明 |', '|---|---|---|---|']
        for _t, _sev, _f, _text in s['bandit']:
            _out.append('| {} | {} | `{}` | {} |'.format(_t, _sev, _f, _cell(_text)))
        _out.append('')
    if s['annotations']:
        _out += ['| 规则 | 文件 | 理由 |', '|---|---|---|']
        for _id, _path, _reason in sorted(s['annotations']):
            _out.append('| {} | `{}` | {} |'.format(_id, _path, _cell(_reason) or '**缺少理由**'))
    else:
        _out.append('无。')
    _out += ['', '## 许可证', '',
             '白名单为宽松许可证（MIT、BSD、Apache、ISC、MPL-2.0、PSF 等），不接受 GPL 系、SSPL、'
             'BUSL 等，理由见 [`docs/design/decisions/15`](../design/decisions/15-第三方组件安全准入与漏洞扫描.md) §3。', '']
    for _env, _title in (('runtime', '运行环境（框架 + 全部可选组，即用户可能装上的全部）'),
                         ('tools', '构建与工具链'),
                         ('bench', 'Android 对比作业专用（Python）')):
        if _env not in _lic:
            continue
        _out += ['<details><summary>{}：{} 个</summary>'.format(_title, len(_lic[_env])), '',
                 '| 分发包 | 版本 | 许可证 | 结果 |', '|---|---|---|---|']
        for _name, _d in sorted(_lic[_env].items()):
            _out.append('| {} | {} | {} | {} |'.format(
                _name, _d['version'], _cell(_d['license']) or '未声明',
                ('通过（人工审查：{}）'.format(_cell(_d['reviewed'])) if _d.get('reviewed')
                 else '通过' if _d['allowed'] else '**未通过**')))
        _out += ['', '</details>', '']
    if s['npm_licenses']:
        _out += ['<details><summary>npm（Android 对比作业专用）：{} 个</summary>'.format(
                     len(s['npm_licenses'])), '',
                 '| 包 | 许可证 | 结果 |', '|---|---|---|']
        for _id, _text in sorted(s['npm_licenses'].items()):
            _review = check_components.NPM_REVIEWED_LICENSES.get(_text)
            _out.append('| {} | {} | {} |'.format(
                _cell(_id), _cell(_text) or '未声明',
                '通过（人工审查：{}）'.format(_cell(_review)) if _review
                else '通过' if _text and check_components.license_ok(_text) else '**未通过**'))
        _out += ['', '</details>', '']
    _out += [
        '## 怎么扫的', '',
        '- **依赖漏洞**：pip-audit {}，对每个锁文件逐一扫描，查询 PyPI 漏洞库。'
        '扫的是锁文件本身（`--require-hashes`），也就是 CI 实际安装的每一个文件，'
        '而不是某台机器上碰巧装着的版本。'.format(s['tools'].get('pip-audit', '?')),
        '- **自身代码**：bandit {}，扫描 `src/` 下全部代码，任何级别的问题都会让扫描失败。'.format(
            s['tools'].get('bandit', '?')),
        '- **npm 依赖**：`npm audit --package-lock-only --omit=optional`，对每个 npm 锁文件扫描，'
        '查询 GitHub 漏洞库；只扫 `npm ci --omit=optional` 会装的包。锁文件里每个包的来源、'
        'sha512 和许可证由 `check_components.py` 离线核对。',
        '- **许可证**：读取环境中每个分发包的元数据，包括间接依赖，因为它们同样会被装到用户环境。',
        '- **组件登记**：`setup.cfg`、`setup.py`、`requirements/*.in` 和工作流里引用的每个组件，'
        '都必须在登记表里出现且版本写法一致。',
        '- **新版本冷静期**：锁文件只接受发布满 14 天的版本（`scripts/update_locks.py`），'
        '恶意版本通常在几天内就会被发现并撤下。',
        '',
    ]
    return '\n'.join(_out)


def write(s, path: str, today: datetime.date) -> bool:
    """Write the report unless only the date would change. True if written."""
    _old = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    _m = re.search(r'^状态日期：(\d{4}-\d{2}-\d{2})$', _old, re.M)
    if _m and render(s, _m.group(1)) == _old:
        return False
    with open(path, 'w', encoding='utf-8') as _f:
        _f.write(render(s, today.isoformat()))
    return True


def main(argv) -> int:
    _p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    _p.add_argument('--runtime-python', default=sys.executable)
    _p.add_argument('--npm', default='npm', help='npm used for `npm audit` (default: npm on PATH)')
    _p.add_argument('--bench-python', default=None,
                    help='an interpreter installed from requirements/bench.txt: its licenses are checked too')
    _p.add_argument('--out', default=REPORT)
    _p.add_argument('--summary', default=os.environ.get('GITHUB_STEP_SUMMARY'),
                    help='also append the report here (default: $GITHUB_STEP_SUMMARY)')
    _opts = _p.parse_args(argv)
    _today = datetime.date.today()
    try:
        _s = assess(_opts.runtime_python, _today, _opts.npm, _opts.bench_python)
    except ScanError as _e:
        print('scan could not run, report not written:\n' + str(_e), file=sys.stderr)
        return 2

    _changed = write(_s, _opts.out, _today)
    print('{}: {}'.format(os.path.relpath(_opts.out, REPO), 'updated' if _changed else 'unchanged'))
    if _opts.summary:
        with open(_opts.summary, 'a', encoding='utf-8') as _f:
            _f.write(open(_opts.out, encoding='utf-8').read())
    for _problem in _s['blocking']:
        print('  ' + _problem, file=sys.stderr)
    if _s['blocking']:
        print('\n{} blocking finding(s). See docs/security/report.md for the full picture and '
              'docs/design/decisions/15-第三方组件安全准入与漏洞扫描.md for what to do.'.format(
                  len(_s['blocking'])), file=sys.stderr)
        return 1
    print('OK: no known vulnerabilities, no unannotated code findings, licenses allowed, '
          'registry consistent')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

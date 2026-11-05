#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mutation testing: break the code on purpose and check the suite notices.

A passing suite proves almost nothing on its own. It can pass because the code
is right, or because the tests never look at the part that is wrong. The only
way to tell those apart is to introduce a defect and watch what happens -- if
everything stays green, the tests were decorative.

This repo has done that by hand since P1, one mutation at a time, written up in
each design doc (restore `self.key = pem_key` -> 3 cases fail; make `header_is`
always true -> 1 fails; treat an unparseable body as `{}` -> 2 fail; put the
keystore back inside the package -> 1 fails). It also caught a case that passed
for the wrong reason, and one "fix" that turned out to be waste rather than a
defect because *no* case failed when it was reverted.

This script is that practice, automated and scored, which is what the plan's
阶段 3 completion standard asks for ("注入错误抽查 ... 比例达到约定值").

    scripts/mutation.py core/report/junit.py --tests test/testreport/test_junit.py
    scripts/mutation.py core/assertion --min-score 80

Scope every run. Mutating all of src/ at once means re-running the suite once
per mutant across ~10k lines; pairing one module with its own tests keeps a run
to minutes. `--min-score` turns it into a gate.

Reading the score
-----------------
killed / (killed + survived). Mutants that time out count as killed -- the
suite noticed, just slowly. `skipped` and `suspicious` are left out of the
denominator rather than guessed at.

A survivor is not automatically a bug in the tests. Some mutations do not
change behaviour at all (reordering an unordered set, a log string), and a
survivor there means the mutation was equivalent, not that a case is missing.
The score is a prompt to go look, never a target to optimise.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join('src', 'ipandora')

# mutmut prints one line per mutant; the summary counts come from `results`.
VERDICTS = ('killed', 'survived', 'timeout', 'suspicious', 'skipped',
            'no_tests', 'segfault')


def resolve(target: str) -> str:
    """Accept `core/report/junit.py`, `src/ipandora/core/...`, or a package."""
    _candidates = [target, os.path.join(SRC, target)]
    for _c in _candidates:
        if os.path.exists(os.path.join(REPO, _c)):
            return _c.replace('\\', '/')
    raise SystemExit('no such module or package: {}'.format(target))


def guess_tests(path: str) -> str:
    """
    The test directory that most likely covers this module.

    A guess, printed so it can be overridden: `src/ipandora/core/report/x.py`
    -> `test/testreport`. Wrong guesses make a run slow or empty, not wrong.
    """
    _parts = path.replace('\\', '/').split('/')
    if SRC.replace('\\', '/') in path:
        _parts = _parts[len(SRC.split(os.sep)):]
    _name = _parts[-2] if len(_parts) > 1 else os.path.splitext(_parts[-1])[0]
    for _candidate in ('test/test{}'.format(_name), 'test/test{}s'.format(_name)):
        if os.path.isdir(os.path.join(REPO, _candidate)):
            return _candidate
    return 'test'


def write_scoped_config(module: str, tests: str) -> str:
    """
    Point mutmut at one module and one set of tests, keeping the base config.

    Written to setup.cfg because that is where mutmut reads from; the original
    is restored in `main`'s finally, including when the run is interrupted.
    """
    _path = os.path.join(REPO, 'setup.cfg')
    with open(_path, encoding='utf-8') as fh:
        _text = fh.read()

    # `only_mutate`, not `source_paths`. Narrowing source_paths to one file
    # makes mutmut copy only that file into its work directory, so the rest of
    # the package is missing and the module cannot even be imported -- every
    # mutant then "fails" for a reason that has nothing to do with the mutant.
    _scoped = _text.replace(
        '[mutmut]\n',
        '[mutmut]\nonly_mutate = {}\npytest_add_cli_args = {}\n'.format(
            module, tests))
    with open(_path, 'w', encoding='utf-8') as fh:
        fh.write(_scoped)
    return _text


def counts() -> dict:
    """
    Verdict -> count, from mutmut's own CI export.

    Not from `mutmut results`: that lists the *survivors* only. Parsing it for
    a killed count silently yields zero, which reads as "the suite caught
    nothing" -- a 0% score on a module whose tests demonstrably do catch
    things. The first version of this script did exactly that.
    """
    subprocess.run([sys.executable, '-m', 'mutmut', 'export-cicd-stats'],
                   cwd=REPO, capture_output=True, text=True)
    _path = os.path.join(REPO, 'mutants', 'mutmut-cicd-stats.json')
    if not os.path.isfile(_path):
        raise SystemExit('mutmut produced no stats file; the run did not finish')
    with open(_path, encoding='utf-8') as fh:
        _stats = json.load(fh)
    return {_k: int(_stats.get(_k, 0) or 0) for _k in VERDICTS + ('total',)}


def score(counts_map: dict) -> float:
    _killed = counts_map.get('killed', 0) + counts_map.get('timeout', 0)
    _survived = counts_map.get('survived', 0)
    _total = _killed + _survived
    return (100.0 * _killed / _total) if _total else 0.0


def main(argv=None) -> int:
    _parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    _parser.add_argument('target', help='module or package, e.g. core/report/junit.py')
    _parser.add_argument('--tests', default=None,
                         help='tests to run against each mutant. Default: guessed')
    _parser.add_argument('--min-score', type=float, default=None,
                         help='fail below this percentage, to use it as a gate')
    _parser.add_argument('--json', dest='as_json', action='store_true',
                         help='print the counts as JSON')
    _options = _parser.parse_args(argv)

    _module = resolve(_options.target)
    _tests = _options.tests or guess_tests(_module)
    print('mutating {}'.format(_module))
    print('against  {}{}'.format(_tests, '' if _options.tests else '  (guessed)'))

    _original = write_scoped_config(_module, _tests)
    try:
        shutil.rmtree(os.path.join(REPO, 'mutants'), ignore_errors=True)
        subprocess.run([sys.executable, '-m', 'mutmut', 'run'], cwd=REPO)
        _counts = counts()
    finally:
        with open(os.path.join(REPO, 'setup.cfg'), 'w', encoding='utf-8') as fh:
            fh.write(_original)

    _score = score(_counts)
    if _options.as_json:
        print(json.dumps({'module': _module, 'tests': _tests,
                          'score': round(_score, 1), 'counts': _counts},
                         ensure_ascii=False))
    else:
        print('')
        print('  杀死 {} · 存活 {} · 超时 {}'.format(
            _counts.get('killed', 0), _counts.get('survived', 0),
            _counts.get('timeout', 0)))
        print('  变异得分 {:.1f}%'.format(_score))
        if _counts.get('survived'):
            print('')
            print('  看存活的那些：mutmut results，然后 mutmut show <name>')
            print('  存活不一定是测试的漏洞——不改变行为的变异本来就杀不掉。')

    if _options.min_score is not None and _score < _options.min_score:
        print('\n变异得分 {:.1f}% 低于要求的 {:.1f}%'.format(
            _score, _options.min_score), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : render.py
@Time  : 2026-08-01
"""
import html
import json
import os
import re
import shlex

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from ipandora.core.report.junit import to_junit
from ipandora.core.report.model import ReportData
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

TEMPLATE = 'conf/static/report.html'

_JSON_TOKEN = re.compile(
    r'("(?:\\.|[^"\\])*")(\s*:)?'          # string, and whether it is a key
    r'|(\btrue\b|\bfalse\b|\bnull\b)'      # literal
    r'|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)')  # number


def pretty(body) -> str:
    """Re-indent a JSON body; anything else comes back as-is."""
    if body is None:
        return ''
    if not isinstance(body, str):
        try:
            return json.dumps(body, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(body)
    try:
        return json.dumps(json.loads(body), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return body


def highlight_json(text: str) -> Markup:
    """
    Colour a JSON body for the report.

    Every span of the input -- matched token and the gaps between -- is passed
    through html.escape before it becomes markup. This is the one place the
    report emits HTML it built itself rather than letting Jinja escape it, and
    the content is a response body from the system under test, so nothing may
    reach the page unescaped.
    """
    if text is None or text == '':
        return Markup('')
    if not isinstance(text, str):
        # a body the recorder could not turn into text -- a number, a dict
        # handed over as-is -- used to raise TypeError and take the whole
        # report with it
        text = json.dumps(text, ensure_ascii=False, indent=2, default=str) \
            if isinstance(text, (dict, list)) else str(text)
    _out, _pos = [], 0
    for _match in _JSON_TOKEN.finditer(text):
        _out.append(html.escape(text[_pos:_match.start()]))
        _string, _colon, _literal, _number = _match.groups()
        if _string is not None:
            _out.append('<span class="{}">{}</span>'.format(
                'jk' if _colon else 'js', html.escape(_string)))
            if _colon:
                _out.append(html.escape(_colon))
        elif _literal is not None:
            _out.append('<span class="jb">{}</span>'.format(html.escape(_literal)))
        else:
            _out.append('<span class="jn">{}</span>'.format(html.escape(_number)))
        _pos = _match.end()
    _out.append(html.escape(text[_pos:]))
    # bandit B704: all text went through html.escape; only our own span tags are raw
    return Markup(''.join(_out))  # nosec B704


def to_curl(exchange: dict) -> str:
    """
    The exchange as a runnable command.

    Reproducing a failure by hand is the first thing anyone does with a report;
    this removes the retyping. Headers are already redacted by the time they
    get here, so the command needs the credential filled back in -- which is
    the correct trade: a report that pastes working credentials into a shell
    is a report nobody can safely share.
    """
    _parts = ['curl', '-X', str(exchange.get('method') or 'GET')]
    for _name, _value in (exchange.get('request_headers') or {}).items():
        _parts += ['-H', shlex.quote('{}: {}'.format(_name, _value))]
    _body = exchange.get('request_body')
    if _body:
        # a dict body is sent as JSON; str() of it is a Python repr no server accepts
        _parts += ['--data', shlex.quote(_body if isinstance(_body, str)
                                         else json.dumps(_body, ensure_ascii=False, default=str))]
    _parts.append(shlex.quote(str(exchange.get('url') or '')))
    return ' '.join(_parts)


def duration(ms) -> str:
    """Milliseconds, or seconds once that stops being readable."""
    try:
        _ms = float(ms or 0)
    except (TypeError, ValueError):
        return '—'
    if _ms < 1000:
        return '{:.0f} ms'.format(_ms)
    return '{:.2f} s'.format(_ms / 1000.0)


def display_path(path: str) -> str:
    """A path as a reader recognises it: relative to the project when it is inside."""
    if not path or not os.path.isabs(path):
        return path or ''
    try:
        _rel = os.path.relpath(path)
    except ValueError:      # another drive on Windows
        return path
    return path if _rel.startswith('..') else _rel


def environment() -> Environment:
    # autoescape matters here: failure messages contain whatever the system
    # under test returned, and an unescaped payload would both break the page
    # and let a response inject markup into it.
    _env = Environment(
        loader=FileSystemLoader(PathUtils().pandora_path),
        autoescape=select_autoescape(['html']))
    _env.filters.update({'pretty': pretty, 'hljson': highlight_json,
                         'curl': to_curl, 'ms': duration})
    from ipandora.core.triage.category import CONFIDENCE_LABEL, LABEL
    _env.globals.update({'category_label': LABEL, 'confidence_label': CONFIDENCE_LABEL})
    return _env


def to_html(report: ReportData, template: str = TEMPLATE) -> str:
    """Render report data to HTML."""
    _context = report.to_dict()
    # The ReportCase objects, not their dicts: the template reads derived
    # properties (judgements, gaps, slowest_exchange) that only exist on the
    # object. The dict form is what the JSON artifact serialises.
    _context.update({
        'by_suite': report.by_suite,
        'inconclusive': report.inconclusive,
        'failures': report.failures,
        'coverage': report.coverage_matrix,
        'gap_list': report.gaps,
        'check_totals': report.check_totals,
        'by_source': report.by_source,
        'attention': report.attention,
        'weak_by_case': report.weakened_by_case,
        'case_by_id': {_c.nodeid: _c for _c in report.cases},
        'baseline_display': display_path(report.baseline),
    })
    return environment().get_template(template).render(**_context)


def to_json(report: ReportData, indent: int = 2) -> str:
    """
    Serialise the report.

    Same data as the HTML, and already redacted -- the JSON is a first-class
    artifact, not a debug dump, so it must not be more revealing than the page.
    """
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def write(report: ReportData, directory: str, basename: str = 'report',
          html: bool = True, as_json: bool = True, junit: bool = True) -> dict:
    """
    Write the report to disk. Returns the paths written.

    All three formats come from the same ReportData, which is the whole reason
    building and rendering are separate steps.

    The HTML is for a person, the JSON for whatever comes next, and the JUnit
    XML for CI and qa-report-visualizer -- the only one of the three whose
    shape is not ours to choose. It is written by default because a gate
    nobody remembers to ask for is a gate that is not there.
    """
    os.makedirs(directory, exist_ok=True)
    _written = {}

    if html:
        _path = os.path.join(directory, '{}.html'.format(basename))
        with open(_path, 'w', encoding='utf-8') as fh:
            fh.write(to_html(report))
        _written['html'] = _path

    if as_json:
        _path = os.path.join(directory, '{}.json'.format(basename))
        with open(_path, 'w', encoding='utf-8') as fh:
            fh.write(to_json(report))
        _written['json'] = _path

    if junit:
        _path = os.path.join(directory, '{}.xml'.format(basename))
        with open(_path, 'w', encoding='utf-8') as fh:
            fh.write(to_junit(report))
        _written['junit'] = _path

    logger.info('report written: %s', ', '.join(_written.values()))
    return _written

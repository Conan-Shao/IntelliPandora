# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : render.py
@Time  : 2026-08-01
"""
import json
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ipandora.core.report.model import ReportData
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

TEMPLATE = 'conf/static/report.html'


def _environment() -> Environment:
    # autoescape matters here: failure messages contain whatever the system
    # under test returned, and an unescaped payload would both break the page
    # and let a response inject markup into it.
    return Environment(
        loader=FileSystemLoader(PathUtils().pandora_path),
        autoescape=select_autoescape(['html']))


def to_html(report: ReportData, template: str = TEMPLATE) -> str:
    """Render report data to HTML."""
    _context = report.to_dict()
    _context.update({
        'by_suite': report.by_suite,
        'inconclusive': report.inconclusive,
        'failures': report.failures,
    })
    return _environment().get_template(template).render(**_context)


def to_json(report: ReportData, indent: int = 2) -> str:
    """
    Serialise the report.

    Same data as the HTML, and already redacted -- the JSON is a first-class
    artifact, not a debug dump, so it must not be more revealing than the page.
    """
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def write(report: ReportData, directory: str, basename: str = 'report',
          html: bool = True, as_json: bool = True) -> dict:
    """
    Write the report to disk. Returns the paths written.

    Both formats come from the same ReportData, which is the whole reason
    building and rendering are separate steps.
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

    logger.info('report written: %s', ', '.join(_written.values()))
    return _written

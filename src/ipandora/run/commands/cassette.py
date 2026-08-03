# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : cassette.py
@Time  : 2026-08-03
"""
import json
import os
import sys
from argparse import Namespace

from ipandora.run.commandbase import CommandBase

STALE_DAYS = 30
"""
When a cassette starts being reported as old.

A tape nobody re-records keeps a suite green while it tests an assumption
nobody holds anymore, and it does so silently. Showing the age is the cheap
half of the fix; `run --max-cassette-age` is the half that can gate a build.
"""


class Command(CommandBase):
    """Look after the tapes: list, inspect, import captured traffic, export."""

    def handle(self, options: Namespace):
        _action = getattr(options, 'cassette_action', None)
        if not _action:
            self.parser.print_help()
            return
        getattr(self, '_{}'.format(_action))(options)

    # -- list --------------------------------------------------------------

    @staticmethod
    def _list(options):
        from ipandora.core.cassette.store import cassettes_dir, list_cassettes

        _entries = list_cassettes(options.dir)
        if not _entries:
            print('还没有磁带（在 {}）。\n'
                  '录一盘：ipandora run <selector> --record --cassette <name>'
                  .format(cassettes_dir(options.dir)))
            return

        print('{:<28} {:>7} {:>7} {:>10}  {}'.format(
            '磁带', '条数', 'blobs', '录于', '来源'))
        for _entry in _entries:
            _age = _entry['age_days']
            _when = '—' if _age is None else '{:.0f} 天前'.format(_age)
            if _age is not None and _age > STALE_DAYS:
                _when += ' ⚠'
            print('{:<28} {:>7} {:>7} {:>10}  {}'.format(
                _entry['name'], _entry['count'], _entry['blobs'], _when,
                _entry['recorded_from'] or '—'))

    # -- show --------------------------------------------------------------

    @staticmethod
    def _show(options):
        from ipandora.core.cassette import Cassette

        _tape = Cassette(options.name, directory=options.dir).load()
        if not _tape.store.exists:
            raise SystemExit('没有名为 {!r} 的磁带（在 {}）'.format(
                options.name, _tape.store.root))

        _age = _tape.age_days
        print('{}  {} 条 · {} 个 blob{}'.format(
            options.name, _tape.total, _tape.store.blob_count(),
            ' · 录于 {:.0f} 天前'.format(_age) if _age is not None else ''))
        print('路径  {}'.format(_tape.store.root))
        if _tape.manifest.recorded_from:
            print('来源  {}'.format(_tape.manifest.recorded_from))
        print('')

        for _key, _records in _tape._records.items():  # noqa: SLF001 - same package
            _first = _records[0]
            print('{:<4} {}'.format(len(_records), _key))
            if options.verbose:
                print('     {} {} → {}'.format(_first.method, _first.url,
                                               _first.status))

    # -- import ------------------------------------------------------------

    @staticmethod
    def _import(options):
        from ipandora.core.cassette.importers import import_into

        _fields = {}
        for _pair in options.field or ():
            if '=' not in _pair:
                raise SystemExit('--field 需要 name=value，收到 {!r}'.format(_pair))
            _key, _value = _pair.split('=', 1)
            _fields[_key.strip()] = _value.strip()

        _report = import_into(options.name, options.path, fmt=options.format,
                              directory=options.dir, fields=_fields or None,
                              recorded_from=options.recorded_from,
                              force=options.force)
        print(_report.describe())

        if not _report.imported:
            raise SystemExit('  没有可导入的记录。')
        if not _report.usable and not options.force:
            # Refusing is the feature. An unreplayable cassette looks exactly
            # like a good one -- right count, right URLs, green import -- and
            # only fails much later, somewhere else.
            raise SystemExit(
                '  未写入磁带。采集端开启 body 记录后重新导出，'
                '或用 --force 明确接受一盘只有请求没有响应的磁带。')
        print('\n  已写入。检查一下：ipandora cassette show {}'.format(options.name))

    # -- export ------------------------------------------------------------

    @staticmethod
    def _export(options):
        from ipandora.core.cassette.importers import to_har
        from ipandora.core.cassette.store import CassetteStore

        _store = CassetteStore(options.name, options.dir)
        if not _store.exists:
            raise SystemExit('没有名为 {!r} 的磁带'.format(options.name))

        _har = to_har(options.name, options.dir)
        _text = json.dumps(_har, ensure_ascii=False, indent=2)
        if options.output in ('-', None):
            sys.stdout.write(_text)
            return
        with open(options.output, 'w', encoding='utf-8') as fh:
            fh.write(_text)
        print('{} 条 → {}'.format(len(_har['log']['entries']),
                                  os.path.abspath(options.output)))

    # -- wiring ------------------------------------------------------------

    @property
    def help(self):
        return 'inspect cassettes, import captured traffic, export to HAR'

    @property
    def sub_command_name(self):
        return 'cassette'

    def add_arguments(self):
        self.parser.add_argument(
            '-d', '--dir', default=None,
            help='where cassettes live. Default: $IPANDORA_CASSETTES_DIR '
                 'or ~/.ipandora/cassettes')

        _sub = self.parser.add_subparsers(dest='cassette_action')

        _sub.add_parser('list', help='every cassette, with its age')

        _show = _sub.add_parser('show', help='what is on one cassette')
        _show.add_argument('name')
        _show.add_argument('-v', '--verbose', action='store_true',
                           help='show the first request behind each key')

        _import = _sub.add_parser(
            'import',
            help='read captured traffic (HAR / nginx JSON log / envoy tap) '
                 'into a cassette')
        _import.add_argument('name', help='cassette to create')
        _import.add_argument('path', help='the capture file')
        _import.add_argument(
            '-f', '--format', default='', choices=['', 'har', 'nginx', 'envoy'],
            help='capture format. Default: guessed from the file')
        _import.add_argument(
            '--field', action='append', default=[],
            help='nginx only: override a log field, e.g. --field url=uri. '
                 'Repeatable, because no two sites name these the same')
        _import.add_argument(
            '--recorded-from', default='',
            help='where this traffic came from, recorded in the manifest')
        _import.add_argument(
            '--force', action='store_true',
            help='write the cassette even when too few exchanges carry a '
                 'response body -- such a tape cannot be replayed or diffed')

        _export = _sub.add_parser('export', help='write a cassette out as HAR')
        _export.add_argument('name')
        _export.add_argument('-o', '--output', default='-',
                             help='file to write. Default: stdout')

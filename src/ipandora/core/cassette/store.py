# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : store.py
@Time  : 2026-08-02

Reading and writing a cassette directory.

    <name>/
      manifest.yaml       metadata, match rules, difference tolerances
      exchanges.jsonl     one line per exchange, appended as it is recorded
      blobs/              large bodies, addressed by content

Redaction happens here, on the way in. Not on the way out, and not at display
time: a cassette gets committed, copied, attached to a ticket and eventually
imported from production traffic, so the moment it touches disk it has to be
already safe to hand to anyone who can read the repository.
"""
import hashlib
import json
import os
import shutil
from typing import Any, Dict, Iterator, List, Optional

import yaml

from ipandora.core.cassette.matcher import MatchRules
from ipandora.core.cassette.model import INLINE_BODY_CHARS, Manifest, Record
from ipandora.core.report.redact import redact, redact_body
from ipandora.utils.log import logger
from ipandora.utils.pathutils import PathUtils

DEFAULT_CASSETTES_DIR = os.path.join(PathUtils().home_path, '.ipandora', 'cassettes')
MANIFEST = 'manifest.yaml'
EXCHANGES = 'exchanges.jsonl'
BLOBS = 'blobs'


def cassettes_dir(directory: str = None) -> str:
    return directory or os.environ.get('IPANDORA_CASSETTES_DIR', DEFAULT_CASSETTES_DIR)


def _safe(name: str) -> str:
    # the name becomes a directory
    if not name or os.path.basename(name) != name or name.startswith('.'):
        raise ValueError('invalid cassette name: {!r}'.format(name))
    return name


class CassetteStore:
    """The files. Matching and play semantics live in Cassette."""

    def __init__(self, name: str, directory: str = None):
        self.name = _safe(name)
        self.root = os.path.join(cassettes_dir(directory), self.name)

    # -- paths -------------------------------------------------------------

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.root, MANIFEST)

    @property
    def exchanges_path(self) -> str:
        return os.path.join(self.root, EXCHANGES)

    @property
    def blobs_path(self) -> str:
        return os.path.join(self.root, BLOBS)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.exchanges_path)

    # -- blobs -------------------------------------------------------------

    def _blob_file(self, ref: str) -> str:
        # ref is derived from a hash we computed, but it lands in a path
        if not ref.startswith('sha256-') or '/' in ref or '\\' in ref:
            raise ValueError('invalid blob ref: {!r}'.format(ref))
        return os.path.join(self.blobs_path, ref)

    def put_blob(self, text: str) -> str:
        """Store a body by its content. Identical bodies are stored once."""
        _digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        _ref = 'sha256-{}'.format(_digest)
        _file = self._blob_file(_ref)
        if not os.path.isfile(_file):
            os.makedirs(self.blobs_path, exist_ok=True)
            with open(_file, 'w', encoding='utf-8') as fh:
                fh.write(text)
        return _ref

    def get_blob(self, ref: str) -> Optional[str]:
        _file = self._blob_file(ref)
        if not os.path.isfile(_file):
            return None
        with open(_file, 'r', encoding='utf-8') as fh:
            return fh.read()

    def blob_count(self) -> int:
        if not os.path.isdir(self.blobs_path):
            return 0
        return len(os.listdir(self.blobs_path))

    # -- records -----------------------------------------------------------

    def begin_recording(self) -> None:
        """Start a fresh cassette, discarding whatever was there."""
        if os.path.isdir(self.root):
            shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.root, exist_ok=True)

    def append(self, record: Record) -> Record:
        """
        Add one exchange. Bodies are redacted, then moved to a blob if large.

        Order matters and is not interchangeable: redacting a body after it has
        been hashed into a blob would leave the secret on disk under a name
        derived from it.
        """
        record.request_headers = redact(dict(record.request_headers or {}))
        record.response_headers = redact(dict(record.response_headers or {}))
        record.request_body = redact_body(record.request_body)
        record.response_body = redact_body(record.response_body)

        for _side in ('request', 'response'):
            _body = getattr(record, '{}_body'.format(_side))
            if isinstance(_body, str) and len(_body) > INLINE_BODY_CHARS:
                setattr(record, '{}_body_ref'.format(_side), self.put_blob(_body))
                setattr(record, '{}_body'.format(_side), None)

        os.makedirs(self.root, exist_ok=True)
        with open(self.exchanges_path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + '\n')
        return record

    def read(self) -> Iterator[Record]:
        """
        Every record, in recorded order, with blobs resolved.

        A malformed line is skipped with a warning rather than killing the
        read: a cassette is an artifact that gets edited by hand, and one bad
        line should cost one exchange, not the whole tape.
        """
        if not self.exists:
            return
        with open(self.exchanges_path, 'r', encoding='utf-8') as fh:
            for _number, _line in enumerate(fh, 1):
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _record = Record.from_dict(json.loads(_line))
                except (TypeError, ValueError) as exc:
                    logger.warning('%s line %d is not a valid record: %s',
                                   self.exchanges_path, _number, exc)
                    continue
                if _record.request_body_ref:
                    _record.request_body = self.get_blob(_record.request_body_ref)
                if _record.response_body_ref:
                    _record.response_body = self.get_blob(_record.response_body_ref)
                yield _record

    # -- manifest ----------------------------------------------------------

    def load_manifest(self) -> Manifest:
        if not os.path.isfile(self.manifest_path):
            return Manifest(name=self.name)
        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as fh:
                return Manifest.from_dict(yaml.safe_load(fh) or {})
        except (OSError, yaml.YAMLError) as exc:
            logger.warning('could not read %s: %s', self.manifest_path, exc)
            return Manifest(name=self.name)

    def save_manifest(self, manifest: Manifest) -> str:
        os.makedirs(self.root, exist_ok=True)
        with open(self.manifest_path, 'w', encoding='utf-8') as fh:
            yaml.safe_dump(manifest.to_dict(), fh, allow_unicode=True,
                           sort_keys=False, default_flow_style=False)
        return self.manifest_path

    def rules(self) -> MatchRules:
        return MatchRules.from_dict(self.load_manifest().match)


def list_cassettes(directory: str = None) -> List[Dict[str, Any]]:
    """Every cassette in the directory, with its age -- see Manifest.age_days."""
    _root = cassettes_dir(directory)
    if not os.path.isdir(_root):
        return []
    _out = []
    for _name in sorted(os.listdir(_root)):
        if not os.path.isdir(os.path.join(_root, _name)):
            continue
        try:
            _store = CassetteStore(_name, directory)
        except ValueError:
            continue
        if not _store.exists:
            continue
        _manifest = _store.load_manifest()
        _out.append({'name': _name, 'count': _manifest.count,
                     'recorded_at': _manifest.recorded_at,
                     'recorded_from': _manifest.recorded_from,
                     'age_days': _manifest.age_days(),
                     'blobs': _manifest.blobs, 'path': _store.root})
    return _out

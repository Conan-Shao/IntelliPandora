# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : cassette.py
@Time  : 2026-08-02

The tape, and what it means to play it.
"""
import threading
from typing import Dict, List, Optional

from ipandora.core.cassette.matcher import MatchRules, key_for, nearest
from ipandora.core.cassette.model import Manifest, Miss, Record
from ipandora.core.cassette.store import CassetteStore
from ipandora.utils.log import logger


class Mode:
    """
    How a run treats the tape.

    Never chosen by a test. A test says what it asserts; how the run gets its
    responses is a property of the run. Baking `@use_cassette` into a test
    welds those two together and the same test can then never be pointed at a
    real environment again.
    """
    OFF = 'off'
    RECORD = 'record'
    REPLAY = 'replay'


class OnExhausted:
    """
    What to do once every recording of a key has been played.

    ERROR is the default and the only safe one for CI. A silent miss means the
    suite either reaches the real system while claiming to replay, or serves
    the wrong response and passes -- the same disease as a 500 passing quietly,
    which is what the assertion layer exists to prevent.
    """
    ERROR = 'error'
    LAST = 'last'
    PASSTHROUGH = 'passthrough'


class CassetteMiss(Exception):
    """
    Nothing on the tape answers this request.

    Carries the nearest recorded key and how it differs, because nine misses
    out of ten are one ignore rule that was never configured.
    """

    def __init__(self, miss: Miss, cassette: str, age_days: float = None):
        self.miss = miss
        self.cassette = cassette
        self.age_days = age_days
        super().__init__(self.describe())

    def describe(self) -> str:
        _lines = ['磁带 {!r} 里没有匹配的记录'.format(self.cassette),
                  '  请求   {} {}'.format(self.miss.method, self.miss.url),
                  '  匹配键 {}'.format(self.miss.key)]
        if self.miss.exhausted:
            _lines.append('  这个键录过，但已经全部播完（play-once）')
        if self.miss.nearest_key:
            _lines.append('  最接近 {}'.format(self.miss.nearest_key))
            if self.miss.nearest_reason:
                _lines.append('         差异：{}'.format(self.miss.nearest_reason))
        _age = ''
        if self.age_days is not None:
            _age = '，录于 {:.0f} 天前'.format(self.age_days)
        _lines.append('  磁带共 {} 条{}'.format(self.miss.total, _age))
        _lines.append('  → 补录：ipandora run <selector> --record --cassette {}'
                      .format(self.cassette))
        return '\n'.join(_lines)


class Cassette:
    """
    A loaded tape, and the cursor over it.

    Play-once by key: the same (method, path, query, body) can appear more than
    once with different responses -- pagination, a status moving from pending to
    success -- and replaying them in recorded order is the only reading that
    preserves what happened.
    """

    def __init__(self, name: str, directory: str = None,
                 on_exhausted: str = OnExhausted.ERROR):
        self.store = CassetteStore(name, directory)
        self.name = name
        self.on_exhausted = on_exhausted
        self.manifest = self.store.load_manifest()
        self.rules = MatchRules.from_dict(self.manifest.match)
        self._records = {}  # type: Dict[str, List[Record]]
        self._cursor = {}  # type: Dict[str, int]
        self._order = []  # type: List[str]
        self._seq = 0
        self._lock = threading.RLock()
        self.misses = []  # type: List[Miss]
        self.played = 0

    # -- loading -----------------------------------------------------------

    def load(self) -> 'Cassette':
        for _record in self.store.read():
            # Keys are recomputed rather than trusted: the stored key was built
            # with whatever rules were in force at record time, and the manifest
            # may have gained an ignore rule since. Recomputing means editing
            # the rules fixes old tapes instead of requiring a re-record.
            _key = key_for(_record.method, _record.url, _record.request_body, self.rules)
            _record.key = _key
            self._records.setdefault(_key, []).append(_record)
            self._order.append(_key)
        return self

    @property
    def total(self) -> int:
        return sum(len(_v) for _v in self._records.values())

    @property
    def age_days(self) -> Optional[float]:
        return self.manifest.age_days()

    @property
    def unplayed(self) -> int:
        """
        Recordings never reached this run.

        Not a failure on its own -- a cassette can legitimately cover more than
        one test -- but a large number usually means the suite changed shape
        and the tape is due for a re-record.
        """
        return self.total - self.played

    # -- replay ------------------------------------------------------------

    def play(self, method: str, url: str, body=None) -> Optional[Record]:
        """
        The next recording for this request, or None when the caller should be
        allowed through (passthrough only). Raises CassetteMiss otherwise.
        """
        _key = key_for(method, url, body, self.rules)
        with self._lock:
            _bucket = self._records.get(_key) or []
            _at = self._cursor.get(_key, 0)

            if _at < len(_bucket):
                self._cursor[_key] = _at + 1
                self.played += 1
                return _bucket[_at]

            _miss = self._miss_for(_key, method, url, exhausted=bool(_bucket))
            self.misses.append(_miss)

        if _bucket and self.on_exhausted == OnExhausted.LAST:
            self.played += 1
            return _bucket[-1]
        if self.on_exhausted == OnExhausted.PASSTHROUGH:
            logger.warning('cassette %s: no record for %s %s, passing through',
                           self.name, method, url)
            return None
        raise CassetteMiss(_miss, self.name, self.age_days)

    def _miss_for(self, key: str, method: str, url: str, exhausted: bool) -> Miss:
        _nearest, _reason = nearest(key, list(self._records))
        return Miss(method=str(method).upper(), url=url, key=key,
                    nearest_key=_nearest or '', nearest_reason=_reason,
                    exhausted=exhausted, total=self.total,
                    keys=list(self._records)[:20])

    # -- record ------------------------------------------------------------

    def start_recording(self, recorded_from: str = '') -> 'Cassette':
        self.store.begin_recording()
        self.manifest = Manifest(name=self.name, recorded_from=recorded_from,
                                 match=self.rules.to_dict())
        return self

    def record(self, method: str, url: str, request_headers, request_body,
               status: int, reason: str, response_headers, response_body,
               ms: float) -> Record:
        with self._lock:
            self._seq += 1
            _seq = self._seq
        return self.store.append(Record(
            seq=_seq,
            key=key_for(method, url, request_body, self.rules),
            method=str(method).upper(), url=url,
            request_headers=dict(request_headers or {}), request_body=request_body,
            status=status, reason=reason or '',
            response_headers=dict(response_headers or {}), response_body=response_body,
            ms=round(ms, 1)))

    def finish_recording(self, version: str = '') -> str:
        self.manifest.count = self._seq
        self.manifest.blobs = self.store.blob_count()
        if version:
            self.manifest.ipandora = version
        return self.store.save_manifest(self.manifest)

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_cassette.py
@Time  : 2026-08-02
"""
import json

import pytest

from ipandora.core.cassette import Cassette, MatchRules, Manifest, OnExhausted, Record
from ipandora.core.cassette.cassette import CassetteMiss
from ipandora.core.cassette.matcher import explain, key_for, nearest
from ipandora.core.cassette.model import INLINE_BODY_CHARS
from ipandora.core.cassette.store import CassetteStore, list_cassettes
from ipandora.core.report.redact import MASK


@pytest.fixture
def store(tmp_path):
    return CassetteStore('tape', directory=str(tmp_path))


def exchange(url='https://x.test/v1/a', method='GET', status=200, body='{"ok":1}',
             request_body=None, headers=None):
    return Record(method=method, url=url, status=status, response_body=body,
                  request_body=request_body, request_headers=headers or {})


class TestTheFilesOnDisk:
    def test_round_trip(self, store):
        store.append(exchange())
        [read] = list(store.read())
        assert read.method == 'GET' and read.status == 200
        assert read.response_body == '{"ok":1}'

    def test_recording_appends_rather_than_rewrites(self, store):
        for i in range(3):
            store.append(exchange(url='https://x.test/v1/{}'.format(i)))
        assert len(list(store.read())) == 3
        # one line per exchange is the whole reason for jsonl
        assert open(store.exchanges_path, encoding='utf-8').read().count('\n') == 3

    def test_each_line_is_valid_json_on_its_own(self, store):
        store.append(exchange())
        store.append(exchange(url='https://x.test/v1/b'))
        for line in open(store.exchanges_path, encoding='utf-8'):
            json.loads(line)

    def test_a_large_body_moves_to_a_blob(self, store):
        big = json.dumps({'k': 'v' * INLINE_BODY_CHARS})
        record = store.append(exchange(body=big))
        assert record.response_body_ref.startswith('sha256-')
        assert record.response_body is None
        # and comes back transparently
        assert list(store.read())[0].response_body == big

    def test_identical_bodies_are_stored_once(self, store):
        """Real traffic repeats the same response constantly -- config
        endpoints, dictionaries, first pages. Content addressing is what keeps
        a cassette from being mostly duplicates."""
        big = json.dumps({'k': 'v' * INLINE_BODY_CHARS})
        for i in range(5):
            store.append(exchange(url='https://x.test/v1/{}'.format(i), body=big))
        assert store.blob_count() == 1

    def test_a_small_body_stays_inline(self, store):
        record = store.append(exchange(body='{"ok":1}'))
        assert record.response_body == '{"ok":1}' and not record.response_body_ref
        assert store.blob_count() == 0

    def test_a_malformed_line_costs_one_exchange_not_the_tape(self, store):
        store.append(exchange())
        with open(store.exchanges_path, 'a', encoding='utf-8') as fh:
            fh.write('this is not json\n')
        store.append(exchange(url='https://x.test/v1/b'))
        assert len(list(store.read())) == 2

    def test_a_name_cannot_escape_the_directory(self, tmp_path):
        for bad in ('../../etc', 'a/b', '.hidden', ''):
            with pytest.raises(ValueError):
                CassetteStore(bad, directory=str(tmp_path))

    def test_a_blob_ref_cannot_escape_either(self, store):
        with pytest.raises(ValueError):
            store.get_blob('../../../etc/passwd')

    def test_listing_reports_age(self, tmp_path):
        store = CassetteStore('tape', directory=str(tmp_path))
        store.append(exchange())
        store.save_manifest(Manifest(name='tape', count=1))
        [entry] = list_cassettes(str(tmp_path))
        assert entry['name'] == 'tape' and entry['age_days'] is not None


class TestRedactionHappensOnTheWayIn:
    """
    A cassette gets committed, copied, attached to a ticket and eventually
    imported from production traffic. By the time it touches disk it has to be
    safe to hand to anyone who can read the repository.
    """

    def test_a_credential_header_never_reaches_the_file(self, store):
        store.append(exchange(headers={'Authorization': 'Bearer sk-live-abcdef123456'}))
        raw = open(store.exchanges_path, encoding='utf-8').read()
        assert 'sk-live-abcdef123456' not in raw
        assert MASK in raw

    def test_a_credential_recognised_only_by_its_field_name_is_redacted(self, store):
        """
        The value here looks like nothing -- no pattern matches it. Only the
        field name says it is a secret, and a body is a string, so the
        name-based rule never saw it until bodies were redacted structurally.

        Deliberately not a value that also matches a shape pattern: that
        version of this test passed either way and proved nothing.
        """
        store.append(exchange(body=json.dumps({'password': 'correcthorsebattery'})))
        raw = open(store.exchanges_path, encoding='utf-8').read()
        assert 'correcthorsebattery' not in raw
        assert MASK in raw

    def test_a_credential_recognised_only_by_its_shape_is_redacted(self, store):
        # the other half: no field name to go on, just the value
        store.append(exchange(body=json.dumps({'note': 'sk-live-abcdef1234567890'})))
        assert 'sk-live-abcdef1234567890' not in open(
            store.exchanges_path, encoding='utf-8').read()

    def test_a_nested_credential_is_redacted(self, store):
        store.append(exchange(body=json.dumps({'d': {'items': [{'apiKey': 'zzz-plain'}]}})))
        assert 'zzz-plain' not in open(store.exchanges_path, encoding='utf-8').read()

    def test_a_body_with_no_secrets_is_stored_byte_for_byte(self, store):
        """Re-serialising every body would rewrite the whole archive -- other
        spacing, other key order, another hash -- for nothing."""
        body = '{"a": 1,   "b": [2, 3]}'
        store.append(exchange(body=body))
        assert list(store.read())[0].response_body == body

    def test_a_credential_in_a_large_body_never_reaches_a_blob(self, store):
        """Redaction has to run before the blob is written, or the secret sits
        on disk under a filename derived from it."""
        secret = '0x' + 'a1b2c3d4' * 8
        big = json.dumps({'pad': 'x' * INLINE_BODY_CHARS, 'key': secret})
        store.append(exchange(body=big))
        for name in __import__('os').listdir(store.blobs_path):
            assert secret not in open(
                __import__('os').path.join(store.blobs_path, name),
                encoding='utf-8').read()


class TestMatching:
    """
    Real requests are full of fields that change every call. Any of them left
    in the key makes every lookup miss, so the ignore lists are not a
    convenience -- without them the feature does not work.
    """

    def test_query_order_does_not_matter(self):
        assert (key_for('GET', 'https://x.test/a?b=2&a=1')
                == key_for('GET', 'https://x.test/a?a=1&b=2'))

    def test_noisy_query_params_are_ignored_by_default(self):
        assert (key_for('GET', 'https://x.test/a?_t=1699999999&id=7')
                == key_for('GET', 'https://x.test/a?_t=1700000000&id=7'))

    def test_a_meaningful_query_param_still_counts(self):
        assert (key_for('GET', 'https://x.test/a?id=7')
                != key_for('GET', 'https://x.test/a?id=8'))

    def test_body_key_order_does_not_matter(self):
        assert (key_for('POST', 'https://x.test/a', '{"a":1,"b":2}')
                == key_for('POST', 'https://x.test/a', '{"b":2,"a":1}'))

    def test_body_whitespace_does_not_matter(self):
        assert (key_for('POST', 'https://x.test/a', '{"a": 1}')
                == key_for('POST', 'https://x.test/a', '{"a":1}'))

    def test_noisy_body_fields_are_ignored(self):
        a = key_for('POST', 'https://x.test/a', '{"amount":5,"requestId":"r1"}')
        b = key_for('POST', 'https://x.test/a', '{"amount":5,"requestId":"r2"}')
        assert a == b

    def test_a_noisy_field_nested_deep_is_ignored_too(self):
        a = key_for('POST', 'https://x.test/a', '{"d":{"amount":5,"nonce":"n1"}}')
        b = key_for('POST', 'https://x.test/a', '{"d":{"amount":5,"nonce":"n2"}}')
        assert a == b

    def test_a_meaningful_body_field_still_counts(self):
        assert (key_for('POST', 'https://x.test/a', '{"amount":5}')
                != key_for('POST', 'https://x.test/a', '{"amount":6}'))

    def test_non_json_body_is_hashed_as_is(self):
        assert (key_for('POST', 'https://x.test/a', 'raw-payload')
                != key_for('POST', 'https://x.test/a', 'other-payload'))

    def test_host_is_ignored_by_default(self):
        """The same cassette should replay against staging and against a local
        port."""
        assert (key_for('GET', 'https://a.test/v1/x')
                == key_for('GET', 'https://b.test/v1/x'))

    def test_host_can_be_made_to_count(self):
        rules = MatchRules(match_host=True)
        assert (key_for('GET', 'https://a.test/v1/x', rules=rules)
                != key_for('GET', 'https://b.test/v1/x', rules=rules))

    def test_the_key_is_readable_not_a_bare_hash(self):
        # a miss message has to show which part differs
        assert key_for('GET', 'https://x.test/v1/order?id=7').startswith(
            'GET|/v1/order|q:id=7')


class TestMissExplanations:
    """Nine misses out of ten are one ignore rule nobody configured, so naming
    the differing part is what turns a dead end into a fix."""

    def test_a_differing_query_param_is_named(self):
        a = key_for('GET', 'https://x.test/v1/a?verbose=1')
        b = key_for('GET', 'https://x.test/v1/a')
        assert 'verbose' in explain(a, b)

    def test_a_differing_path_says_so(self):
        a = key_for('GET', 'https://x.test/v1/a')
        b = key_for('GET', 'https://x.test/v1/b')
        assert '路径' in explain(a, b)

    def test_a_differing_body_says_so(self):
        a = key_for('POST', 'https://x.test/a', '{"amount":5}')
        b = key_for('POST', 'https://x.test/a', '{"amount":6}')
        assert '请求体' in explain(a, b)

    def test_nearest_prefers_the_key_sharing_more_segments(self):
        target = key_for('GET', 'https://x.test/v1/order?id=7')
        candidates = [key_for('GET', 'https://x.test/v1/order'),
                      key_for('POST', 'https://x.test/v9/other')]
        found, _ = nearest(target, candidates)
        assert found == candidates[0]

    def test_nearest_on_an_empty_tape_is_none(self):
        assert nearest('GET|/a|q:-|b:-', []) == (None, '')


class TestPlaySemantics:
    def _tape(self, tmp_path, *records, **kwargs):
        store = CassetteStore('t', directory=str(tmp_path))
        for record in records:
            store.append(record)
        store.save_manifest(Manifest(name='t'))
        return Cassette('t', directory=str(tmp_path), **kwargs).load()

    def test_a_recorded_request_plays_back(self, tmp_path):
        tape = self._tape(tmp_path, exchange())
        assert tape.play('GET', 'https://x.test/v1/a').status == 200

    def test_the_same_key_plays_in_recorded_order(self, tmp_path):
        """Pagination and status machines record the same request twice with
        different answers; recorded order is the only reading that keeps what
        happened."""
        tape = self._tape(tmp_path,
                          exchange(body='{"page":1}'), exchange(body='{"page":2}'))
        assert tape.play('GET', 'https://x.test/v1/a').response_body == '{"page":1}'
        assert tape.play('GET', 'https://x.test/v1/a').response_body == '{"page":2}'

    def test_running_out_raises_by_default(self, tmp_path):
        tape = self._tape(tmp_path, exchange())
        tape.play('GET', 'https://x.test/v1/a')
        with pytest.raises(CassetteMiss) as exc:
            tape.play('GET', 'https://x.test/v1/a')
        assert exc.value.miss.exhausted is True

    def test_last_replays_the_final_recording(self, tmp_path):
        tape = self._tape(tmp_path, exchange(body='{"n":1}'), exchange(body='{"n":2}'),
                          on_exhausted=OnExhausted.LAST)
        for _ in range(3):
            tape.play('GET', 'https://x.test/v1/a')
        assert tape.play('GET', 'https://x.test/v1/a').response_body == '{"n":2}'

    def test_passthrough_returns_none_so_the_caller_goes_to_the_network(self, tmp_path):
        tape = self._tape(tmp_path, exchange(), on_exhausted=OnExhausted.PASSTHROUGH)
        assert tape.play('GET', 'https://x.test/nope') is None

    def test_an_unknown_request_raises_with_the_nearest_key(self, tmp_path):
        tape = self._tape(tmp_path, exchange())
        with pytest.raises(CassetteMiss) as exc:
            tape.play('GET', 'https://x.test/v1/a?verbose=1')
        text = str(exc.value)
        assert '最接近' in text and 'verbose' in text
        assert '--record' in text, 'the message has to say how to fix it'

    def test_misses_are_collected_not_only_raised(self, tmp_path):
        tape = self._tape(tmp_path, exchange(), on_exhausted=OnExhausted.PASSTHROUGH)
        tape.play('GET', 'https://x.test/nope')
        assert len(tape.misses) == 1

    def test_unplayed_recordings_are_countable(self, tmp_path):
        tape = self._tape(tmp_path, exchange(), exchange(url='https://x.test/v1/b'))
        tape.play('GET', 'https://x.test/v1/a')
        assert tape.played == 1 and tape.unplayed == 1

    def test_keys_are_recomputed_from_current_rules(self, tmp_path):
        """
        Editing the manifest fixes old tapes instead of forcing a re-record.

        The stored key was built with whatever rules existed at record time; a
        rule added since has to apply to what is already on disk, or every
        ignore-list fix would mean recording everything again.
        """
        store = CassetteStore('t', directory=str(tmp_path))
        store.append(exchange(url='https://x.test/v1/a?trace=abc'))
        store.save_manifest(Manifest(name='t', match={'ignore_query': ['trace']}))
        tape = Cassette('t', directory=str(tmp_path)).load()
        # a different trace value now matches the recorded one
        assert tape.play('GET', 'https://x.test/v1/a?trace=zzz').status == 200


class TestStaleness:
    def test_age_is_reported(self):
        assert Manifest(recorded_at='2026-08-01T00:00:00Z').age_days() > 0

    def test_an_unparseable_date_is_unknown_not_zero(self):
        # zero would read as "recorded just now", which is the wrong lie
        assert Manifest(recorded_at='whenever').age_days() is None

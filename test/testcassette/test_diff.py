# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_diff.py
@Time  : 2026-08-03
"""
import json

import pytest

from ipandora.core.cassette.diff import (Change, DiffRules, Kind, MAX_DIFFERENCES,
                                         compare)
from ipandora.core.cassette.model import Record


def recorded(body='{"a": 1}', status=200, headers=None):
    return Record(method='GET', url='https://x.test/v1/a', status=status,
                  response_body=body, response_headers=headers or {})


def diff(baseline, actual, rules=None, status=200, base_status=200,
         headers=None, base_headers=None):
    _base = baseline if isinstance(baseline, str) else json.dumps(baseline)
    _live = actual if isinstance(actual, str) else json.dumps(actual)
    return compare(recorded(_base, base_status, base_headers), status,
                   headers or {}, _live, rules=rules)


def paths(result):
    return [d.path for d in result.real]


class TestAgreement:
    def test_identical_bodies_agree(self):
        assert diff({'a': 1}, {'a': 1}).identical

    def test_key_order_does_not_matter(self):
        assert diff('{"a":1,"b":2}', '{"b":2,"a":1}').identical

    def test_whitespace_does_not_matter(self):
        assert diff('{"a": 1}', '{"a":1}').identical

    def test_identical_non_json_bodies_agree(self):
        assert diff('v1.3.0\nv1.7.0', 'v1.3.0\nv1.7.0').identical


class TestWhatChanged:
    def test_a_changed_value_is_reported_with_both_sides(self):
        [difference] = diff({'status': 'SUCCESS'}, {'status': 'PENDING'}).real
        assert difference.path == 'status'
        assert difference.baseline == 'SUCCESS' and difference.actual == 'PENDING'
        assert difference.change == Change.CHANGED

    def test_a_removed_field_is_not_the_same_as_a_changed_one(self):
        """A field that vanished is a contract change; showing it as
        `'0.0002' -> None` reads like a value problem and sends the reader to
        the wrong place."""
        [difference] = diff({'fee': '0.0002'}, {}).real
        assert difference.change == Change.REMOVED and difference.path == 'fee'

    def test_an_added_field_is_reported(self):
        [difference] = diff({}, {'riskLevel': 'LOW'}).real
        assert difference.change == Change.ADDED

    def test_nested_paths_are_full_paths(self):
        result = diff({'data': {'order': {'status': 'A'}}},
                      {'data': {'order': {'status': 'B'}}})
        assert paths(result) == ['data.order.status']

    def test_list_elements_are_indexed(self):
        result = diff({'l': [{'n': 1}, {'n': 2}]}, {'l': [{'n': 1}, {'n': 9}]})
        assert paths(result) == ['l[1].n']

    def test_a_length_change_is_reported_once_not_per_element(self):
        result = diff({'l': [1, 2, 3]}, {'l': [1]})
        assert paths(result) == ['l']

    def test_status_is_reported_separately_from_the_body(self):
        """When a 200 becomes a 500 the body differences are noise about an
        error page; the status has to be findable among them."""
        result = diff({'a': 1}, {'error': 'boom'}, status=500)
        statuses = [d for d in result.real if d.kind == Kind.STATUS]
        assert len(statuses) == 1
        assert statuses[0].baseline == 200 and statuses[0].actual == 500

    def test_a_body_that_stopped_being_json_says_so(self):
        result = diff({'a': 1}, '<html>502 Bad Gateway</html>')
        assert any(d.kind == Kind.SHAPE for d in result.real)

    def test_the_difference_list_is_bounded(self):
        big_a = {'k{}'.format(i): i for i in range(500)}
        big_b = {'k{}'.format(i): i + 1 for i in range(500)}
        result = diff(big_a, big_b)
        assert len(result.differences) <= MAX_DIFFERENCES + 1
        assert result.truncated


class TestNoiseCanBeSilenced:
    """
    Without this the feature is unusable: real responses differ on every call
    for reasons nobody cares about, and a diff that is mostly noise is read the
    same way as no diff at all.
    """

    def test_an_ignored_path_is_not_a_difference(self):
        rules = DiffRules(ignore_paths=('data.serverTime',))
        assert diff({'data': {'serverTime': 1}}, {'data': {'serverTime': 2}},
                    rules).identical

    def test_a_wildcard_index_covers_every_element(self):
        rules = DiffRules(ignore_paths=('l[*].updatedAt',))
        result = diff({'l': [{'updatedAt': 1}, {'updatedAt': 2}]},
                      {'l': [{'updatedAt': 9}, {'updatedAt': 8}]}, rules)
        assert result.identical

    def test_a_whole_list_element_can_be_ignored(self):
        """
        The list branch recurses without re-checking, so element-level
        ignores are caught by the guard at the top of the walk rather than by
        the one on dict children. Covered separately because a mutation that
        removes that guard passes every other ignore test.
        """
        rules = DiffRules(ignore_paths=('l[*]',))
        assert diff({'l': [{'a': 1}, {'a': 2}]}, {'l': [{'a': 9}, {'a': 8}]},
                    rules).identical

    def test_a_single_indexed_element_can_be_ignored(self):
        rules = DiffRules(ignore_paths=('l[0]',))
        result = diff({'l': [{'a': 1}, {'a': 2}]}, {'l': [{'a': 9}, {'a': 8}]}, rules)
        assert paths(result) == ['l[1].a']

    def test_ignoring_a_subtree_ignores_what_is_under_it(self):
        rules = DiffRules(ignore_paths=('meta',))
        assert diff({'meta': {'a': 1, 'b': 2}}, {'meta': {'a': 9}}, rules).identical

    def test_ignoring_does_not_silence_its_siblings(self):
        rules = DiffRules(ignore_paths=('data.serverTime',))
        result = diff({'data': {'serverTime': 1, 'status': 'A'}},
                      {'data': {'serverTime': 2, 'status': 'B'}}, rules)
        assert paths(result) == ['data.status']

    def test_a_tolerated_difference_is_recorded_but_does_not_count(self):
        """Not the same as ignoring it. The reader still sees that the value
        moved -- they just are not asked to act on it."""
        rules = DiffRules(tolerate=({'path': 'amount', 'kind': 'numeric',
                                     'epsilon': 0.001},))
        result = diff({'amount': '0.5'}, {'amount': '0.5000001'}, rules)
        assert result.identical
        assert len(result.tolerated) == 1
        assert '容差' in result.tolerated[0].reason

    def test_a_difference_beyond_the_tolerance_still_counts(self):
        rules = DiffRules(tolerate=({'path': 'amount', 'kind': 'numeric',
                                     'epsilon': 0.001},))
        assert not diff({'amount': '0.5'}, {'amount': '0.9'}, rules).identical

    def test_a_non_numeric_value_is_never_tolerated_numerically(self):
        rules = DiffRules(tolerate=({'path': 'status', 'kind': 'numeric',
                                     'epsilon': 999},))
        assert not diff({'status': 'A'}, {'status': 'B'}, rules).identical

    def test_no_tolerance_rule_at_all_is_not_a_crash(self):
        # `_within_tolerance` used to be handed None and call .get on it, which
        # raised -- and the raise was swallowed upstream, so a broken
        # comparator looked exactly like agreement
        assert not diff({'a': 1}, {'a': 2}, DiffRules()).identical

    def test_an_unordered_list_compares_as_a_bag(self):
        rules = DiffRules(unordered_paths=('l',))
        assert diff({'l': [{'id': 1}, {'id': 2}]},
                    {'l': [{'id': 2}, {'id': 1}]}, rules).identical

    def test_an_unordered_list_still_notices_different_contents(self):
        rules = DiffRules(unordered_paths=('l',))
        assert not diff({'l': [1, 2]}, {'l': [1, 3]}, rules).identical


class TestHeaders:
    def test_headers_are_not_compared_by_default(self):
        """A diff that is 90% header churn gets skipped wholesale, taking the
        body differences with it."""
        assert diff({'a': 1}, {'a': 1}, headers={'X-Whatever': 'b'},
                    base_headers={'X-Whatever': 'a'}).identical

    def test_headers_are_compared_when_asked(self):
        rules = DiffRules(compare_headers=True)
        result = diff({'a': 1}, {'a': 1}, rules, headers={'X-Mode': 'b'},
                      base_headers={'X-Mode': 'a'})
        assert [d.kind for d in result.real] == [Kind.HEADER]

    def test_headers_that_always_change_stay_quiet(self):
        rules = DiffRules(compare_headers=True)
        assert diff({'a': 1}, {'a': 1}, rules, headers={'Date': 'later'},
                    base_headers={'Date': 'earlier'}).identical


class TestTheSummary:
    def test_agreement_says_so(self):
        assert '与基线一致' in diff({'a': 1}, {'a': 1}).summary()

    def test_tolerated_differences_are_counted_in_the_summary(self):
        rules = DiffRules(tolerate=({'path': 'a', 'kind': 'numeric',
                                     'epsilon': 1},))
        assert '已容忍' in diff({'a': 1}, {'a': 2}, rules).summary()

    def test_the_summary_names_the_first_few_and_counts_the_rest(self):
        base = {'k{}'.format(i): i for i in range(20)}
        live = {'k{}'.format(i): i + 1 for i in range(20)}
        summary = diff(base, live).summary()
        assert '20 处差异' in summary and '另有' in summary

    def test_the_summary_is_bounded(self):
        base = {'k{}'.format(i): 'v' * 500 for i in range(20)}
        live = {'k{}'.format(i): 'w' * 500 for i in range(20)}
        assert len(diff(base, live).summary()) < 1200

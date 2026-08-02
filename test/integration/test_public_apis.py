# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_public_apis.py
@Time  : 2026-08-02

The framework driven against real third-party APIs.

Everything else in test/ is hermetic, which is what makes it fit to gate a
merge -- but it also means every response shape is one we chose. These cases
exist because a mock cannot tell you that the transport policy, the response
parser and the assertion layer survive contact with services nobody wrote for
us. Two real defects came out of exactly that: a read timeout reporting itself
as a connection failure (only reproducible through the real retry adapter), and
the dashed `dist-tags` key that the old namedtuple parser could not represent.

Public package registries are used deliberately: no key, no quota, no account,
stable schemas, and their availability is not our concern to fix.

Opt in, since these need the network and can fail for reasons that are not ours:

    IPANDORA_INTEGRATION=1 pytest test/integration -v
"""
import os

import pytest

from ipandora.core import api
from ipandora.core.assertion import (assert_all, json_equals, json_has, json_matches,
                                     json_value, require, schema_conforms, status_is,
                                     status_ok)
from ipandora.core.base.data.markdata import MarkData
from ipandora.core.plugin.interface.endpointsinterface import EndPointsInterface
from ipandora.core.plugin.pluginmanager import PluginManager
from ipandora.core.triage import classify
from ipandora.utils.error import HttpTimeoutError, TransportError

pytestmark = pytest.mark.skipif(
    os.environ.get('IPANDORA_INTEGRATION') != '1',
    reason='needs network; set IPANDORA_INTEGRATION=1 to run')


class _NoEndpoints(EndPointsInterface):
    def endpoints(self, mark: MarkData) -> dict:
        return {}


PluginManager.endpoints(reg=_NoEndpoints())


class Registries:
    @api.http.get('https://pypi.org/pypi/requests/json')
    def pypi_package(self):
        return {}

    @api.http.get('https://registry.npmjs.org/express')
    def npm_package(self):
        return {}

    @api.http.get('https://proxy.golang.org/github.com/gorilla/mux/@v/list')
    def go_versions(self):
        return {}

    @api.http.get('https://pypi.org/pypi/ipandora-no-such-package-42/json')
    def pypi_missing(self):
        return {}

    @api.http.get('https://pypi.org/pypi/requests/json')
    def pypi_impatient(self):
        # short enough that the response cannot possibly arrive in time
        return dict(timeout=(5, 0.001))


class TestNestedJson:
    """PyPI returns a large, deeply nested document -- the shape the parser has
    to handle without the caller flattening anything by hand."""

    def test_reads_by_attribute_and_by_key(self):
        r = Registries().pypi_package()
        assert r.data.info.name == 'requests'
        assert r.data['info']['version'] == r.data.info.version
        assert isinstance(r.data.info.requires_dist, (list, type(None)))

    def test_assertions_hold_against_the_live_document(self):
        r = Registries().pypi_package()
        assert_all(
            status_ok(r),
            json_equals(r, 'info.name', 'requests'),
            json_has(r, 'info.version'),
            json_has(r, 'releases'),
            json_matches(r, 'info.summary', {'$contains': 'HTTP'}),
            schema_conforms(r, {
                'type': 'object',
                'required': ['info', 'releases'],
                'properties': {
                    'info': {'type': 'object', 'required': ['name', 'version']}}}),
        )


class TestKeysPythonCannotName:
    """
    npm's document has `dist-tags` and `_id`.

    A dash is not a valid identifier, so the old namedtuple-based parser could
    not carry this key at all. Real APIs do not restrict themselves to names
    that happen to be valid Python.
    """

    def test_dashed_and_underscored_keys_survive(self):
        r = Registries().npm_package()
        assert 'latest' in r.data['dist-tags']
        assert r.data['_id'] == 'express'
        assert_all(
            status_ok(r),
            json_equals(r, 'name', 'express'),
            json_has(r, 'dist-tags.latest'),
            json_has(r, '_id'),
        )


class TestNonJsonBody:
    """The Go module proxy answers text/plain. A JSON assertion against it must
    report a readable reason, not raise out of the assertion layer."""

    def test_plain_text_is_returned_as_text(self):
        r = Registries().go_versions()
        assert_all(status_ok(r))
        assert isinstance(r.data, str)
        assert 'v1.' in r.data

    def test_json_assertion_fails_instead_of_exploding(self):
        r = Registries().go_versions()
        check = json_has(r, 'anything')
        assert check.ok is False
        assert check.expr  # the reason has to say something usable


class TestStatusIsJudged:
    """The defect that motivated the assertion layer: an unexpected status used
    to pass silently, because nothing ever looked at it."""

    def test_404_fails(self):
        r = Registries().pypi_missing()
        assert r.response.status_code == 404
        assert status_ok(r).ok is False
        with pytest.raises(AssertionError):
            assert_all(status_ok(r))


class TestFailureMessagesOnUnfamiliarData:
    """
    A passing assertion tells you almost nothing about the assertion layer. What
    matters is what a *failure* says, on data nobody wrote a fixture for.
    """

    def test_one_run_reports_every_failure_not_just_the_first(self):
        r = Registries().pypi_package()
        with pytest.raises(AssertionError) as exc:
            assert_all(
                status_ok(r),                                    # passes
                status_is(r, 201),                               # fails
                json_equals(r, 'info.name', 'flask'),            # fails
                json_has(r, 'info.no_such_field'),               # fails
                json_matches(r, 'info.version', {'$startWith': '0.'}),  # fails
            )
        message = str(exc.value)
        assert '4/5 checks failed' in message
        # the actual values have to be in there, or the reader has to re-run
        assert "'requests'" in message and '201' in message
        # and what passed, so a reader knows the run was not simply broken
        assert 'passed:' in message

    def test_a_failure_on_a_large_field_stays_readable(self):
        # PyPI's `releases` is ~195KB. Before the cap this exact assertion
        # produced a 195,529-character message -- printed, stored in the report,
        # and sent to the triage model.
        r = Registries().pypi_package()
        with pytest.raises(AssertionError) as exc:
            assert_all(json_equals(r, 'releases', 'nope'))
        message = str(exc.value)
        assert len(message) < 1000, '{} chars'.format(len(message))
        assert 'truncated' in message

    def test_a_broken_path_says_where_the_walk_stopped(self):
        r = Registries().pypi_package()
        _, reason = json_value(r, 'info.nope.deeper')
        assert "at 'info'" in reason
        assert 'no key' in reason
        assert 'present:' in reason  # the keys that do exist

    def test_versions_keyed_by_dotted_string_are_reachable(self):
        # PyPI keys releases by version. Without a quoted path form this field
        # cannot be addressed at all.
        r = Registries().pypi_package()
        assert_all(json_has(r, "releases['2.32.0'][0].filename"),
                   json_matches(r, "releases['2.32.0'].0.packagetype",
                                {'$in': ['sdist', 'bdist_wheel']}))

    def test_bare_index_works_the_way_people_write_it(self):
        r = Registries().pypi_package()
        assert_all(json_has(r, 'urls.0.url'), json_has(r, 'urls[0].url'))

    def test_assertions_on_a_non_json_body_fail_rather_than_raise(self):
        go = Registries().go_versions()
        for check in (json_has(go, 'x'), json_equals(go, 'x', 1),
                      json_matches(go, 'x', {'$gt': 1}),
                      schema_conforms(go, {'type': 'object'})):
            assert check.ok is False
            assert 'not JSON' in check.expr

    def test_schema_failure_points_at_the_field(self):
        r = Registries().pypi_package()
        check = schema_conforms(r, {
            'type': 'object',
            'properties': {'info': {'type': 'object',
                                    'properties': {'version': {'type': 'integer'}}}}})
        assert check.ok is False
        assert 'info/version' in check.expr


class TestRequireIsNotAFailure:
    """
    "the precondition did not hold" and "the code is wrong" must not look the
    same on a dashboard. require() skips; assert_all() fails.
    """

    def test_an_unmet_precondition_skips(self):
        r = Registries().pypi_package()
        # Skipped derives from BaseException, so it has to be caught explicitly
        # rather than through pytest.raises -- which is the point: an unmet
        # precondition does not travel the same path as a failed assertion.
        try:
            require(json_matches(r, 'info.version', {'$startWith': '99.'}))
        except BaseException as exc:  # noqa: BLE001
            assert type(exc).__name__ == 'Skipped', type(exc).__name__
            assert not isinstance(exc, AssertionError)
            assert 'Precondition not met' in str(exc)
        else:
            pytest.fail('an unmet precondition did not skip')

    def test_a_met_precondition_returns_the_checks(self):
        r = Registries().pypi_package()
        checks = require(status_ok(r), json_has(r, 'info.version'))
        assert len(checks) == 2 and all(c.ok for c in checks)


class TestTransportFailuresAreDistinguishable:
    def test_read_timeout_is_a_timeout_not_a_connection_error(self):
        # Regression against a live server. The mounted retry adapter makes
        # urllib3 wrap this as MaxRetryError(reason=ReadTimeoutError), which
        # requests then reports as ConnectionError -- the framework has to see
        # through that. test/testtransport covers it without the network.
        with pytest.raises(HttpTimeoutError):
            Registries().pypi_impatient()

    def test_a_transport_failure_is_not_blamed_on_the_service(self):
        try:
            Registries().pypi_impatient()
        except TransportError as exc:
            finding = classify('integration::timeout', 'failed',
                               '{}: {}'.format(type(exc).__name__, exc))
            # nothing was measured, so this says nothing about the API's health
            assert finding.blames_system_under_test is False
        else:
            pytest.skip('the response arrived within 1ms; nothing to classify')

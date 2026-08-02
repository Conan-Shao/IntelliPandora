# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : test_response_parsing.py
@Time  : 2026-08-01
"""
import json

import pytest

from ipandora.core.protocol.http.model.handler.responsehandler import (JsonObject,
                                                                       ResponseHandler,
                                                                       as_item_list,
                                                                       as_mapping,
                                                                       json_to_obj)


class _Raw:
    status_code = 200
    headers = {}

    def __init__(self, content):
        if isinstance(content, bytes):
            self.content = content
        elif isinstance(content, str):
            self.content = content.encode('utf-8')
        else:
            self.content = json.dumps(content).encode('utf-8')

    @property
    def text(self):
        return self.content.decode('utf-8', errors='replace')


def handler(content):
    raw = _Raw(content)
    return ResponseHandler().inject(response=raw, content=raw.content)


class TestPayloadShapes:
    """
    fetch_all() used to iterate whatever _valid_data() returned. A single
    object was torn into its field values, and null or a scalar raised
    TypeError.
    """

    def test_single_object_stays_one_item(self):
        # previously [1, 'alice'] -- the field values, not the record
        assert handler({'code': 0, 'data': {'id': 1, 'name': 'alice'}}).fetch_all() == [
            {'id': 1, 'name': 'alice'}]

    def test_list_is_already_items(self):
        assert handler({'code': 0, 'data': [{'id': 1}, {'id': 2}]}).fetch_all() == [
            {'id': 1}, {'id': 2}]

    def test_null_is_no_items(self):
        # previously TypeError: 'NoneType' object is not iterable
        assert handler({'code': 0, 'data': None}).fetch_all() == []

    def test_scalar_is_one_item(self):
        # previously TypeError: 'int' object is not iterable
        assert handler({'code': 0, 'data': 5}).fetch_all() == [5]

    def test_unwrapped_object(self):
        # previously ['10.0.0.1']
        assert handler({'origin': '10.0.0.1'}).fetch_all() == [{'origin': '10.0.0.1'}]

    def test_string_is_not_shredded_into_characters(self):
        assert handler({'data': 'hello'}).fetch_all() == ['hello']

    def test_data_wrapper_is_still_unwrapped(self):
        assert handler({'code': 0, 'data': {'id': 1}}).data == {'id': 1}

    def test_result_wrapper_is_still_unwrapped(self):
        assert handler({'code': 0, 'result': {'id': 1}}).data == {'id': 1}


class TestBackwardCompatibleAttributeAccess:
    """`response.data.origin` is the documented API; it must keep working."""

    def test_attribute_access(self):
        assert handler({'origin': '10.0.0.1'}).data.origin == '10.0.0.1'

    def test_nested_attribute_access(self):
        assert handler({'data': {'user': {'name': 'alice'}}}).data.user.name == 'alice'

    def test_attribute_access_inside_a_list(self):
        assert handler({'data': [{'id': 1}, {'id': 2}]}).fetch_one().id == 1

    def test_missing_field_says_what_is_available(self):
        with pytest.raises(AttributeError) as exc:
            _ = handler({'origin': 'x'}).data.nope
        assert 'nope' in str(exc.value) and 'origin' in str(exc.value)


class TestNoSilentDegradation:
    """
    json_to_obj used to build a namedtuple and fall back to a plain dict when
    a key was a Python keyword or held a dash -- so the parsed type depended on
    the payload's key names, and _asdict() blew up on exactly those responses.
    """

    def test_dashed_key_is_reachable(self):
        assert handler({'data': {'x-req-id': 'abc'}}).data['x-req-id'] == 'abc'

    def test_python_keyword_key_is_reachable(self):
        assert handler({'data': {'class': 'premium'}}).data['class'] == 'premium'

    def test_type_is_the_same_whatever_the_keys_look_like(self):
        plain = handler({'data': {'id': 1}}).data
        awkward = handler({'data': {'x-req-id': 1, 'class': 2}}).data
        assert type(plain) is type(awkward) is JsonObject

    def test_filter_works_on_awkward_keys(self):
        # this raised AttributeError before: degraded dicts have no _asdict
        result = handler({'data': [{'x-req-id': 'a'}, {'x-req-id': 'b'}]})
        assert result.filter(**{'x-req-id': 'b'}).fetch_one() == {'x-req-id': 'b'}


class TestNonJsonBodies:
    def test_html_comes_back_as_text(self):
        assert handler('<html>error</html>').data == '<html>error</html>'

    def test_binary_comes_back_as_bytes(self):
        payload = b'\x89PNG\r\n\x1a\n\xff\xfe'
        assert handler(payload).data == payload

    def test_empty_body(self):
        assert handler('').data == ''


class TestFilter:
    def test_filter_selects(self):
        assert handler({'data': [{'i': 1}, {'i': 2}]}).filter(i=2).fetch_one() == {'i': 2}

    def test_filter_with_operator(self):
        assert handler({'data': [{'i': 1}, {'i': 5}]}).filter(
            i={'$gt': 3}).fetch_all() == [{'i': 5}]

    def test_filter_skips_items_without_fields(self):
        # a list of scalars has nothing to match on; previously AttributeError
        assert handler({'data': [1, 2, 3]}).filter(i=2).fetch_all() == []

    def test_filter_on_a_single_object(self):
        assert handler({'data': {'i': 2}}).filter(i=2).fetch_all() == [{'i': 2}]


class TestFetchSemantics:
    def test_fetch_one_on_empty_is_none(self):
        # [] read as "here is your item, it is a list", which it was not
        assert handler({'data': None}).fetch_one() is None

    def test_fetch_one_returns_first(self):
        assert handler({'data': [{'i': 1}, {'i': 2}]}).fetch_one() == {'i': 1}

    def test_fetch_last_returns_last(self):
        assert handler({'data': [{'i': 1}, {'i': 2}]}).fetch_last() == {'i': 2}

    def test_len_has_no_side_effects(self):
        result = handler({'data': [{'i': 1}, {'i': 2}]})
        assert (len(result), len(result), len(result)) == (2, 2, 2)

    def test_len_does_not_clear_an_applied_filter(self):
        result = handler({'data': [{'i': 1}, {'i': 2}]}).filter(i=2)
        assert len(result) == 1
        assert result.fetch_all() == [{'i': 2}]

    def test_iteration_yields_every_item_once(self):
        assert list(handler({'data': [{'i': 1}, {'i': 2}, {'i': 3}]})) == [
            {'i': 1}, {'i': 2}, {'i': 3}]

    def test_fetch_on_empty_is_none(self):
        assert handler({'data': None}).fetch(0) is None


class TestHelpers:
    @pytest.mark.parametrize('value,expected', [
        (None, []),
        ([1, 2], [1, 2]),
        ({'a': 1}, [{'a': 1}]),
        (5, [5]),
        ('text', ['text']),
        (b'bytes', [b'bytes']),
    ])
    def test_as_item_list(self, value, expected):
        assert as_item_list(value) == expected

    def test_as_mapping_accepts_dicts_and_namedtuples(self):
        from collections import namedtuple
        assert as_mapping({'a': 1}) == {'a': 1}
        assert as_mapping(JsonObject(a=1)) == {'a': 1}
        assert as_mapping(namedtuple('T', 'a')(a=1)) == {'a': 1}

    def test_as_mapping_rejects_fieldless_values(self):
        assert as_mapping(5) is None
        assert as_mapping('text') is None

    def test_json_to_obj_passes_through_parsed_data(self):
        assert json_to_obj({'already': 'parsed'}) == {'already': 'parsed'}

    def test_jsonobject_is_a_dict(self):
        obj = json_to_obj('{"a": 1}')
        assert isinstance(obj, dict) and obj['a'] == 1 and obj.a == 1

    def test_jsonobject_asdict_for_namedtuple_compatibility(self):
        assert JsonObject(a=1)._asdict() == {'a': 1}

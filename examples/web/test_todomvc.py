# -*- coding: utf-8 -*-
"""
Web example against a public site: Playwright's own TodoMVC demo.

Plain Playwright and pytest-playwright -- `page`, `expect`, nothing from this
framework is imported. Run it through the framework and every expect() is a
judgement in the inventory, a failure carries its screenshot and trace, and a
selector that finds nothing is triaged as stale or missing:

    pip install intellipandora[web]
    python -m playwright install chromium
    ipandora run examples/web                 # serial
    ipandora run examples/web --workers 4     # same answer, in parallel
"""
import re

import pytest
from playwright.sync_api import Page, expect

URL = 'https://demo.playwright.dev/todomvc/'


@pytest.fixture
def todo(page: Page) -> Page:
    page.goto(URL)
    return page


def add(page: Page, *items: str) -> None:
    _input = page.get_by_placeholder('What needs to be done?')
    for _item in items:
        _input.fill(_item)
        _input.press('Enter')


def test_a_new_item_is_listed(todo: Page):
    """新增一条待办，列表里能看到它"""
    add(todo, '买牛奶')
    expect(todo.get_by_test_id('todo-title')).to_have_text(['买牛奶'])
    expect(todo.get_by_test_id('todo-count')).to_have_text('1 item left')


def test_completing_an_item_updates_the_count(todo: Page):
    """勾选完成后，剩余数量减一"""
    add(todo, '买牛奶', '交电费')
    todo.get_by_test_id('todo-item').nth(0).get_by_role('checkbox').check()
    expect(todo.get_by_test_id('todo-item').nth(0)).to_have_class(re.compile('completed'))
    expect(todo.get_by_test_id('todo-count')).to_have_text('1 item left')


def test_the_active_filter_hides_completed_items(todo: Page):
    """"Active" 过滤只显示未完成的"""
    add(todo, '买牛奶', '交电费')
    todo.get_by_test_id('todo-item').nth(0).get_by_role('checkbox').check()
    todo.get_by_role('link', name='Active').click()
    expect(todo.get_by_test_id('todo-title')).to_have_text(['交电费'])
    expect(todo).to_have_url(re.compile(r'#/active$'))


def test_clear_completed_removes_them(todo: Page):
    """清除已完成"""
    add(todo, '买牛奶', '交电费', '订机票')
    todo.get_by_test_id('todo-item').nth(1).get_by_role('checkbox').check()
    todo.get_by_role('button', name='Clear completed').click()
    expect(todo.get_by_test_id('todo-title')).to_have_text(['买牛奶', '订机票'])

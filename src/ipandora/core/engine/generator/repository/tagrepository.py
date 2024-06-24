# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : tagrepository.py
@Time  : 2024-05-22
"""
from typing import List, Optional
from pymysql import Connection
from ipandora.core.engine.generator.model.data.testcase import Tag, TagUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TagRepository(BaseRepository):

    def get_tags(self) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE Status = 1"
        rows = self.execute_query(query)
        return self.filter_fields(rows, Tag)

    def get_tags_by_category_id(self, category_id: int) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE CategoryId = %s AND Status = 1"
        rows = self.execute_query(query % category_id)
        return self.filter_fields(rows, Tag)

    def get_tags_by_name(self, tag_name: str) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE TagName = '%s' AND Status = 1"
        rows = self.execute_query(query % tag_name)
        return self.filter_fields(rows, Tag)

    def get_tags_by_description(self, description: str) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE Description LIKE %s"
        rows = self.execute_query(query % f"%{description}%")
        return self.filter_fields(rows, Tag)

    def get_tag_by_id(self, tag_id: int) -> Optional[Tag]:
        query = "SELECT * FROM Tags WHERE TagID = %s AND Status = 1"
        rows = self.execute_query(query % tag_id)
        return self.filter_single(rows, Tag)

    def get_tag_id_by_name(self, tag_name: str) -> Optional[int]:
        query = "SELECT TagID FROM Tags WHERE UPPER(TagName) = UPPER(%s) AND Status = 1"
        rows = self.execute_query(query, (tag_name,))
        return rows[0]['TagID'] if rows else None

    def insert_tag(self, tag: Tag) -> int:
        query, values = self.generate_insert_query(tag, "Tags")
        return self.execute_insert(query, tuple(values))

    def update_tag(self, tag: TagUpdate) -> int:
        query, values = self.generate_update_query(tag, "Tags", "TagID")
        return self.execute_update(query, tuple(values))

    def insert_tag_as_transaction(self, tag: Tag,
                                  connection: Optional[Connection] = None,
                                  last_trans: bool = False):
        query, values = self.generate_insert_query(tag, "Tags")
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            _conn = connection if _conn is None else _conn
            self.commit_transaction(_conn)
        return _conn, result


if __name__ == '__main__':
    resp = TagRepository().get_tags()
    print(resp)
    print(len(resp))

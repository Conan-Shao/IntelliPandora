# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : tagrepository.py
@Time  : 2024-05-22
"""
from typing import List, Optional

from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import Tag, TagUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.error import DataError
from ipandora.utils.log import logger


class TagRepository(BaseRepository):

    def get_tags(self) -> List[Tag]:
        query = "SELECT * FROM Tags"
        rows = self.execute_query(query)
        return [Tag(**row) for row in rows] if rows else []

    def get_tags_by_category_id(self, category_id: int) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE CategoryId = %s"
        rows = self.execute_query(query % category_id)
        return [Tag(**row) for row in rows] if rows else []

    def get_tags_by_name(self, tag_name: str) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE TagName = '%s'"
        print(query % tag_name)
        rows = self.execute_query(query % tag_name)
        return [Tag(**row) for row in rows] if rows else []

    def get_tags_by_description(self, description: str) -> List[Tag]:
        query = "SELECT * FROM Tags WHERE Description LIKE %s"
        rows = self.execute_query(query % f"%{description}%")
        return [Tag(**row) for row in rows] if rows else []

    def get_tag_by_id(self, tag_id: int) -> Optional[Tag]:
        query = "SELECT * FROM Tags WHERE TagID = %s"
        rows = self.execute_query(query % tag_id)
        return Tag(**rows[0]) if rows else []

    def get_tag_id_by_name(self, tag_name: str) -> Optional[int]:
        query = "SELECT TagID FROM Tags WHERE TagName = %s"
        rows = self.execute_query(query, (tag_name,))
        return rows[0]['TagID'] if rows else None

    def insert_tag(self, tag: Tag) -> int:
        fields, values = AttrValueSplit(tag).get_fields_and_values()
        query = f"""
            INSERT INTO Tags ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        return self.execute_insert(query, tuple(values))

    def update_tag(self, tag: TagUpdate) -> int:
        fields, values = AttrValueSplit(tag, "TagID").get_fields_and_values()
        query = f"""
            UPDATE Tags
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE TagID = %s
        """
        values.append(tag.TagID)
        return self.execute_update(query, tuple(values))

    def insert_tag_as_transaction(self, tag: Tag, last_trans: bool = False):
        fields, values = AttrValueSplit(tag).get_fields_and_values()
        query = f"""
            INSERT INTO Tags ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        _conn, result = self.execute_with_transaction(query, tuple(values))
        if last_trans:
            self.commit_transaction(_conn)
        return _conn, result


if __name__ == '__main__':
    resp = TagRepository().get_tags()
    print(resp)
    print(len(resp))

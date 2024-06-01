# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : tagcategoryrepository.py
@Time  : 2024-05-23
"""
from typing import List, Optional

from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import TagCategory, TagCategoryUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class TagCategoryRepository(BaseRepository):

    def get_tag_categories(self) -> List[TagCategory]:
        query = "SELECT * FROM TagCategories"
        rows = self.execute_query(query)
        return [TagCategory(**row) for row in rows] if rows else []

    def get_tag_category_by_id(self, category_id: int) -> Optional[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE CategoryId = %s"
        rows = self.execute_query(query, (category_id,))
        return TagCategory(**rows[0]) if rows else None

    def get_tag_categories_by_name(self, category_name: str) -> List[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE CategoryName = %s"
        rows = self.execute_query(query, (category_name,))
        return [TagCategory(**row) for row in rows] if rows else []

    def get_tag_categories_by_description(self, description: str) -> List[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE Description LIKE %s"
        rows = self.execute_query(query, (f"%{description}%",))
        return [TagCategory(**row) for row in rows] if rows else []

    def insert_tag_category(self, tag_category: TagCategory) -> int:
        fields, values = AttrValueSplit(tag_category).get_fields_and_values()
        query = f"""
            INSERT INTO TagCategories ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        return self.execute_insert(query, tuple(values))

    def update_tag_category(self, tag_category_update: TagCategoryUpdate) -> int:
        fields, values = AttrValueSplit(tag_category_update, "CategoryId").get_fields_and_values()
        query = f"""
            UPDATE TagCategories
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE CategoryId = %s
        """
        values.append(tag_category_update.CategoryId)
        return self.execute_update(query, tuple(values))


if __name__ == '__main__':
    _result = TagCategoryRepository().get_tag_categories()
    print(_result)

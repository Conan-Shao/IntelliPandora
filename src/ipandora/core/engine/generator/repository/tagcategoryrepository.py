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
        query = "SELECT * FROM TagCategories WHERE Status = 1"
        rows = self.execute_query(query)
        return self.filter_fields(rows, TagCategory)

    def get_tag_category_by_id(self, category_id: int) -> Optional[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE CategoryId = %s AND Status = 1"
        rows = self.execute_query(query, (category_id,))
        return self.filter_single(rows, TagCategory)

    def get_tag_categories_by_name(self, category_name: str) -> List[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE CategoryName = %s AND Status = 1"
        rows = self.execute_query(query, (category_name,))
        return self.filter_fields(rows, TagCategory)

    def get_tag_categories_by_description(self, description: str) -> List[TagCategory]:
        query = "SELECT * FROM TagCategories WHERE Description LIKE %s"
        rows = self.execute_query(query, (f"%{description}%",))
        return self.filter_fields(rows, TagCategory)

    def insert_tag_category(self, tag_category: TagCategory) -> int:
        query, values = self.generate_insert_query(tag_category, "TagCategories")
        return self.execute_insert(query, tuple(values))

    def update_tag_category(self, tag_category_update: TagCategoryUpdate) -> int:
        query, values = self.generate_update_query(tag_category_update, "TagCategories",
                                                   "CategoryId")
        return self.execute_update(query, tuple(values))


if __name__ == '__main__':
    _result = TagCategoryRepository().get_tag_categories()
    print(_result)

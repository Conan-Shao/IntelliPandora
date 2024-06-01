# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : attrvaluesplit.py
@Time  : 2024-05-24
"""
from typing import List, Tuple, Any


class AttrValueSplit:

    def __init__(self, update_data: Any, attr_filter=None):
        self.fields, self.values = self._prepare_update_fields_and_values(update_data, attr_filter)

    @staticmethod
    def _prepare_update_fields_and_values(update_data: Any,
                                          attr_filter) -> Tuple[List[str], List[Any]]:
        fields = []
        values = []
        for field, value in update_data.__dict__.items():
            if value is not None:
                if attr_filter and field != attr_filter:
                    fields.append(f"{field} = %s")
                elif attr_filter is None and field != attr_filter:
                    fields.append(field)
                else:
                    continue
                values.append(value)
        return fields, values

    def get_fields_and_values(self) -> Tuple[List[str], List[Any]]:
        return self.fields, self.values


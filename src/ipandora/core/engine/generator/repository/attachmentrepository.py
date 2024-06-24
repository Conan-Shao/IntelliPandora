# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : attachmentrepository.py
@Time  : 2024-06-02
"""
from typing import List, Optional
from pymysql.connections import Connection
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.core.engine.generator.model.data.case import (Attachment,
                                                            AttachmentGetter)
from ipandora.utils.log import logger


class AttachmentRepository(BaseRepository):

    def get_attachments_by_test_case_id(self, test_case_id: int) -> List[AttachmentGetter]:
        query = self.generate_select_query(AttachmentGetter, "Attachments",
                                           "TestCaseID")
        rows = self.execute_query(query, (test_case_id,))
        return self.filter_fields(rows, AttachmentGetter)
        # return [AttachmentGetter(**row) for row in rows] if rows else []

    def insert_attachment(self, attachment: Attachment) -> int:
        query, values = self.generate_insert_query(attachment, "Attachments")
        return self.execute_insert(query, tuple(values))

    def delete_attachment(self, attachment_id: int) -> int:
        query = """
            DELETE FROM TestCaseAttachments
            WHERE AttachmentID = %s
        """
        return self.execute_update(query, (attachment_id,))

    def update_attachment(self, attachment: Attachment) -> int:
        query, values = self.generate_update_query(attachment, "Attachments",
                                                   "AttachmentID")
        return self.execute_update(query, tuple(values))

    def insert_attachment_as_transaction(self, attachment: Attachment,
                                         connection: Optional[Connection] = None,
                                         last_trans: bool = False):
        query, values = self.generate_insert_query(attachment, "Attachments")
        _conn, result = self.execute_with_transaction(query, tuple(values), connection)
        if last_trans:
            _conn = connection if _conn is None else _conn
            self.commit_transaction(_conn)
        return _conn, result





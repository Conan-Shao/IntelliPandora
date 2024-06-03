# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : testattachmentrepository.py
@Time  : 2024-06-02
"""
from typing import List, Optional
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.core.engine.generator.model.data.testcase import TestAttachment, TestAttachmentGetter
from ipandora.utils.log import logger


class TestAttachmentRepository(BaseRepository):

    def get_attachments_by_test_case_id(self, test_case_id: int) -> List[TestAttachmentGetter]:
        query = """
            SELECT AttachmentID, TestCaseID, FilePath, Description, CreatedTime
            FROM TestCaseAttachments
            WHERE TestCaseID = %s
        """
        rows = self.execute_query(query, (test_case_id,))
        return [TestAttachmentGetter(**row) for row in rows] if rows else []

    def insert_attachment(self, attachment: TestAttachment) -> int:
        query, values = self.generate_insert_query(attachment, "TestCaseAttachments")
        return self.execute_insert(query, tuple(values))

    def delete_attachment(self, attachment_id: int) -> int:
        query = """
            DELETE FROM TestCaseAttachments
            WHERE AttachmentID = %s
        """
        return self.execute_update(query, (attachment_id,))

    def update_attachment(self, attachment: TestAttachment) -> int:
        query, values = self.generate_update_query(attachment, "TestCaseAttachments",
                                                   "AttachmentID")
        return self.execute_update(query, tuple(values))

    def insert_attachment_as_transaction(self, attachment: TestAttachment,
                                         last_trans: bool = False):
        query, values = self.generate_insert_query(attachment, "TestCaseAttachments")
        _conn, result = self.execute_with_transaction(query, tuple(values))
        if last_trans:
            self.commit_transaction(_conn)
        return _conn, result





# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : projectrepository.py
@Time  : 2024-05-23
"""
from typing import List

from ipandora.core.base.classwrap.attrvaluesplit import AttrValueSplit
from ipandora.core.engine.generator.model.data.testcase import Project, ProjectUpdate
from ipandora.core.base.repository.baserepository import BaseRepository
from ipandora.utils.log import logger


class ProjectRepository(BaseRepository):

    def get_projects(self) -> List[Project]:
        query = "SELECT * FROM Projects"
        rows = self.execute_query(query)
        return [Project(**row) for row in rows] if rows else []

    def insert_project(self, project: Project) -> int:
        fields, values = AttrValueSplit(project).get_fields_and_values()
        query = f"""
            INSERT INTO Projects ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        return self.execute_insert(query, tuple(values))

    def update_project(self, project_update: ProjectUpdate) -> int:
        fields, values = AttrValueSplit(project_update, "ProjectID").get_fields_and_values()
        query = f"""
            UPDATE Projects
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE ProjectID = %s
        """
        values.append(project_update.ProjectID)
        return self.execute_update(query, tuple(values))


if __name__ == '__main__':
    resp = ProjectRepository().get_projects()
    print(resp)

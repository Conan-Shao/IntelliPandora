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
        return self.filter_fields(rows, Project)

    def insert_project(self, project: Project) -> int:
        query, values = self.generate_insert_query(project, "Projects")
        return self.execute_insert(query, tuple(values))

    def update_project(self, project_update: ProjectUpdate) -> int:
        query, values = self.generate_update_query(project_update, "Projects", "ProjectID")
        return self.execute_update(query, tuple(values))


if __name__ == '__main__':
    resp = ProjectRepository().get_projects()
    print(resp)

# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : case.py
@Time  : 2024-06-24
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Project:
    ProjectID: Optional[int]
    ProjectName: str
    Description: Optional[str]
    StartDate: Optional[datetime]
    EndDate: Optional[datetime]
    Status: str
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class ProjectUpdate:
    ProjectID: Optional[int]
    ProjectName: str = None
    Description: Optional[str] = None
    StartDate: Optional[datetime] = None
    EndDate: Optional[datetime] = None
    Status: str = None


@dataclass
class Module:
    ModuleID: Optional[int]
    ProjectID: int
    ModuleName: str
    Description: Optional[str]
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class ModuleUpdate:
    ModuleID: Optional[int]
    ProjectID: int = None
    ModuleName: str = None
    Description: Optional[str] = None


@dataclass
class Submodule:
    SubmoduleID: Optional[int]
    ModuleID: int
    SubmoduleName: str
    Description: Optional[str]
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class SubmoduleUpdate:
    SubmoduleID: Optional[int]
    ModuleID: int = None
    SubmoduleName: str = None
    Description: Optional[str] = None


@dataclass
class Case:
    TestCaseID: Optional[int]
    SubmoduleID: Optional[int]
    Title: str
    Description: Optional[str]
    Precondition: Optional[str]
    Source: Optional[str]
    IsAutomated: bool
    ExcelCaseID: Optional[int] = None
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class CaseUpdate:
    TestCaseID: Optional[int]
    SubmoduleID: Optional[int] = None
    Title: Optional[str] = None
    Description: Optional[str] = None
    Precondition: Optional[str] = None
    IsAutomated: Optional[bool] = None


@dataclass
class Step:
    StepID: Optional[int]
    TestCaseID: Optional[int]
    StepNumber: int
    StepDescription: Optional[str]
    ExpectedResult: Optional[str]
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class StepUpdate:
    StepID: Optional[int]
    TestCaseID: Optional[int] = None
    StepNumber: int = None
    StepDescription: Optional[str] = None
    ExpectedResult: Optional[str] = None


@dataclass
class StepGetter:
    StepNumber: int
    StepDescription: Optional[str]
    ExpectedResult: Optional[str]


@dataclass
class TagCategory:
    CategoryId: Optional[int]
    CategoryName: str
    Description: Optional[str]
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class TagCategoryUpdate:
    CategoryId: Optional[int]
    CategoryName: str = None
    Description: Optional[str] = None


@dataclass
class Tag:
    TagID: Optional[int]
    CategoryId: int
    TagName: str
    Description: Optional[str]
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class TagUpdate:
    TagID: Optional[int]
    CategoryId: int = None
    TagName: str = None
    Description: Optional[str] = None


@dataclass
class CaseTag:
    TestCaseID: int
    TagID: int
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class CaseTagUpdate:
    TestCaseID: int
    TagID: int = None


@dataclass
class Attachment:
    AttachmentID: Optional[int]
    TestCaseID: Optional[int]
    OriginalFileName: Optional[str]
    OriginalLink: Optional[str]
    FilePath: Optional[str]
    Description: Optional[str] = None
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None


@dataclass
class AttachmentGetter:
    OriginalFileName: Optional[str]
    FilePath: Optional[str]
    Description: Optional[str]


@dataclass
class TestCaseFull:
    TestCaseID: Optional[int]
    Title: str
    ModuleID: Optional[int]
    ModuleName: Optional[str]
    SubmoduleID: Optional[int]
    SubmoduleName: Optional[str]
    Description: Optional[str]
    Precondition: Optional[str]
    Source: Optional[str]
    IsAutomated: bool
    ExcelCaseID: Optional[int] = None
    Tags: List[str] = field(default_factory=list)
    Steps: List[StepGetter] = field(default_factory=list)
    Attachments: List[AttachmentGetter] = field(default_factory=list)
    ModifiedBy: Optional[str] = None
    CreatedTime: Optional[datetime] = None
    UpdatedTime: Optional[datetime] = None

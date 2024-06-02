-- 1.创建database
CREATE DATABASE TestCasesDB;
USE TestCasesDB;

-- 2. 创建project
CREATE TABLE Projects (
    ProjectID INT AUTO_INCREMENT PRIMARY KEY,
    ProjectName VARCHAR(255) NOT NULL,
    Description TEXT,
    StartDate DATE,
    EndDate DATE,
    Status ENUM('Active', 'Inactive', 'Completed') DEFAULT 'Active',
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100)
) DEFAULT CHARACTER SET utf8mb4;

-- 3. 创建module 和 submodule
CREATE TABLE Modules (
    ModuleID INT AUTO_INCREMENT PRIMARY KEY,
    ProjectID INT,
    ModuleName VARCHAR(100) NOT NULL,
    Description TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (ProjectID) REFERENCES Projects(ProjectID)
) DEFAULT CHARACTER SET utf8mb4;

CREATE TABLE Submodules (
    SubmoduleID INT AUTO_INCREMENT PRIMARY KEY,
    ModuleID INT,
    SubmoduleName VARCHAR(100) NOT NULL,
    Description TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (ModuleID) REFERENCES Modules(ModuleID)
) DEFAULT CHARACTER SET utf8mb4;

-- 4.创建case 和 step
CREATE TABLE TestCases (
    TestCaseID INT AUTO_INCREMENT PRIMARY KEY,
    ProjectID INT,
    SubmoduleID INT,
    Title VARCHAR(255) NOT NULL,
    Description TEXT,
    Precondition TEXT,
    IsAutomated BOOL NOT NULL DEFAULT 0,  -- 使用 BOOL 类型，0 表示“否”，即非自动化用例, 1 表示“是”，即自动化用例
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (SubmoduleID) REFERENCES Submodules(SubmoduleID),
    FOREIGN KEY (ProjectID) REFERENCES Projects(ProjectID)
) DEFAULT CHARACTER SET utf8mb4;

CREATE TABLE TestSteps (
    StepID INT AUTO_INCREMENT PRIMARY KEY,
    TestCaseID INT,
    StepNumber INT,
    StepDescription TEXT,
    ExpectedResult TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (TestCaseID) REFERENCES TestCases(TestCaseID)
) DEFAULT CHARACTER SET utf8mb4;


-- 5. 创建tag、TagCategories、TestCaseTags
CREATE TABLE TagCategories (
    CategoryId INT AUTO_INCREMENT PRIMARY KEY,
    CategoryName VARCHAR(100) NOT NULL,
    Description TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100)
)DEFAULT CHARACTER SET utf8mb4;

CREATE TABLE Tags (
    TagID INT AUTO_INCREMENT PRIMARY KEY,
    CategoryId INT,
    TagName VARCHAR(100) NOT NULL,
    Description TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (CategoryId) REFERENCES TagCategories(CategoryId)
) DEFAULT CHARACTER SET utf8mb4;

CREATE TABLE TestCaseTags (
    TestCaseID INT,
    TagID INT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    PRIMARY KEY (TestCaseID, TagID),
    FOREIGN KEY (TestCaseID) REFERENCES TestCases(TestCaseID),
    FOREIGN KEY (TagID) REFERENCES Tags(TagID)
) DEFAULT CHARACTER SET utf8mb4;

CREATE TABLE TestCaseAttachments (
    AttachmentID INT AUTO_INCREMENT PRIMARY KEY,
    TestCaseID INT,
    OriginalFileName VARCHAR(255),  -- 修改字段名以反映它存储的是文件的原始名称
    FilePath VARCHAR(512),  -- 存储基于时间戳和UUID生成的唯一文件路径
    Description TEXT,
    CreatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UpdatedTime DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100),
    FOREIGN KEY (TestCaseID) REFERENCES TestCases(TestCaseID)
);
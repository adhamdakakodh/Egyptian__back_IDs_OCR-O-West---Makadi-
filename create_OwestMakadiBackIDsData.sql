CREATE TABLE dbo.OwestMakadiBackIDsData (
    id                       INT IDENTITY(1, 1) NOT NULL,
    national_id_back         NVARCHAR(14)  NULL,
    issuing_date_back        NVARCHAR(20)  NULL,
    profession_workplace_back NVARCHAR(500) NULL,
    gender_back              NVARCHAR(20)  NULL,
    religion_back            NVARCHAR(50)  NULL,
    marital_status_back      NVARCHAR(50)  NULL,
    husband_name_back        NVARCHAR(255) NULL,
    valid_until_back         NVARCHAR(20)  NULL,
    created_at               DATETIME2(0)  NOT NULL CONSTRAINT DF_OwestMakadiBackIDsData_created_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_OwestMakadiBackIDsData PRIMARY KEY CLUSTERED (id)
);

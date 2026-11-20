/*
  Student SQL sandbox (handoff section 9.3): a SEPARATE database and a least-privilege login.
  Idempotent. Run as a sysadmin with Windows auth; the name and password come in as sqlcmd
  variables so no password is stored in this file. The password comes ONLY from the
  SANDBOX_PASSWORD environment variable (sqlcmd reads it); never pass it with -v:

    sqlcmd -S localhost -E -C -b -v SANDBOX_DB=<db> SANDBOX_LOGIN=<login> -i database\sandbox_setup.sql

  Command-line values are visible in the process list and shell history. Mirror the same values into
  backend/.env (SANDBOX_DB_NAME, SANDBOX_DB_USER, SANDBOX_DB_PASSWORD).
  These permissions are the real control. The app-side validator is defense in depth only.
  Sandbox object reset: database/sandbox_reset.sql (scheduled, not SQL Agent).
*/
/* Guards run first, before any login is created or altered. */
:on error exit
USE [master];
GO
IF N'$(SANDBOX_DB)' LIKE N'%[^A-Za-z0-9_]%' OR N'$(SANDBOX_LOGIN)' LIKE N'%[^A-Za-z0-9_]%' OR N'$(SANDBOX_DB)' = N'' OR N'$(SANDBOX_LOGIN)' = N''
    THROW 50002, N'SANDBOX_DB and SANDBOX_LOGIN must be non-empty and contain only letters, digits and underscore.', 1;
IF LOWER(N'$(SANDBOX_DB)') IN (N'synorav1', N'synorav1_test', N'master', N'model', N'msdb', N'tempdb') OR LOWER(N'$(SANDBOX_DB)') NOT LIKE N'%sandbox%' AND LOWER(N'$(SANDBOX_DB)') NOT LIKE N'%sbx%' AND LOWER(N'$(SANDBOX_DB)') NOT LIKE N'%lab%'
    THROW 50003, N'SANDBOX_DB must be a dedicated sandbox/lab database (name contains sandbox, sbx or lab) and never an application or system database.', 1;
IF LOWER(N'$(SANDBOX_LOGIN)') IN (N'sa', N'synora_app') OR IS_SRVROLEMEMBER(N'sysadmin', N'$(SANDBOX_LOGIN)') = 1
    THROW 50004, N'SANDBOX_LOGIN must be a dedicated sandbox login, not sa, synora_app or a sysadmin.', 1;
IF LOWER(N'$(SANDBOX_LOGIN)') NOT LIKE N'%sandbox%' AND LOWER(N'$(SANDBOX_LOGIN)') NOT LIKE N'%sbx%'
    THROW 50005, N'SANDBOX_LOGIN name must contain sandbox or sbx so an unrelated login is never rotated.', 1;
-- The password is pasted into T-SQL below: allow only characters that cannot break out of the string.
IF N'$(SANDBOX_PASSWORD)' LIKE N'%[^A-Za-z0-9_.!@#%-]%' OR LEN(N'$(SANDBOX_PASSWORD)') < 16
    THROW 50006, N'SANDBOX_PASSWORD must be 16+ characters from A-Z a-z 0-9 _ . ! @ # % - only.', 1;
-- Fail closed BEFORE the login is changed: an existing sandbox DB must hold no dbo user objects.
IF DB_ID(N'$(SANDBOX_DB)') IS NOT NULL
BEGIN
    DECLARE @n INT;
    EXEC sp_executesql N'SELECT @n = COUNT(*) FROM [$(SANDBOX_DB)].sys.objects WHERE schema_id = SCHEMA_ID(N''dbo'') AND is_ms_shipped = 0', N'@n INT OUTPUT', @n = @n OUTPUT;
    IF @n > 0 THROW 50007, N'Sandbox database has user objects in schema dbo; refusing before any login change.', 1;
END
GO
USE [master];
GO
IF SUSER_ID(N'$(SANDBOX_LOGIN)') IS NULL
    CREATE LOGIN [$(SANDBOX_LOGIN)] WITH PASSWORD = N'$(SANDBOX_PASSWORD)', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;
ELSE
    ALTER LOGIN [$(SANDBOX_LOGIN)] WITH PASSWORD = N'$(SANDBOX_PASSWORD)', CHECK_POLICY = ON;
-- Hide other databases' names (sys.databases would otherwise list every database on the instance).
DENY VIEW ANY DATABASE TO [$(SANDBOX_LOGIN)];
GO
IF DB_ID(N'$(SANDBOX_DB)') IS NULL CREATE DATABASE [$(SANDBOX_DB)];
GO
USE [$(SANDBOX_DB)];
GO
-- Students hold ALTER on schema sbx (owned by dbo), so a trigger they create there runs with ownership
-- chaining into any dbo object. The sandbox DB must therefore hold NO dbo user objects. Fail closed.
IF EXISTS (SELECT 1 FROM sys.objects WHERE schema_id = SCHEMA_ID(N'dbo') AND is_ms_shipped = 0)
   OR EXISTS (SELECT 1 FROM sys.types WHERE schema_id = SCHEMA_ID(N'dbo') AND is_user_defined = 1)
    THROW 50001, N'Sandbox database has user objects in schema dbo. Use an empty database dedicated to the sandbox.', 1;
GO
IF SCHEMA_ID(N'sbx') IS NULL EXEC (N'CREATE SCHEMA [sbx] AUTHORIZATION [dbo]');
IF DATABASE_PRINCIPAL_ID(N'$(SANDBOX_LOGIN)') IS NULL CREATE USER [$(SANDBOX_LOGIN)] FOR LOGIN [$(SANDBOX_LOGIN)];
ALTER USER [$(SANDBOX_LOGIN)] WITH DEFAULT_SCHEMA = [sbx];
-- Remove the broad roles an earlier version granted (db_ddladmin lets students create procedures and triggers).
IF IS_ROLEMEMBER(N'db_ddladmin', N'$(SANDBOX_LOGIN)') = 1 ALTER ROLE [db_ddladmin] DROP MEMBER [$(SANDBOX_LOGIN)];
IF IS_ROLEMEMBER(N'db_datareader', N'$(SANDBOX_LOGIN)') = 1 ALTER ROLE [db_datareader] DROP MEMBER [$(SANDBOX_LOGIN)];
IF IS_ROLEMEMBER(N'db_datawriter', N'$(SANDBOX_LOGIN)') = 1 ALTER ROLE [db_datawriter] DROP MEMBER [$(SANDBOX_LOGIN)];
GRANT CREATE TABLE TO [$(SANDBOX_LOGIN)];
GRANT SELECT, INSERT, UPDATE, DELETE, ALTER ON SCHEMA::[sbx] TO [$(SANDBOX_LOGIN)];
DENY CREATE PROCEDURE TO [$(SANDBOX_LOGIN)];
DENY CREATE FUNCTION TO [$(SANDBOX_LOGIN)];
DENY CREATE TYPE TO [$(SANDBOX_LOGIN)];
-- CREATE SEQUENCE is a schema-scoped permission. CREATE TRIGGER cannot be denied at all: a DML trigger
-- needs ALTER on its table, which the schema grant above gives. Triggers stay inside the rolled-back
-- transaction and the leak detector removes any that persist (see docs/technical/practice-execution.md).
DENY CREATE SEQUENCE ON SCHEMA::[sbx] TO [$(SANDBOX_LOGIN)];
DENY ALTER ON SCHEMA::[dbo] TO [$(SANDBOX_LOGIN)];
GO
-- Bound the sandbox's disk use and keep the log from growing without limit. Re-runs reapply the caps.
ALTER DATABASE CURRENT SET RECOVERY SIMPLE;
DECLARE @name SYSNAME, @type TINYINT, @sql NVARCHAR(MAX);
DECLARE file_cursor CURSOR LOCAL FAST_FORWARD FOR SELECT name, type FROM sys.database_files;
OPEN file_cursor;
FETCH NEXT FROM file_cursor INTO @name, @type;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'ALTER DATABASE CURRENT MODIFY FILE (NAME = N''' + REPLACE(@name, N'''', N'''''')
        + N''', MAXSIZE = ' + CASE WHEN @type = 1 THEN N'256MB' ELSE N'512MB' END + N');';
    EXEC (@sql);
    FETCH NEXT FROM file_cursor INTO @name, @type;
END
CLOSE file_cursor;
DEALLOCATE file_cursor;
GO
-- Report only (not changed here): guest must not connect to this DB; these instance options must stay off.
SELECT N'guest CONNECT in this database' AS check_name,
       CASE WHEN EXISTS (SELECT 1 FROM sys.database_permissions p
                         WHERE p.grantee_principal_id = DATABASE_PRINCIPAL_ID(N'guest')
                           AND p.permission_name = N'CONNECT' AND p.state_desc LIKE N'GRANT%')
            THEN N'ENABLED (expected disabled)' ELSE N'disabled' END AS status;
SELECT name AS instance_option, CAST(value_in_use AS INT) AS value_in_use
FROM sys.configurations
WHERE name IN (N'xp_cmdshell', N'Ole Automation Procedures', N'Ad Hoc Distributed Queries');
GO

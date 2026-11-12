/*
  Student SQL sandbox (handoff section 9.3): a SEPARATE database and a least-privilege login.
  Idempotent. Run as a sysadmin with Windows auth; the name and password come in as sqlcmd
  variables so no password is stored in this file:

    sqlcmd -S localhost -E -C -b -v SANDBOX_DB=<db> SANDBOX_LOGIN=<login> SANDBOX_PASSWORD=<pw> -i database\sandbox_setup.sql

  The -v value is visible in the process list while sqlcmd runs. Mirror the same values into
  backend/.env (SANDBOX_DB_NAME, SANDBOX_DB_USER, SANDBOX_DB_PASSWORD).
  These permissions are the real control. The app-side validator is defense in depth only.
  Sandbox object reset: database/sandbox_reset.sql (scheduled, not SQL Agent).
*/
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

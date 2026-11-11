/*
  Student SQL sandbox (handoff section 9.3): a SEPARATE database and low-privilege login.
  The app never runs student SQL against SynoraV1. Run as a sysadmin, e.g.:
    sqlcmd -S localhost -E -i database/sandbox_setup.sql
  Change the password and mirror it in backend/.env (SANDBOX_DB_*).
*/
IF DB_ID('SynoraV1_Sandbox') IS NULL CREATE DATABASE SynoraV1_Sandbox;
GO
IF SUSER_ID('synora_sandbox') IS NULL
    CREATE LOGIN synora_sandbox WITH PASSWORD = 'Sandbox@2026!', CHECK_POLICY = OFF;
GO
USE SynoraV1_Sandbox;
GO
IF USER_ID('synora_sandbox') IS NULL CREATE USER synora_sandbox FOR LOGIN synora_sandbox;
-- DDL + DML inside the sandbox DB only; no server-level rights, no access to other databases.
ALTER ROLE db_ddladmin  ADD MEMBER synora_sandbox;
ALTER ROLE db_datareader ADD MEMBER synora_sandbox;
ALTER ROLE db_datawriter ADD MEMBER synora_sandbox;
GO

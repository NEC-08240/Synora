/*
  Template-reset backstop for the SQL sandbox: drops every user object in the sbx schema.
  The per-request rollback and the app's leak detector already clean up; this covers anything
  that slips through (for example a run interrupted by a crash).

  SQL Server Express has no SQL Agent, so this runs from Windows Task Scheduler with sqlcmd.
  Schedule it on the server (for example nightly), as the same account that can run
  sandbox_setup.sql:

    sqlcmd -S localhost -E -C -b -v SANDBOX_DB=<db> -i database\sandbox_reset.sql

  Foreign keys go first, then views/procedures/functions/synonyms/sequences, then tables, then types.
*/
USE [$(SANDBOX_DB)];
GO
DECLARE @sql NVARCHAR(MAX) = N'';
SELECT @sql += N'ALTER TABLE ' + QUOTENAME(SCHEMA_NAME(t.schema_id)) + N'.' + QUOTENAME(t.name)
    + N' DROP CONSTRAINT ' + QUOTENAME(fk.name) + N';'
FROM sys.foreign_keys fk
JOIN sys.tables t ON t.object_id = fk.parent_object_id
WHERE SCHEMA_NAME(fk.schema_id) = N'sbx';
SELECT @sql += N'DROP ' + CASE type WHEN 'V' THEN N'VIEW ' WHEN 'P' THEN N'PROCEDURE '
        WHEN 'SN' THEN N'SYNONYM ' WHEN 'SO' THEN N'SEQUENCE ' ELSE N'FUNCTION ' END
    + QUOTENAME(SCHEMA_NAME(schema_id)) + N'.' + QUOTENAME(name) + N';'
FROM sys.objects
WHERE is_ms_shipped = 0 AND SCHEMA_NAME(schema_id) = N'sbx' AND type IN ('V', 'P', 'SN', 'SO', 'FN', 'IF', 'TF');
SELECT @sql += N'DROP TABLE ' + QUOTENAME(SCHEMA_NAME(schema_id)) + N'.' + QUOTENAME(name) + N';'
FROM sys.tables
WHERE is_ms_shipped = 0 AND SCHEMA_NAME(schema_id) = N'sbx';
SELECT @sql += N'DROP TYPE ' + QUOTENAME(SCHEMA_NAME(schema_id)) + N'.' + QUOTENAME(name) + N';'
FROM sys.types
WHERE is_user_defined = 1 AND SCHEMA_NAME(schema_id) = N'sbx';
IF LEN(@sql) > 0 EXEC sp_executesql @sql;
GO

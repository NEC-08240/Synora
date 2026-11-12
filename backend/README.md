# Synora backend (Node.js + Express + SQL Server)

## Setup

1. SQL Server 2019+ with TCP/IP enabled on port 1433 and mixed-mode authentication.
2. Create the database: run `database/schema.sql` (SSMS or `sqlcmd -S localhost -E -i database/schema.sql`).
3. Create an application login with data read/write on `SynoraV1`:
   ```sql
   CREATE LOGIN synora_app WITH PASSWORD = '<strong password>';
   USE SynoraV1; CREATE USER synora_app FOR LOGIN synora_app;
   ALTER ROLE db_datareader ADD MEMBER synora_app; ALTER ROLE db_datawriter ADD MEMBER synora_app;
   ```
4. `cp .env.example .env` and fill in `DB_PASSWORD` and a random `JWT_SECRET`.
5. `npm install && npm run seed && npm run dev` → http://localhost:4000/api/v1/health

## Demo accounts (created by `npm run seed`, password `Synora@2026`)

| Role | Email |
|------|-------|
| Administrator | admin@synora.local |
| Faculty | faculty@synora.local |
| Student | student@synora.local |

## Tests

Integration tests run against a second database so seed/demo data is never touched:

```
sed "s/SynoraV1/SynoraV1_Test/g" ../database/schema.sql | sqlcmd -S localhost -E
# grant synora_app the same roles on SynoraV1_Test, then:
cp .env .env.test   # set DB_NAME=SynoraV1_Test and PORT=0
# SQL sandbox tests need the separate sandbox DB (see docs/technical/practice-execution.md):
sqlcmd -S localhost -E -C -b -v SANDBOX_DB=<db> SANDBOX_LOGIN=<login> SANDBOX_PASSWORD=<pw> -i ../database/sandbox_setup.sql
# REQUIRE_SANDBOX_TESTS=1 makes skipped sandbox tests (no lab env, no sqlcmd/Windows auth) fail loudly; unset = skip with a warning
# then set SANDBOX_DB_NAME/USER/PASSWORD in .env.test (empty dedicated database; setup refuses dbo objects)
npm run seed:test && npm test
```

API contract: see `docs/technical/api-spec.md`.

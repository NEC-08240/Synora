# Synora backend (Node.js + Express + SQL Server)

## Setup

1. SQL Server 2019+ with TCP/IP enabled on port 1433 and mixed-mode authentication.
2. Create the database: run `database/schema.sql` with an explicit target (there is no default): `sqlcmd -S localhost -E -C -b -v DB_NAME=SynoraV1 -i database/schema.sql`, then check it with `sqlcmd -S localhost -E -C -b -v DB_NAME=SynoraV1 -i database/validate_schema.sql`.
3. Create an application login with data read/write on `SynoraV1`:
   ```sql
   CREATE LOGIN synora_app WITH PASSWORD = '<strong password>';
   USE SynoraV1; CREATE USER synora_app FOR LOGIN synora_app;
   ALTER ROLE db_datareader ADD MEMBER synora_app; ALTER ROLE db_datawriter ADD MEMBER synora_app;
   ```
4. `cp .env.example .env` and fill in `DB_PASSWORD`, a random `JWT_SECRET`, and `SEED_PASSWORD` (12+ characters, no default).
5. `npm install`, then seed the demo data (see below), then `npm run dev` → http://localhost:4000/api/v1/health

Seeding is guarded: `scripts/seed.js` refuses to run when `NODE_ENV=production`, and refuses unless `ALLOW_SEED=1` is set. Only seed a disposable database. The target `DB_NAME` is printed before any write:

```
ALLOW_SEED=1 npm run seed
```

## Demo accounts (created by `npm run seed`; password is the `SEED_PASSWORD` you set)

| Role | Email |
|------|-------|
| Administrator | admin@synora.local |
| Faculty | faculty@synora.local |
| Student | student@synora.local |

## Tests

Integration tests run against a disposable scratch database, never a real one. `npm test`, `npm run test:ci` and `npm run seed:test` refuse to start unless `DB_NAME` (and `SANDBOX_DB_NAME`, if set) starts with `SynoraT` (for example `SynoraT_Local`, `SynoraT_Sandbox`). `SynoraV1`, `SynoraV1_Test` and `SynoraV1_Sandbox` are refused. Keep `.env.test` untracked.

```
sqlcmd -S localhost -E -C -b -v DB_NAME=SynoraT_Local -i ../database/schema.sql
# grant synora_app the same roles on SynoraT_Local, then:
cp .env .env.test   # set DB_NAME=SynoraT_Local and PORT=0
# SQL sandbox tests need the separate sandbox DB (see docs/technical/practice-execution.md):
sqlcmd -S localhost -E -C -b -v SANDBOX_DB=<db> SANDBOX_LOGIN=<login> SANDBOX_PASSWORD=<pw> -i ../database/sandbox_setup.sql
# REQUIRE_SANDBOX_TESTS=1 makes skipped sandbox tests (no lab env, no sqlcmd/Windows auth) fail loudly; unset = skip with a warning
# then set SANDBOX_DB_NAME/USER/PASSWORD in .env.test (empty dedicated database; setup refuses dbo objects)
# .env.test also needs SEED_PASSWORD (12+ chars) and ALLOW_SEED=1
npm run seed:test && npm test
```

The test helpers overwrite the demo users' password hashes with random values, so after any test run the demo accounts no longer accept `SEED_PASSWORD`. `npm run seed` never updates existing users, so for the browser smoke test (`frontend`: `npm run smoke`) use a freshly seeded database and run the smoke test **before** `npm test` / `npm run test:ci`; on a used database, recreate it or reset the three demo users' `PasswordHash` first.

API contract: see `docs/technical/api-spec.md`.

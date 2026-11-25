# Contributing to Synora

Thank you for contributing to the Synora Live Smart Edification project.

This document defines the basic GitHub workflow and development practices
followed by the project team.

## Development Workflow

All project work should follow this general workflow:

Issue → Branch → Commit → Pull Request → Review → Merge

## Branches

The `main` branch contains reviewed and stable project work.

Do not directly push development work to `main`.

Create a branch for each task.

### Branch naming

Use the following formats:

- `feature/<name>` - New functionality
- `fix/<name>` - Bug fixes
- `docs/<name>` - Documentation changes
- `prototype/<name>` - UI or design prototypes
- `chore/<name>` - Repository or development setup changes

Examples:

```text
feature/student-learning-hub
docs/page-inventory
prototype/learning-workspace
chore/add-gitignore

## Commits

Use conventional commits: `<type>: <description>` with type `feat`, `fix`, `docs`, `test`,
`refactor`, `chore`, `perf` or `ci` (for example `feat(frontend): student dashboard layout`).

## Pull requests

- One PR per screen or feature. Keep it small and limited to the task.
- Target `main`, unless it is frontend design work (see below).
- `npm run lint`, `npm test` and `npm run build` must pass in `frontend/`, and `npm test` in
  `backend/` if you touched it. CI (`.github/workflows/ci.yml`) runs these on every PR; do not merge red.
- Fill in the PR template, with screenshots for any UI change.
- Never commit secrets or `.env` files (only `.env.example` with placeholders).
- Never point the app or tests at a real database. Backend tests refuse any `DB_NAME` not starting
  with `SynoraT`; see `backend/README.md` for the scratch-database setup.
- Setup steps are in the README under "Running locally".

## Frontend design work

Design and theme work targets branch `feat/grey-theme`, not `main`, and follows
`docs/design/light-redesign-plan.md`. That file exists only on `feat/grey-theme`, so
`git fetch origin && git switch feat/grey-theme` first, then branch from it
(`feature/<screen-name>`) and open the PR against `feat/grey-theme`.
Design tasks change styling and markup only: do not change logic, API calls or tests.

## AI assistants (Claude, Gemini, others)

The rules above apply equally to AI-assisted work, and you are responsible for what you commit:

- Give the assistant this file and the issue; keep it to the one screen or feature.
- It must not read, print or commit `.env` files or secrets, or run anything against a real database.
- It must not change logic, API or tests in a design task, and must not add dependencies unasked.
- Review the diff yourself and run lint, tests and build before opening the PR.
- Do not commit assistant state or scratch files (`.claude/`, `.playwright-mcp/`, handoff notes).

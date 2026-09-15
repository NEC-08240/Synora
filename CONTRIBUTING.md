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

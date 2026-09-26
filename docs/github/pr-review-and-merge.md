# Synora PR Review & Merge Format

## 1. Reviewer Approval Comment

Use the following format when reviewing a completed PR:

## Review Result

- [x] Approved

### Comments

Reviewed the changes against the approved Synora scope, relevant documentation, and design requirements.

The submitted changes are consistent with the intended project scope and no blocking issues were found.

---

## 2. Merge Message

Use the following format when merging an approved PR:

### Merge Title

Merge pull request #X from NEC-08240/<branch-name>

### Merge Description

Merge <short description> into main.

Includes:
- <change 1>
- <change 2>
- <change 3>

---

## 3. Review and Merge Workflow

Issue
↓
Feature / Prototype Branch
↓
Development
↓
Pull Request
↓
Peer Review
↓
Approval
↓
Merge into `main`

---

## 4. Rules

- Pull requests must be reviewed before merging.
- At least one approval is required.
- Do not push directly to `main`.
- Do not merge without required approval.
- Keep review comments clear and specific.
- Keep merge messages related to the actual PR.
- Do not create unnecessary commits or PRs.
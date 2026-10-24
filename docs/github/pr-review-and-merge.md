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

---

## GitHub governance

Applies to `NEC-08240/Synora`. Live state is checked with the commands in the
[recovery runbook, section 11](../operations/recovery-runbook.md#11-github-ruleset-or-codeowners-recovery).
Configured 2026-10-24.

### Protection on `main`

Ruleset `Protect main` (id `23422368`), enforcement active:

| Rule | Setting |
|---|---|
| Direct pushes | Not allowed. Every change goes through a pull request. |
| Pull request required | Yes |
| Approvals | One |
| Code-owner review | Required |
| Deletion of `main` | Blocked |
| Force push (non-fast-forward) | Blocked |
| Bypass actors | One: the team `mainline-owners` (id `20296003`), mode `always` |

No administrator bypass, and no user bypass. Rajaneesh and the other teammates are not bypass actors.

**Observed behaviour (2026-10-24, PR #25):** the bypass team did **not** let a normal merge request from Johan's account
through. `gh pr merge` returned "base branch policy prohibits the merge" for a PR that Johan's account had authored. GitHub
does not allow an author to approve their own PR, so that PR had no approval that could satisfy the rule. The bypass
therefore does not apply through the normal merge path. Whether the GitHub UI "merge without waiting" option works for
such a PR is **not verified**. Do not use `--admin` or any other bypass workaround to merge a PR.

### CODEOWNERS

`.github/CODEOWNERS` contains one rule:

```text
# Johan is the final review authority for the canonical main branch.
* @StevefromSpace
```

Every path needs Johan's approval. A change to CODEOWNERS is itself a change to protected `main`, so it goes through a PR
that Johan approves.

### Who holds what

| Person or identity | GitHub role | Merge authority on `main` |
|---|---|---|
| Johan (`StevefromSpace`) | Owner, member of `mainline-owners` | Final authority. Code owner. Cannot approve his own PRs, so a PR authored from his account needs a manual bypass merge (see below). |
| Rajaneesh T V (`rajaneesh`) | Repository **Admin**, intentionally kept | None. Not a bypass actor, not a code owner. Merging to `main` needs Johan's approval. |
| Other developers (`suma026`, `Nithyashri-008`, `Poja-006`) | Organisation members with push access to the repository | None on `main`. Their PRs need Johan's approval. |
| AI sessions (Claude) | Use Johan's GitHub credentials. No separate AI account. | Same as Johan in GitHub's eyes. Governed by the rule below. |

Admin authority and merge authority are different things. Rajaneesh's Admin role lets him change repository settings,
including the ruleset, on the free plan. That is an accepted limit (the runbook records it). Merge authority on `main`
comes from the ruleset and CODEOWNERS, and both are configured so that Johan decides.

### Rules for AI and automation

- **Do not merge to `main` without explicit authorization from Johan** for that specific PR. Approval given for one
  action does not extend to the next.
- Do not use the bypass to merge for convenience. Use it only when Johan has explicitly asked for that merge.
- Routine automated merging is not in place. Each PR needs an approval from someone other than its author, so an AI-authored
  PR still needs a human reviewer who is not the author.
- Do not modify the ruleset, the team, or CODEOWNERS to get a change merged.
- AI sessions do not hold a separate identity. Actions they take appear as Johan. Treat every AI-driven GitHub action as
  Johan's action when reviewing the audit trail.
- Do not place a token in the repository, in a PR, or in `worker.env`.

### Verification

```text
gh api repos/NEC-08240/Synora/rulesets/23422368 --jq '{enforcement, bypass_actors}'
gh api orgs/NEC-08240/teams/mainline-owners/members --jq '[.[].login]'
```

Expected: `active`; the team `20296003` as the only bypass actor; members `["StevefromSpace"]`.
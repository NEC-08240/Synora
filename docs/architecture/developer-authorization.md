# Developer authorization and the control plane

Status: implemented on `feature/manager-authorization`. Production policy migration prepared, **not executed**.

## Model

Authority comes from three places, each enforced in code:

| Layer | Where | What it decides |
|---|---|---|
| Identity | Gateway challenge-response, `team.json` public key | Who the request is from. The developer ID comes from the authenticated session, never from the request body. |
| Branch | `authorization.check_submit_task`, Worker `_intake` | Which branch names a developer may use (`allowed_branches`). `main` is never matched by any entry that does not name it. |
| Path | `path_scope.py`, `bridge.scope_violations`, `DeveloperEntry.can_touch_file` | Which files a job may change (`assigned_modules`), plus a control-plane denylist that applies to every role. |

Roles (`project_owner`, `developer`, `auditor`) carry no path authority of their own. The only role check in the code is
`is_owner()` for `project_owner`, which bypasses the job-ownership check. An `engineering_manager` role would have
no enforcement behind it, so a manager is a `developer` with a broader module list.

### Module entries

- A directory entry ends with `/` and matches by prefix: `docs/`, `frontend/`.
- A file entry names one file and matches exactly: `README.md`, `.github/pull_request_template.md`.
- `*` matches every path that is not in the control plane.
- Glob entries such as `frontend/*` are refused at enrolment, as before.

### Control plane (denied to every job, every role)

- `tools/pipeline/` (Agent Bridge code, Gateway, Worker, deployment and their docs)
- `.github/workflows/` and `.github/CODEOWNERS`
- Files named `.env`, or ending in `.key`, `.pem`, `.p12`, `.pfx`, and anything under a `secrets/` or `keys/` folder

Matching is case-insensitive for the denylist. Paths containing `..`, drive letters, or that cannot be normalised are
treated as control plane (fail closed). Backslashes and leading slashes are normalised first.

### Bridge enforcement

Every job's actual changed files are checked after Claude runs and before verification:

1. Within the task type's write scope (`WRITE_SCOPE`, unchanged).
2. Not in the control plane.
3. Within the requester's module scope, when the job carries one.

A bridge job without a module scope is refused before any work starts. Jobs queued before the scope column existed
carry no scope and are refused; that is the fail-closed choice.

## Engineering Manager policy for `rajaneesh` (intended)

```text
role:      developer
modules:   README.md, CONTRIBUTING.md, docs/, frontend/, backend/, database/, tests/, prototypes/,
           .github/ISSUE_TEMPLATE/, .github/pull_request_template.md
branches:  feature/rajaneesh/*, fix/rajaneesh/*, docs/rajaneesh/*, prototype/rajaneesh/*
```

Notes:
- `docs/` includes `docs/agent-bridge/`, which is documentation only. The control plane itself is denied separately.
- The branch patterns cover only his own namespaces. They do not reach other developers' branches or `main`.
- `main` is not in any entry, and the ruleset on `main` still requires a pull request.

## Pipeline boundary: what Rajaneesh cannot reach

Through Agent Bridge jobs:
- `tools/pipeline/**` (Agent Bridge, Gateway, Worker, authorization, deployment), including nested paths
- `.github/workflows/**` and `.github/CODEOWNERS`
- Secret-looking files anywhere (`.env`, keys, certificates, `secrets/`, `keys/`)
- Traversal, absolute, drive-letter and case-variant paths to any of the above

Outside Agent Bridge (on the Gateway host, the Worker machine, and in the repository):
- Production `team.json`, `workers.json`, `gateway.env`, TLS material, the database: root-owned on EC2, not in Git.
- Worker private keys and `~/.synora`: on Johan's machine, outside any repository.
- AWS credentials: not in the repository (scanned; no repository secrets or variables exist).

## Security review answers

1. **Enforced by code or registry?** Code. The registry supplies the lists. The denylist and the path check are code, and they apply to every entry, including `*`.
2. **Can Rajaneesh modify `tools/pipeline/` through Agent Bridge?** No. Changed files are checked by the bridge and denied, and `*` does not override the denylist.
3. **Can he reach Agent Bridge secrets through another path?** Not through Agent Bridge. Secrets are not in the repository, and production files are root-owned on EC2. **Through GitHub he can reach the code, see below.**
4. **Path traversal?** Denied (`..` is refused in both the normaliser and the bridge check).
5. **Symlinks?** The bridge cannot create symlinks: Claude's restricted tools have no shell, and Write/Edit create regular files. A symlink committed through GitHub would be checked by its path string. Its target would be stored as text. Low risk, but not verified against a checkout on every platform.
6. **Can he modify the authorization policy?** Not through Agent Bridge (`authorization.py`, `path_scope.py` are control plane). **Through GitHub he can, see below.** Production `team.json` is root-owned and changes only through the admin CLI on the host.
7. **Can he modify deployment configuration to gain pipeline access?** Not through Agent Bridge (`tools/pipeline/deploy/` is control plane). **Through GitHub he can, see below.**
8. **Can he modify GitHub workflows to bypass the boundary?** Not through Agent Bridge (`.github/workflows/` is control plane). **Through GitHub he can, see below.** No workflows exist today.
9. **Does the Agent Bridge scope model protect against these?** For Agent Bridge jobs, yes. It does not govern GitHub actions.
10. **Does broader repository access grant pipeline access through another path?** Through Agent Bridge, no. **Through GitHub, yes, because his repository permission is `admin`.**

## Residual risk: GitHub admin permission (requires Johan's decision)

`rajaneeshappu07-netizen` has **admin** permission on `NEC-08240/Synora`. That is broader than this policy and allows, among
other things:

- merging to `main` (the ruleset requires 0 approvals and has no bypass actors, but admin can still open and merge PRs),
- editing the ruleset on `main`,
- adding or changing workflows and repository settings,
- adding collaborators.

The Agent Bridge changes in this document cannot stop those actions. Recommended, in order:

1. Reduce the permission to `write` for the repository. Command: `gh api -X PUT repos/NEC-08240/Synora/collaborators/rajaneeshappu07-netizen -f permission=push`. **Not run; requires Johan's approval.**
2. Add `.github/CODEOWNERS` with `tools/pipeline/` and `.github/` owned by Johan, and make the ruleset on `main` require code-owner review. This changes repository protection, so it is also for Johan to approve. Do not weaken the ruleset.

## Production migration (prepared, not executed)

Prerequisites, in order:

1. Merge this PR after review.
2. Deploy the merged code to the Gateway host with Git (`git checkout --detach <merged-sha>` as root), then restart `synora-gateway`. The path rules are enforced in the Gateway's repair gate and registry normalisation.
3. Update Johan's Worker checkout to the same commit and restart the Worker task, so bridge jobs enforce the module scope.
4. Apply the scope change on the host, as root, using the new command:

   ```text
   sudo cp -p /etc/synora-gateway/team.json /etc/synora-gateway/team.json.pre-manager-<UTC timestamp>
   cd /opt/synora
   sudo .venv/bin/python -m tools.pipeline.admin_cli update-developer-scope --registry /etc/synora-gateway/team.json --developer-id rajaneesh --modules "README.md,CONTRIBUTING.md,docs/,frontend/,backend/,database/,tests/,prototypes/,.github/ISSUE_TEMPLATE/,.github/pull_request_template.md" --branches "feature/rajaneesh/*,fix/rajaneesh/*,docs/rajaneesh/*,prototype/rajaneesh/*"
   sudo chown root:synora-gateway /etc/synora-gateway/*.json
   sudo chmod 640 /etc/synora-gateway/*.json
   sudo systemctl restart synora-gateway
   ```

5. Verify: `systemctl is-active synora-gateway`, the health endpoint, the registry diff against the backup (only the
   `rajaneesh` module and branch lists should differ), the developer count (unchanged), and that `johan-admin` still
   authenticates.
6. Rollback: restore the backup, reapply the ownership and permission commands, and restart.

Nothing in this step changes a key, a role, a status, or any other developer's entry.

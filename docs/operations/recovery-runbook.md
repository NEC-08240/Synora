# Synora emergency recovery runbook

Use this when something is broken and you need the order of actions and a way to tell that it is fixed. For the facts
behind each step (paths, services, certificate, registry format, Worker task) read
[tools/pipeline/deploy/README.md](../../tools/pipeline/deploy/README.md). The architecture and trust boundaries are in
[docs/architecture/agent-bridge.md](../architecture/agent-bridge.md). Who may merge to `main` is in
[docs/github/pr-review-and-merge.md](../github/pr-review-and-merge.md).

## Rules that apply to every procedure

- **Never put a secret in a ticket, PR, log, or chat.** That includes the Gateway signing secret in `gateway.env`, every
  `*.key` file, the Worker key `worker-johan.key`, `gateway.key`, and any token. Check paths and names; do not print contents.
- **Stop before a destructive step** and confirm the backup exists first: deleting `gateway.db`, replacing registries,
  regenerating the signing secret or the certificate, clearing Lead state, or moving production to a new commit.
- **Do not weaken the trust model to get service back.** Do not disable certificate verification, do not open port 8000,
  do not put Claude credentials on the Gateway host, do not start a second Gateway process, and do not run the Worker as a
  system service.
- **Do not run a production experiment to find out whether something works.** Use the verification step of the matching
  procedure, which is read-only or a single smoke job.
- **Record every change** to production or the registry in the deploy README (Part A) with date, commit and reason.
- Status labels: **VERIFIED** = observed on the real system (date in the deploy README). **UNTESTED** = written from the
  documented procedure but never run here. Do not treat an UNTESTED step as proven.

## Current known-good state (2026-10-24)

| Layer | Known-good value | How to check |
|---|---|---|
| GitHub `main` | `0019eb5` (PR #23 merge). Runtime code is identical to `f371792` (PR #20 merge); the only later change is CODEOWNERS | `git ls-remote origin main` |
| EC2 Gateway checkout `/opt/synora` | `f371792` detached | `git -c safe.directory=/opt/synora -C /opt/synora rev-parse HEAD` (sudo) |
| Gateway service | `synora-gateway` active, `127.0.0.1:8000` only | `systemctl is-active synora-gateway`; `curl -s http://127.0.0.1:8000/health` |
| Caddy | active on `*:80`, `*:443`; certificate SHA-256 `35:C4:16:70:…:96:B1`, expires 2027-01-21 | `systemctl is-active caddy`; `openssl x509 -fingerprint -sha256` on `/etc/caddy/tls/gateway.crt` |
| Johan's Worker | Scheduled task `Synora Worker`, code at `Documents\Synora-worktrees\worker-runtime` on `f371792` | `Get-ScheduledTask 'Synora Worker'`; `git -C <worker-runtime> rev-parse --short HEAD` |
| Persistent Lead | `ACTIVE`, turn count and cost in `%USERPROFILE%\.synora\lead\lead_state.json` | Read the `state` field only; never print `session_id` |
| Ruleset | `Protect main` (id `23422368`), enforcement active | `gh api repos/NEC-08240/Synora/rulesets/23422368` |
| Bypass team | `mainline-owners` (id `20296003`), member `StevefromSpace` only | `gh api orgs/NEC-08240/teams/mainline-owners/members` |

Each check is read-only. If a value differs from the table, that is drift: find out why before changing anything.

---

## 1. Gateway unavailable (health check fails)

**Symptoms:** `https://<ELASTIC_IP>/health` times out or returns 502 through Caddy; Workers log connection errors.

**Diagnosis (in this order, stop at the first failure):**
1. Can you reach SSH? If not, check the Security Group rule for TCP 22 (it allows only the administrator's `/32`; deploy README Part A). HTTPS keeps working without SSH.
2. `sudo systemctl status synora-gateway caddy --no-pager`
3. `curl -s http://127.0.0.1:8000/health` on the host. Works = the problem is Caddy or the network, not the Gateway.
4. `sudo journalctl -u synora-gateway -n 80 --no-pager` (look for tracebacks; the audit log at `/var/log/synora-gateway/audit.log` has no secrets)

**Recovery:**
- Gateway process down: `sudo systemctl restart synora-gateway`. Queued jobs persist in `gateway.db`; the Worker reconnects.
- Gateway restarts repeatedly: do not edit code on the host. Confirm the checkout is the known-good commit (table above). If it is, check `gateway.env` and the registries exist and are readable by `synora-gateway` (names and permissions only). If they are missing, go to scenario 5.
- Caddy: go to scenario 4.

**Verification:**
- Host: `curl -s http://127.0.0.1:8000/health` returns `"status":"HEALTHY"`.
- From outside (laptop, with the pinned certificate): `curl --cacert <gateway.crt> https://<ELASTIC_IP>/health` returns 200.
- `curl -s https://<ELASTIC_IP>/worker/status` (no token) returns 401. This confirms authentication is still in place.
- `sudo ss -ltn | grep 8000` shows `127.0.0.1:8000` only.

**Escalation:** if the process fails to start with the known-good commit and config, stop and report the journal excerpt. Do not change code on the host.

**Status:** restart and reconnect **VERIFIED** (2026-10-23, Gateway restart with a live Worker). External health and port checks **VERIFIED** (2026-10-23, 2026-10-24).

## 2. Worker unavailable

**Symptoms:** `/worker/status` shows the Worker offline; `teammate_cli smoke` exits 3; no jobs are picked up.

**Diagnosis:**
1. Is the Worker process running? `Get-ScheduledTask 'Synora Worker' | Select State` and `Get-Process python | Where-Object {$_.CommandLine -match 'worker_daemon'}` (the command line may contain paths; do not paste it anywhere).
2. Read the last 30 lines of `%USERPROFILE%\.synora\logs\worker.log`. Look for `Starting Synora Worker daemon`, connection errors, `Worker daemon crashed`, or a base-commit refusal.
3. Remember: the Worker only runs while Johan is logged on. A Worker that is off because the PC is off or asleep is not a fault.

**Recovery:**
- Not running, and the task is enabled: wait up to one minute (the minute trigger restarts it), or `Start-ScheduledTask 'Synora Worker'`.
- Task disabled: `Enable-ScheduledTask 'Synora Worker'`.
- Crashes on start: check the env file has the expected names (deploy README Part C) and the key file exists. Do not regenerate the key to fix a crash.

**Verification:** the log shows a new `Starting Synora Worker daemon` line followed by a successful connection; `/worker/status` shows the Worker online with a recent heartbeat; a smoke job (scenario 8) succeeds.

**Escalation:** if the log shows repeated unexplained terminations, record the times. The deploy README (Part C, "Unexplained terminations") lists four earlier cases with no cause. Enable the Task Scheduler operational log as that section describes before the next occurrence.

**Status:** restart and one-minute recovery **VERIFIED** (2026-10-23). The cause of the earlier unexplained terminations is **NOT ESTABLISHED**.

## 3. Worker cannot reconnect (TLS or certificate failure)

**Symptoms:** the log shows certificate verification errors, or connection refused/timeouts that persist after the network is up.

**Diagnosis:**
1. Compare the certificate the Worker trusts with the host's. The Worker pins `%USERPROFILE%\.synora\gateway.crt` (`SYNORA_CA_CERT`). Compare the SHA-256 with the fingerprint in the deploy README through a second channel. Do not accept a certificate just because the Gateway sent it.
2. On the host: `sudo openssl x509 -in /etc/caddy/tls/gateway.crt -noout -fingerprint -sha256 -enddate`
3. Check the expiry date. The certificate expires **2027-01-21**; anything past that date is expected to fail.

**Recovery:**
- Pinned file is wrong or missing: obtain the current `gateway.crt` from the host through an authenticated SSH session (`sudo cat /etc/caddy/tls/gateway.crt`), confirm its fingerprint, and replace the local file. Never copy `gateway.key`.
- Certificate expired or regenerated: go to scenario 3b.
- Network down: wait. The Worker backs off up to 30 seconds and reconnects.

**Verification:** Worker log shows a successful connection; `/worker/status` online; a smoke job succeeds and its signature verifies.

**3b. Certificate regeneration (UNTESTED as a whole procedure on this host):** create a new certificate with `admin_cli gen-cert --host <ELASTIC_IP> --days 90` (deploy README Part B step 12), move it to `gateway.crt`/`gateway.key` with the documented ownership, `sudo systemctl reload caddy`, then give the new `gateway.crt` to Johan's Worker and every teammate. Old clients fail until updated. The certificate generation was run once (2026-10-23); the reload and client update were verified only for that run.

**Escalation:** a fingerprint mismatch that you cannot explain is a possible compromise. Stop, do not connect with the new certificate, and report to Johan.

**Status:** pinned-certificate connection and rejection of a wrong pin **VERIFIED** (2026-10-23). Certificate regeneration on a live host **UNTESTED** since the first issue.

## 4. Caddy or TLS failure

**Symptoms:** port 443 unreachable from outside while the host is healthy; TLS handshake alert "internal error"; HTTP 308 redirect missing.

**Diagnosis:**
1. `sudo systemctl status caddy --no-pager` and `sudo journalctl -u caddy -n 50 --no-pager`
2. `sudo caddy validate --config /etc/caddy/Caddyfile`
3. `sudo ss -ltnp | grep -E ':(80|443)\b'` must show Caddy.
4. Confirm the Caddyfile still has `default_sni <ELASTIC_IP>`. Without it every IP-based handshake fails (recorded in the deploy README).
5. From the host, `curl -sk --resolve <ELASTIC_IP>:443:127.0.0.1 https://<ELASTIC_IP>/health`. Works = Caddy is fine and the outside path is the problem (Security Group, network).
6. If external 443 times out while the host is healthy: this happened once before with no cause found (deploy README, Part A). Check the Security Group allows TCP 443 from `0.0.0.0/0`, then capture SYN packets on the instance as that section describes.

**Recovery:**
- Caddy stopped: `sudo systemctl start caddy`.
- Bad Caddyfile: restore the known-good copy (keep one next to the live file before every edit, and do not commit it), validate, then `sudo systemctl reload caddy`.
- Security Group wrong: restore TCP 80 and 443 from `0.0.0.0/0`, TCP 22 from the administrator's `/32`, and no 8000 (deploy README Part A).

**Verification:** step 5 succeeds; from outside, `curl --cacert <gateway.crt> https://<ELASTIC_IP>/health` returns 200; `http://<ELASTIC_IP>/` returns 308 to HTTPS; `/worker/status` without a token returns 401.

**Status:** Caddy config validation, `default_sni` requirement, 308 redirect, 413 on oversize body, and external 200 with pinned verification **VERIFIED** (2026-10-23). Caddy restart after a bad config **UNTESTED** on this host.

## 5. Gateway service failure: corrupt or missing registry, or config

**Symptoms:** the service fails to start, or starts and rejects every login.

**Diagnosis:** check that these exist and are readable by `synora-gateway` (names and modes only; do not `cat` them):
`/etc/synora-gateway/gateway.env`, `team.json`, `workers.json`. The service needs all three.

**Recovery:**
- Registry file missing or unreadable: restore it from the backup (below) with `root:synora-gateway` and mode `640`, then restart. A registry from the backup is the right source. An empty file lets the service start, but everyone must then be re-enrolled. Do that only with Johan's approval.
- Registry corrupt (invalid JSON): keep the broken file for diagnosis (rename it), restore the last good copy, and restart.
- `gateway.env` lost: the signing secret cannot be recreated without invalidating every session. Restore from the secure backup. If there is no backup, stop and escalate (see scenario 6).

**Backups:** `/var/backups/synora-gateway/` holds root-only snapshots of `gateway.db`. Registries have a `.pre-<label>` copy in `/etc/synora-gateway/` (for example `team.json.pre-rajaneesh-20261023T180938Z`). The secure off-host backup of `gateway.env`, the registries, `gateway.crt`, and `gateway.key` must be verified to exist before a risky change. **Whether that off-host copy exists is NOT VERIFIED by this runbook; the administrator must confirm it.**

**Verification:** service active; `/health` returns HEALTHY; a login for an enrolled developer succeeds in a test smoke job; an unenrolled identity is refused.

**Escalation:** any corrupt `gateway.db` with unexplained rows: stop. Keep the file and report. Do not delete it.

**Status:** registry restore and restart **UNTESTED**. Registry is read only at start (documented and observed).

## 6. Gateway replacement or EC2 rebuild

**Symptoms:** the instance is lost, unreachable, or must be rebuilt.

**Diagnosis:** confirm the instance is really gone (AWS console), and that the Elastic IP is still allocated. A new public IP means a new certificate and new `SYNORA_GATEWAY_URL` values everywhere, so it is a significant change.

**Recovery:** follow deploy README **Part B, "Rebuild from nothing"**, steps 1 to 17. Important points:
- Use the known-good commit (`f371792` or a later commit explicitly approved and recorded). Do not use an AMI or snapshot of the old host.
- Restore `gateway.env`, `team.json`, `workers.json`, and the certificate pair from the secure backup. Regenerate them only if no backup exists, and then accept that every session is invalidated and everyone is re-enrolled.
- Keep the Security Group rules exactly as listed in Part A.

**Verification:** Part B step 15 and 16 checks; the Worker reconnects (scenario 2); one smoke job succeeds.

**Escalation:** if the Elastic IP cannot be reattached, stop. The Worker and every teammate must be re-pointed, which needs Johan's decision.

**Status:** **UNTESTED end to end.** The install procedure was run once from a fresh host on 2026-10-23. A second, full rebuild has not been rehearsed.

## 7. Persistent Lead recovery

**Symptoms:** Lead turns refused; the Worker reports the Lead BROKEN, busy, or session mismatch; `lead_state.json` shows `CREATING`.

**Diagnosis:**
1. Read the `state` field of `%USERPROFILE%\.synora\lead\lead_state.json` only.
2. `ACTIVE` with a busy error: an attachment is open or a turn is stuck. Check for an open `lead_attach` terminal.
3. `BROKEN`: the stored session ID did not match what Claude returned. The state will not clear by itself. This is a security-relevant stop.
4. `CREATING`: a creation was interrupted. The Lead refuses to start until an administrator decides. Do not delete the file to retry; a retry could create a second session.
5. `SYNORA_LEAD_SESSION_ID` in `worker.env` differs from the stored session: fail closed. Do not set it to match by copying a value from anywhere but the state file.

**Recovery:**
- Busy: close the attachment (`/exit`), then retry. The OS releases the lock if the holder died.
- BROKEN or CREATING: keep the state file and the turn log (`lead_turns.jsonl`) for diagnosis. Stop the Worker task (`Disable-ScheduledTask` then `Stop-ScheduledTask`). Decide with Johan whether to start a new session, which is a new Lead identity with no history. Clearing the state is a manual, reviewed act, not a routine step.
- Do not run a bare `claude --resume` against the Lead session. Use `python -m tools.pipeline.lead_attach`.

**Verification:** `state` is `ACTIVE`, a short Lead request returns a `DECISION:` line, and the turn count increases by one.

**Escalation:** any BROKEN state, or a session ID you did not expect. Report it to Johan; do not attempt a repair.

**Known limits:** the shared-conversation risk is open. Multi-teammate Lead use is not approved (agent-bridge.md, Persistent Engineering Lead). Recovery is **UNTESTED** for BROKEN and CREATING, since neither has occurred.

## 8. Smoke test (use after any recovery)

From a checkout of `main`, with the Worker running and the caller's own key file (never print the key):

```text
python -m tools.pipeline.teammate_cli smoke
```

Exit code 0 = all steps PASS (Gateway sign-in, Worker online, job accepted, finished, signature verified, result returned).
Non-zero codes: 3 Worker offline, 4 rejected, 5 timeout, 6 job failed, 7 Worker signature did not verify. Treat exit 7 as a
security stop, not a retry. The smoke job consumes Johan's Claude budget (10 jobs an hour, 50 a day by default), so run it
once per recovery, not in a loop.

## 9. GitHub authentication failure

**Symptoms:** `gh` reports not logged in or missing scope; a merge or API call returns 401/403.

**Diagnosis:** `gh auth status` (shows the account and scopes, not the token).

**Recovery:**
- Expired login: `gh auth login`, or refresh the required scope with `gh auth refresh -h github.com -s admin:org` (device flow in the browser). Request only the scope you need.
- The AI sessions use Johan's GitHub credentials. There is no separate AI account (a documented limit). Do not create a token and paste it into a file or chat.
- Never store a token in the repository or in `worker.env`.

**Verification:** `gh api user --jq .login` returns the expected login.

**Escalation:** if an action happens under an account you did not expect, stop and report it to Johan. Rotate the token in GitHub settings.

**Status:** refresh flow **VERIFIED** (2026-10-24, device-flow browser approval for `admin:org`).

## 10. Team enrollment recovery

**Symptoms:** a developer or Worker is refused, or a new teammate cannot sign in.

**Diagnosis:** read the entry in `team.json` or `workers.json` by name and status only. Confirm the public key matches the one the person generated. Public keys are not secrets, but never accept a key from the Gateway or from a chat message without Johan's confirmation.

**Recovery:**
- Add or update: `admin_cli add-developer` or `add-worker` (see deploy README step 5 for flags), then restart the Gateway. Registries are read only at start.
- Suspend, do not delete, when access must stop: set `status` to `suspended`, restart, and verify.
- Never give a developer more module or branch scope than the task needs. For the Engineering Manager scope, see the open PR #22 (not merged on `main`).

**Verification:** the person's login succeeds (smoke test by that person), and a suspended entry is refused.

**Escalation:** any request to widen scope or add a bypass actor needs Johan's explicit approval.

**Status:** enrollment and restart **VERIFIED** (2026-10-23). Rajaneesh's own machine checks were not run by this runbook and are not verified here. Suspension path **UNTESTED**.

## 11. GitHub ruleset or CODEOWNERS recovery

**Symptoms:** the ruleset is missing, disabled, or edited; `main` accepts a direct push; CODEOWNERS was changed.

**Diagnosis:**
```text
gh api repos/NEC-08240/Synora/rulesets/23422368 --jq '{enforcement, bypass_actors, rules: [.rules[].type]}'
gh api orgs/NEC-08240/teams/mainline-owners/members --jq '[.[].login]'
gh api repos/NEC-08240/Synora/contents/.github/CODEOWNERS?ref=main --jq .content | base64 -d
```
Expected: enforcement `active`; bypass actor is only the team `20296003`; members are `StevefromSpace`; CODEOWNERS is `* @StevefromSpace`.

**Recovery:**
- Ruleset weakened or edited: restore the expected settings through the GitHub UI or `gh api -X PUT` with the same settings. Settings: deletion blocked, non-fast-forward (force push) blocked, pull request required with one approval, code-owner review required, bypass only for the `mainline-owners` team. Export the current ruleset JSON before changing it so the diff is visible. Export contains no secrets.
- CODEOWNERS changed: restore the file through a PR that Johan approves. Do not push it directly.
- Team membership changed: restore membership through the org settings, and record the change.
- Do not relax protection to get a PR merged.

**Verification:** the diagnosis commands return the expected values; a probe PR shows `REVIEW_REQUIRED` and `BLOCKED` before approval, then close it unmerged.

**Escalation:** repository admins (Rajaneesh is one) can edit the ruleset on the free plan. This is an accepted limit. Any unexplained change is reported to Johan and investigated.

**Status:** configuration and effective state **VERIFIED** (2026-10-24). Restoration from a broken state **UNTESTED**.

## 12. Repository or production rollback

**Symptoms:** a bad commit reached `main` or the production checkout and breaks behaviour.

**Diagnosis:** identify the last known-good commit from the table at the top, then the diff: `git diff <good> <bad> --stat`.

**Recovery:**
- Do not force-push `main` (prohibited by the ruleset). Revert with a new PR: `git revert <bad>` on a branch, PR, and merge.
- Production: on the host, move the checkout to the known-good commit (`sudo git fetch && sudo git -c safe.directory=/opt/synora -C /opt/synora checkout <good>`). Record the change in deploy README Part A.
- Restart only if the runtime code changed. Commit changes limited to docs or CODEOWNERS do not need a Gateway restart; confirm with `git diff <old> <new> -- tools/`, which must be empty for a restart-free move.
- Worker: move `worker-runtime` with `git -C <worker-runtime> checkout --detach <good>` then `Stop-ScheduledTask` (after `Disable-ScheduledTask`, re-enable afterwards).

**Verification:** health check, a smoke job, and the commit shown in the table.

**Escalation:** a rollback that needs a registry or database change is a migration. Stop and get approval.

**Status:** the production checkout move with no runtime diff **VERIFIED** (2026-10-23, `9e6d6b3` to `f371792`, no code change to tools). Revert-based rollback of a bad merge **UNTESTED**.

---

## Destructive operations (listed once)

| Operation | Why it is destructive | Required before |
|---|---|---|
| `rm` or overwrite of `gateway.db` | Loses the job queue and history | A copy in `/var/backups/synora-gateway/`, owned by root |
| Replacing `team.json` or `workers.json` with an empty file | Everyone is re-enrolled | Johan's approval and a backup |
| Regenerating `gateway.env` secret | Invalidates all session tokens | Johan's approval; clients sign in again |
| Regenerating `gateway.crt`/`gateway.key` | Clients pinning the old certificate fail | Distribution of the new certificate to Johan and teammates |
| Clearing `lead_state.json` | Can create a second Lead session | Johan's decision; keep the file for diagnosis |
| Force-push to `main` | Prohibited by the ruleset | Not permitted |
| Editing the ruleset or bypass team | Changes who can merge | Johan's approval, export first |
| Restarting the Gateway with more than one process | Breaks in-memory challenges | Not permitted |

## Open items

- The off-host backup of `gateway.env`, registries, and certificate pair is not verified by this runbook. The administrator must confirm it exists and is readable.
- The Worker's last scheduled-task result (`0x800710E0`) was not diagnosed. Check the task history before relying on the Worker through a restart.
- Lead BROKEN and CREATING recovery, registry restore, Caddy restart after a bad config, and a full EC2 rebuild are **UNTESTED**. Rehearse them on a throwaway host, not production, before a real incident.

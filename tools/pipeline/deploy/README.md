# Synora Agent Gateway: deployment

This file has two parts. **Part A** records the deployment that actually exists. **Part B** is the disaster-recovery
procedure and the list of things not to do. After them comes the generic install procedure the deployment was built
from. Values marked *(administrator-stated)* were supplied by the administrator rather than read from the host. No
secret value appears in this file and none may be added to it.

The Gateway is a control plane: it authenticates teammates, queues jobs and relays signed results. It never holds
Claude credentials and never runs agents. Johan's Worker connects **out** to it over `wss://`.

---

# Part A: the current deployment (as built, 2026-10-23)

## Revision
| Item | Value |
|---|---|
| Repository | https://github.com/NEC-08240/Synora.git |
| Branch | `chore/agent-bridge-poc` |
| **Deployed application commit** | **`9e6d6b3`** (checked out detached at `/opt/synora`) |
| Deployment directory | `/opt/synora` (owned by root) |
| Virtualenv | `/opt/synora/.venv` (Python 3.12.3) |

`9e6d6b3` is the deployed application revision (the Gateway). The Worker and client code on Johan's PC are newer commits
of the same branch and are not deployed to AWS; see Part C. Commits made to the branch later, including documentation-only
commits such as the one that last edited this file, do **not** change what runs on the host. The host changes only
when someone explicitly runs `git fetch && git checkout <commit>` in `/opt/synora` and restarts the service, and that
change must be recorded here.

## AWS infrastructure
| Item | Value |
|---|---|
| Region | Singapore, `ap-southeast-1` *(administrator-stated)* |
| Instance type | `t4g.small` *(administrator-stated)* |
| OS | Ubuntu 24.04.5 LTS, aarch64 (read from the host) |
| Python | 3.12.3 (system `python3`) |
| Elastic IP | `13.228.104.217` (the instance metadata service reports the same public IPv4) |
| Attached Security Group | `sg-0e9e8622e87721c46` (group ID read from the instance metadata service) |

### Security Group `sg-0e9e8622e87721c46`: inbound (verified by the administrator in the AWS console)
| Protocol / port | Source | Purpose |
|---|---|---|
| TCP 22 | `106.216.234.211/32` | SSH, administrator only |
| TCP 80 | `0.0.0.0/0` | Caddy redirect to HTTPS |
| TCP 443 | `0.0.0.0/0` | Caddy, public HTTPS |
| (none) | | **No inbound TCP 8000 rule** |

- SSH is restricted on purpose to the administrator's current public IP. **When that IP changes, update the rule**
  or SSH access is lost. Never widen it to `0.0.0.0/0`.
- The Gateway listens only on `127.0.0.1:8000` and is reachable from outside only through Caddy on 443.
- The host firewall is not the perimeter: `ufw` is inactive and `iptables` policies are ACCEPT. **The Security Group
  is the only network perimeter.**

## Services
| Service | State | Runs as | Notes |
|---|---|---|---|
| `synora-gateway` | enabled, active | system user `synora-gateway` (no login shell, home `/opt/synora`) | `/etc/systemd/system/synora-gateway.service`, copied from `tools/pipeline/deploy/` |
| `caddy` | enabled, active | package default user `caddy` | Ubuntu `caddy` package 2.6.2; config `/etc/caddy/Caddyfile` |

```
systemctl status synora-gateway caddy                 # state
sudo journalctl -u synora-gateway -n 50 --no-pager    # Gateway log
sudo journalctl -u caddy -n 50 --no-pager             # Caddy log
sudo systemctl restart synora-gateway                 # needed after any enrolment or env change
sudo systemctl reload caddy                           # apply a Caddyfile change without dropping connections
sudo systemctl stop synora-gateway                    # safe stop: queued jobs persist in gateway.db; the Worker reconnects when it returns
sudo systemctl stop caddy                             # takes the public endpoint offline; the Gateway keeps running privately
```
Run the Gateway as a **single process**: challenges and worker tokens live in memory.

## Paths
| Path | Contents | Owner:group, mode |
|---|---|---|
| `/opt/synora` | repository checkout and `.venv` | root |
| `/etc/synora-gateway/` | Gateway configuration directory | root:synora-gateway, 750 |
| `/etc/synora-gateway/gateway.env` | systemd `EnvironmentFile`, **contains the signing secret** | root:synora-gateway, 640 |
| `/etc/synora-gateway/team.json` | developer registry (public keys, roles, module and branch scopes) | root:synora-gateway, 640 |
| `/etc/synora-gateway/workers.json` | Worker registry (public keys) | root:synora-gateway, 640 |
| `/var/lib/synora-gateway/gateway.db` | SQLite job queue and Worker heartbeats | synora-gateway |
| `/var/log/synora-gateway/audit.log` | Gateway audit log | synora-gateway |
| `/etc/caddy/Caddyfile` | Caddy configuration | root |
| `/etc/caddy/tls/gateway.crt` | self-signed public certificate | root:caddy, 644 |
| `/etc/caddy/tls/gateway.key` | **certificate private key** | root:caddy, 640 |

`/etc/caddy/tls` is root:caddy 750, so reading the certificate from it needs `sudo`.

## Gateway configuration
`/etc/synora-gateway/gateway.env` was created from `tools/pipeline/deploy/gateway.env.example`: host `127.0.0.1`,
port `8000`, absolute registry, database and audit paths as in the table above, recovery interval 30 seconds.

- **Signing secret:** generated on the host with `openssl rand -base64 48` and substituted into `gateway.env`. It was
  never displayed, copied elsewhere or committed. It exists only in that file (root:synora-gateway, 640). The Gateway
  refuses secrets shorter than 32 bytes.
- **Registries:** `team.json` and `workers.json` were **created empty** at deployment because the service will not
  start without the files. Enrolment (`admin_cli add-developer`, `add-worker`) adds entries.
- **Registries are read only at start.** Restart `synora-gateway` after every enrolment or configuration change.

## Caddy / TLS (IP-only, self-signed)
The instance has no DNS name, so Caddy serves a self-signed certificate for the Elastic IP.
- Caddy listens on 80 and 443 (and UDP 443 for HTTP/3). HTTP on 80 redirects to HTTPS (308). The Caddy admin API is
  on `127.0.0.1:2019` only.
- Caddy reverse-proxies to `127.0.0.1:8000` and limits request bodies to 2 MB (`request_body max_size`).
- Certificate: CN and SAN `13.228.104.217`, created with `admin_cli gen-cert --host 13.228.104.217 --days 90`
  (the files came out as `test_server.crt/.key` and were renamed to `gateway.crt/.key`), valid until **2027-01-21**.
- **SHA-256 fingerprint:** `35c4167013e381872e132c2d18a1762eed9577e8063e168a89764630802c96b1`.
- **Renewal:** the certificate expires after 90 days. Before 2027-01-21 regenerate it (Part B step 12), reload Caddy
  and give the new `gateway.crt` to the Worker and teammates. Clients pinning the old file fail until updated.

The Caddyfile in use is `Caddyfile.ip-selfsigned` with the address filled in **and a global option the template
originally lacked**:
```
{
	default_sni 13.228.104.217
}

https://13.228.104.217 {
	tls /etc/caddy/tls/gateway.crt /etc/caddy/tls/gateway.key
	request_body {
		max_size 2MB
	}
	reverse_proxy 127.0.0.1:8000
}
```
**`default_sni` is required for an IP-only site.** Clients connecting to an IP send no SNI, and behind the AWS public
address Caddy cannot match the site by local address. Without it every handshake ended in a TLS "internal error"
alert (observed with `curl -v`). `Caddyfile.ip-selfsigned` in the repository now includes it.

**Clients obtain the trust anchor** by copying `gateway.crt` from the host (`sudo cat /etc/caddy/tls/gateway.crt`),
comparing its SHA-256 with the fingerprint above through a second channel, and setting `SYNORA_CA_CERT` to the file.
The certificate is public. Never distribute `gateway.key`.

## Dependencies actually installed
```
sudo apt-get update && sudo apt-get install -y python3-venv git caddy
sudo useradd --system --home /opt/synora --shell /usr/sbin/nologin synora-gateway
sudo git clone --branch chore/agent-bridge-poc https://github.com/NEC-08240/Synora.git /opt/synora
cd /opt/synora && sudo git checkout 9e6d6b3
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r tools/pipeline/requirements-gateway.txt -r tools/pipeline/requirements-client.txt
```
Resolved versions on the host included: starlette 1.9.0, uvicorn 0.54.0, wsproto 1.3.2, cryptography 50.0.2,
httpx 0.28.1, mcp 2.3.0. The deployment venv deliberately does **not** contain `websocket-client` (a Worker dependency).

## Host test result at deployment
- **Gateway-relevant modules:** 222 of 223 tests pass: `test_gateway_api`, `test_gateway_auth`,
  `test_gateway_authorization`, `test_gateway_concurrency`, `test_gateway_compromise_validation`,
  `test_public_gateway_review`, `test_remote_protocol`, `test_result_signing`, `test_lan_mode`, `test_step3`,
  `test_admin_tools`, `test_remediation_transport`, `test_deployment_fixes`, `test_red_team_audit`, `test_storage`.
  The one failure, `test_critical_3_relative_path_traversal_blocked`, tests the Worker-side `Bridge.create` with a
  Windows backslash path.
- **Full suite (362 tests, including Worker modules):** 3 failures and 3 errors, all Worker-side portability or
  environment limits, accepted by the administrator and left unchanged: three `test_remediation_env` tests write a
  `fake_claude.bat` stand-in that Linux will not execute; two `test_server` tests need a real `claude` binary on
  `PATH`; and `test_critical_3` above. In the deployment venv `test_review_regressions` cannot import `websocket`
  (it needs the Worker requirements).

## Verification record (2026-10-23)
- Local: `http://127.0.0.1:8000/health` returned HTTP 200 through the service.
- Listeners: the Gateway (`python`, user `synora-gateway`) only on `127.0.0.1:8000` with no other sockets; Caddy on
  `*:80`, `*:443`, UDP 443 and `127.0.0.1:2019`; also SSH (22) and the system resolver on loopback.
- External, from the administrator's laptop (egress `106.216.234.211`) and an independent public port-checker:
  - TCP 443 reachable (the port-checker's SYN was also seen on the instance's network interface);
  - `https://13.228.104.217/health` returned HTTP 200 `{"status":"HEALTHY","service":"Synora Agent Gateway",...}`;
  - verification against the pinned `gateway.crt` succeeded, and fails without the pin;
  - `/worker/status` without authentication returned 401;
  - TCP 8000 unreachable from outside;
  - `http://13.228.104.217/` returned 308 to `https://13.228.104.217/`;
  - a 3 MB request body through Caddy returned 413.

### An earlier transient connectivity failure (root cause not established)
The first external probes from the laptop to ports 80 and 443 failed while SSH on 22 worked. A `tcpdump` on the
instance's network interface at that moment showed **no inbound SYN packets** for 80, 443 or 8000. A later `tcpdump`
showed the SYN from an independent public port-checker arriving, and the laptop then connected and completed HTTPS
verification. No AWS, host, Caddy or Gateway configuration was changed in between. **The cause was not determined**
and nothing is claimed about it. If external 443 fails again, repeat the instance-side capture
(`sudo tcpdump -ni ens5 'tcp[tcpflags] & tcp-syn != 0 and dst port 443'`) while probing, and test from a second network.

---

# Part B: disaster recovery

## Rebuild from nothing
Items marked **[BACKUP]** must be restored from a secure backup; items marked **[REGENERATE]** can be recreated.

1. **Provision** a fresh Ubuntu 24.04 ARM64 instance (`t4g.small` or larger) in `ap-southeast-1`. Do not use an AMI or snapshot of the old host.
2. **Elastic IP:** associate `13.228.104.217` with the new instance (disassociate it from the old one first). A different IP means a new certificate (step 12) and new `SYNORA_GATEWAY_URL` values everywhere.
3. **Security Group:** attach a group with exactly TCP 22 from the administrator's current `/32`, TCP 80 and 443 from `0.0.0.0/0`, and **no 8000**. Reuse `sg-0e9e8622e87721c46` if it still exists.
4. **Prerequisites:** `sudo apt-get install -y python3-venv git caddy`.
5. **Users and directories:**
   ```
   sudo useradd --system --home /opt/synora --shell /usr/sbin/nologin synora-gateway
   sudo install -d -m 750 -o root -g synora-gateway /etc/synora-gateway
   sudo install -d -m 750 -o synora-gateway -g synora-gateway /var/lib/synora-gateway /var/log/synora-gateway
   ```
6. **Clone:** `sudo git clone --branch chore/agent-bridge-poc https://github.com/NEC-08240/Synora.git /opt/synora`
7. **Checkout** the intended revision explicitly (`9e6d6b3` unless a newer one was approved and recorded here): `cd /opt/synora && sudo git checkout <commit>`.
8. **Virtualenv:** `sudo python3 -m venv .venv`.
9. **Dependencies:** `sudo .venv/bin/pip install -r tools/pipeline/requirements-gateway.txt -r tools/pipeline/requirements-client.txt`. Run the Gateway-relevant tests listed in Part A and stop on any Gateway-module failure.
10. **Gateway configuration:** copy `tools/pipeline/deploy/gateway.env.example` to `/etc/synora-gateway/gateway.env` (root:synora-gateway, 640).
11. **Signing secret [REGENERATE, or BACKUP]:** a fresh `openssl rand -base64 48` works, but it invalidates every issued session token, so clients must sign in again. Restore the old value only from a secure backup, never from this repository.
12. **Caddy and TLS [REGENERATE, or BACKUP the old key and certificate]:**
    ```
    sudo install -d -m 750 -o root -g caddy /etc/caddy/tls
    cd /opt/synora && sudo .venv/bin/python -m tools.pipeline.admin_cli gen-cert --out-dir /etc/caddy/tls --host <ELASTIC_IP> --days 90
    sudo mv /etc/caddy/tls/test_server.crt /etc/caddy/tls/gateway.crt && sudo mv /etc/caddy/tls/test_server.key /etc/caddy/tls/gateway.key
    sudo chown root:caddy /etc/caddy/tls/gateway.* && sudo chmod 644 /etc/caddy/tls/gateway.crt && sudo chmod 640 /etc/caddy/tls/gateway.key
    ```
    Install the Caddyfile from `Caddyfile.ip-selfsigned` with the IP substituted (it includes `default_sni`), then
    `sudo caddy validate --config /etc/caddy/Caddyfile`. A regenerated certificate has a new fingerprint: update Part A
    and give the new `gateway.crt` to the Worker and every teammate.
13. **Registries [BACKUP]:** restore `team.json` and `workers.json` (root:synora-gateway, 640). Without a backup, create them empty (the Gateway will not start without the files) and re-enrol everyone in step 17. **[BACKUP, optional]** `gateway.db` and `audit.log` hold job history and the audit trail; a fresh start loses only that history.
14. **Start:** `sudo cp tools/pipeline/deploy/synora-gateway.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now synora-gateway && sudo systemctl reload caddy`.
15. **Local health:** `curl -s http://127.0.0.1:8000/health`, and `sudo ss -ltnp | grep 8000` must show `127.0.0.1:8000` only.
16. **External HTTPS** from another machine: `curl --cacert gateway.crt https://<ELASTIC_IP>/health` must return 200 with certificate verification enabled; `/worker/status` without a token must return 401; port 8000 must be unreachable.
17. **Worker and teammates:** restore or re-enrol their public keys with `admin_cli add-worker` / `add-developer` (steps 5, 8 and 9 below), restart the Gateway, and re-test. Private keys never leave the machines that generated them.

**Back up:** `gateway.env` (contains the secret), `team.json`, `workers.json`, `gateway.crt` and `gateway.key`, and optionally
`gateway.db` and `audit.log`. Store them encrypted and outside this repository.

## Things NOT to do
- Never expose port 8000. It has no TLS and must stay bound to `127.0.0.1`.
- Never commit secrets: the signing secret, `*.key`, `*.pem`, `*.db`, `gateway.env`.
- Never put Claude credentials on the Gateway host. The Worker is the execution boundary.
- Never disable TLS certificate verification, in curl (`-k`), in `SYNORA_CA_CERT` handling or in code.
- Never open SSH to `0.0.0.0/0`. Keep it to the administrator's `/32` and update it when that IP changes.
- Never modify the deployed application on the host without recording the change (commit, date, reason) in Part A.
- Never run more than one Gateway process.

---

# Part C: Johan's Worker on Windows (as built, 2026-10-23)

The Gateway in Part A is unchanged and still runs commit `9e6d6b3`. Everything in this part runs on Johan's PC and
works against that Gateway. "Verified" means observed by running it; limitations are listed separately and are not
claimed to work.

## What runs and where
| Item | Value |
|---|---|
| Mechanism | Windows Scheduled Task `Synora Worker`, per user (`Interactive`, no stored password) |
| Process | `python.exe -B -u -m tools.pipeline.worker_daemon --env-file %USERPROFILE%\.synora\worker.env`, started by the Task Scheduler service itself (its parent is a `svchost.exe`), so it does not depend on any Claude Code or terminal session |
| Code it runs | A dedicated, detached checkout: `C:\Users\Johan Joseph\Documents\Synora-worktrees\worker-runtime`, pinned to one commit. It is also the repository the Worker creates job worktrees in. Do not run it from a checkout you are editing |
| Settings | `%USERPROFILE%\.synora\worker.env` (names and paths only; template: `tools/pipeline/deploy/windows/worker.env.example`) |
| Secrets | `%USERPROFILE%\.synora\keys\worker-johan.key` (raw Ed25519 private key, never in the env file, never committed) |
| Trust anchor | `%USERPROFILE%\.synora\gateway.crt` (public; SHA-256 `35c41670…2c96b1`, see Part A) |
| Log | `%USERPROFILE%\.synora\logs\worker.log`: timestamped, rotated at 5 MB, 3 backups |
| Network | One outbound `wss://13.228.104.217:443` connection; no listening socket |

Why a Scheduled Task and not a Windows service: Claude Code's login lives in the user profile, and a service would
need a stored password or a different account that has no Claude login. No new dependency (NSSM, WinSW, pywin32) is
needed. Why not a plain startup shortcut: it would not restart a dead Worker.

## Install, update, stop, remove
```
# one time: copy tools\pipeline\deploy\windows\worker.env.example to %USERPROFILE%\.synora\worker.env and edit it
powershell -NoProfile -ExecutionPolicy Bypass -File tools\pipeline\deploy\windows\install-worker-task.ps1 -Start

# update the Worker's code: move the pinned checkout, then restart the task
git -C <worker-runtime> checkout --detach <commit>
Stop-ScheduledTask 'Synora Worker'     # the one-minute check below starts it again with the new code

# look at it
Get-ScheduledTask 'Synora Worker' | Select State
Get-Content $env:USERPROFILE\.synora\logs\worker.log -Tail 30 -Wait

# stop it properly (Stop alone is undone within a minute, see below)
Disable-ScheduledTask 'Synora Worker'; Stop-ScheduledTask 'Synora Worker'
Enable-ScheduledTask  'Synora Worker'      # to resume

# remove it (keeps %USERPROFILE%\.synora)
powershell -NoProfile -ExecutionPolicy Bypass -File tools\pipeline\deploy\windows\uninstall-worker-task.ps1
```
The task has two triggers: at logon, and every minute. A start is ignored while an instance is running
(`MultipleInstances IgnoreNew`), so the minute trigger only acts when the Worker is not running. Task Scheduler's
built-in "restart on failure" was tried first and does **not** fire when the process is killed (the task just returns to
Ready), so it is not used.

## Verified behaviour
- **Starts by itself:** after registration, without `-Start`, the daemon was started by the one-minute trigger.
- **Survives a hard kill:** `Stop-Process -Force` on the daemon; a new daemon was running 53 s later.
- **Stops cleanly:** after `Disable-ScheduledTask` + `Stop-ScheduledTask` no daemon process remained and none appeared
  in the following 75 s; `Enable-ScheduledTask` brought it back on its own. (An earlier PowerShell-wrapper design left the
  daemon running after `Stop-ScheduledTask`; that design was replaced.)
- **Outbound only:** the daemon owned 0 listening TCP sockets and one established connection to `13.228.104.217:443`.
- **Pinned certificate and authentication preserved:** it connects only with `SYNORA_CA_CERT` and signs the Gateway's
  challenge with its key. A Worker pinned to a different certificate never registered and kept retrying (loopback harness).
- **Reconnects after a Gateway restart:** a real Gateway process was killed and restarted; the Worker re-registered
  and the next job succeeded (loopback harness, which runs real processes over TLS).
- **Reconnects through network trouble:** during testing the laptop's connection to AWS dropped and timed out several
  times (its public IP also alternated between two addresses). The Worker logged each failure, backed off
  (0.1 s doubling to 30 s) and reconnected without intervention.
- **Long jobs:** see the next section.

## Fixed in this work: long jobs lost their result
The Gateway's WebSocket server (uvicorn) pings every 20 s and closes a connection that does not answer within 20 s.
The Worker answered pings only while it was reading, and it did not read while Claude ran, so any job longer than about
40 s lost its connection: the job finished on the Worker, the result was never delivered and the job stayed `RUNNING`
on the Gateway. This was seen on the deployed Gateway (disconnect exactly 60 s after connecting, 27 s into a job).
The Worker now runs the job in a thread while the main thread keeps reading the socket, and keeps a signed result that
the Gateway did not acknowledge so it can send it again after reconnecting. Verified: a 50 s job on the deployed Gateway
delivered its result and verified; `test_worker_long_jobs` reproduces both failures against a real TLS Gateway with a 1 s
keepalive. No Gateway change is needed.

## `base_commit`
Before: the Gateway checked only the *format* of `base_commit` and passed it on. The Worker never read it and always
started the job worktree at its repository's current `HEAD`, whatever the client sent; the result's `base_commit`
field held the Worker's HEAD. A client therefore believed its job was based on one commit while it was based on another.

Now (Worker-side, in `bridge.py`): the value must be 7 to 40 hex characters (the Gateway's own pattern also admits
`-` and `/`, which git could read as an option or a ref, so the Worker does not rely on it). The Worker resolves it
in its own repository, requires it to be in the history of its current `HEAD` (a job cannot reach other branches), and
starts the worktree at exactly that commit. Anything else is refused before any worktree exists, with
`Refused: base_commit is not a commit in the Worker repository's current history.` Review jobs still start from the
reviewed job's base. An absent `base_commit` still means `HEAD`.
Consequences: the commit must exist in the Worker's checkout (pushed and fetched there); `teammate_cli` now defaults to
the HEAD of the caller's own checkout instead of the old placeholder `abc1234`. Verified on the deployed Gateway: an
unknown commit was refused by the Worker, and a job based on older commit `9e6d6b3` (Worker HEAD was newer) succeeded
with that commit recorded as its base.

## Result signatures (client side)
The Worker signs every successful result with its key. The deployed Gateway verifies that signature (the
`JOB_RESULT_VERIFIED` audit event) but stores only the signed `result` and discards the signature, so clients could not
check anything. Rather than change the Gateway, the Worker now also embeds a second, small signed envelope
(`result.attestation`) over the SHA-256 of the result. A client holding the Worker's public key checks that signature,
that it names the job and developer it asked about, and that the returned content hashes to what was signed.
- **Get the Worker's public key from Johan, not from the Gateway** (`worker-johan.pub`; public). A key taken from the
  Gateway would let a compromised Gateway vouch for itself.
- `teammate_cli smoke` and `teammate_cli result` require `SYNORA_WORKER_PUBLIC_KEY` (a `.pub` file or the base64 text) and
  fail with exit code 7 if the signature does not verify. The MCP `get_result` tool verifies when the variable is set.
- Use the verified result that `get_verified_result` returns. Outside `result`, the Gateway merges the result over its
  own job record (for example the returned `job_id` is the Worker's local ID), and a compromised Gateway can change
  those top-level fields.
- Verified: valid results verify; a changed field, a different key, another job ID or developer, a missing attestation
  and an attestation copied onto different content are all rejected (`test_base_commit_and_attestation` and the live checks below).

## Live checks against the deployed Gateway (2026-10-23, Gateway `9e6d6b3`, Worker from the pinned checkout)
All 12 passed:
- unauthenticated `/worker/status` refused (401); forged login signature refused (401); unenrolled developer refused;
- a client without the pinned certificate cannot connect; a client pinned to a different certificate cannot connect;
- a branch outside the developer's scope (`main`) refused; a malformed job (wrong types) refused with 400;
- unknown `base_commit` (`abc1234`): accepted by the Gateway, refused by the Worker (`Refused: base_commit is not a commit...`);
- real older commit `9e6d6b3` (Worker HEAD `1402adf`): job succeeded, signature verified, result records `9e6d6b3bcc7b` as its base;
- a tampered result and a result checked against another key were both rejected by the client.
Also on the deployed Gateway: `teammate_cli smoke` passed with the signature step, and a requeued job that ran 50 s
(longer than the old 40 s limit) delivered a result that verified.

## Known limitations
- **Runs only while Johan is logged in (by design).** The task is per-user and `Interactive` so that Claude Code uses
  Johan's own login and no password is stored. Before logon, after logoff, and while the PC is off or asleep, no jobs are
  processed and queued jobs wait. Do not "fix" this by running the Worker as a system service: it would need credentials
  the Worker should not hold.
- **Crash recovery takes up to about a minute.** The one-minute trigger is the restart mechanism (53 s measured).
- **`Stop-ScheduledTask` alone is not a stop** (the minute trigger restarts it); use `Disable-ScheduledTask` first.
- **Logon and reboot: see "Lifecycle verification" below** for exactly what was and was not exercised.
- **`base_commit` must exist in the Worker's checkout.** The Worker accepts only a commit that is in the history of the
  commit its `worker-runtime` checkout is on. A teammate's commit must be pushed to GitHub and fetched into that
  checkout (`git -C <worker-runtime> fetch origin`) before it can be a base, and the checkout must be at or after it;
  otherwise the Worker refuses the job. Moving the checkout to a different commit changes which bases are accepted.
- **The Gateway's top-level job record is not authoritative.** It merges the Worker's result over its own fields (the
  returned `job_id` is the Worker's local ID) and a compromised Gateway can change them. Read results through
  `get_verified_result` / `teammate_cli result` / MCP `get_result` with `SYNORA_WORKER_PUBLIC_KEY` set.
- **AWS SSH access depends on Johan's public IP.** The Security Group allows SSH only from one `/32`, and the IP changed
  at least twice during this work. When it changes, SSH to the host fails until the rule is updated. HTTPS (443) is
  unaffected, so the Gateway and Worker keep working; only administration is blocked.
- **A forced stop mid-job** can orphan a Claude process. If the Worker stays away for more than 60 s the Gateway puts its
  unfinished jobs back in the queue and the Worker runs them again from the start (observed: the job stranded by the
  keepalive bug was requeued when the Worker was stopped for over a minute, re-run, and succeeded). If the Worker is
  back in under 60 s the Gateway does not requeue, and a job whose result was lost stays `RUNNING` until its 24 h
  expiry unless the Worker still holds that result for redelivery.
- **Only successful results are signed and stored.** A job that fails stores only its error text, which is not
  verifiable. Treat failure messages as informational.
- **A result must be redelivered within the Gateway's 300 s freshness window** or the Gateway rejects it (logged by the Worker).
- **The Gateway still allows each developer one active job**; a stranded job blocks that developer until it finishes or expires.
- The Gateway's result endpoint is unchanged: it still merges `result` fields into the job record.

---

# Generic install procedure

The numbered steps below are the original install steps. Part A records what was actually done.

## 0. AWS (console)
Security group inbound: 443/tcp from anywhere; 80/tcp only if using the domain variant; 22/tcp from your IP only.
Do not open 8000. Nothing else is needed inbound.

## 1. Packages and code
    sudo apt update && sudo apt install -y python3-venv git caddy
    sudo useradd --system --home /opt/synora --shell /usr/sbin/nologin synora-gateway
    sudo git clone --branch chore/agent-bridge-poc https://github.com/NEC-08240/Synora.git /opt/synora
    cd /opt/synora && sudo git checkout <DEPLOY_COMMIT>
    sudo python3 -m venv .venv && sudo .venv/bin/pip install -r tools/pipeline/requirements-gateway.txt

## 2. Directories
    sudo install -d -m 750 -o root -g synora-gateway /etc/synora-gateway
    sudo install -d -m 750 -o synora-gateway -g synora-gateway /var/lib/synora-gateway /var/log/synora-gateway

## 3. Test on this host
    cd /opt/synora && sudo .venv/bin/pip install -r tools/pipeline/requirements-client.txt
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest $(ls tools/pipeline/test_*.py | sed 's|/|.|g; s|\.py$||')
Expect all tests OK on a host that also has `claude` on PATH and the Worker requirements. On a Gateway-only host the
Worker-side modules fail for environmental reasons: run the Gateway-relevant modules listed in Part A instead, and
do not proceed on a failure in a Gateway module.

## 4. Configuration
    sudo cp tools/pipeline/deploy/gateway.env.example /etc/synora-gateway/gateway.env
    sudo chmod 640 /etc/synora-gateway/gateway.env && sudo chown root:synora-gateway /etc/synora-gateway/gateway.env
    sudo sed -i "s|REPLACE_ME|$(openssl rand -base64 48)|" /etc/synora-gateway/gateway.env

## 5. Enrol Johan's Worker and the first teammate (public keys only)
Each person runs `python -m tools.pipeline.admin_cli keygen --out-dir keys --name <name>` on their OWN machine
and sends only the printed public key. Then on the host:
    cd /opt/synora
    sudo .venv/bin/python -m tools.pipeline.admin_cli add-worker --registry /etc/synora-gateway/workers.json --worker-id worker-johan --public-key <JOHAN_WORKER_PUBKEY>
    sudo .venv/bin/python -m tools.pipeline.admin_cli add-developer --registry /etc/synora-gateway/team.json --developer-id <id> --name "<Name>" --github <gh> --public-key <PUBKEY> --modules docs/ --branches 'feature/*'
    sudo chown root:synora-gateway /etc/synora-gateway/*.json && sudo chmod 640 /etc/synora-gateway/*.json
Registries load at start: restart the service after every enrolment.

## 6. TLS front end (pick one)
Domain: copy `Caddyfile.domain` to /etc/caddy/Caddyfile, edit the name.
IP only:
    sudo install -d -m 750 -o root -g caddy /etc/caddy/tls
    sudo .venv/bin/python -m tools.pipeline.admin_cli gen-cert --out-dir /etc/caddy/tls --host <PUBLIC_IP> --days 90
    (gen-cert writes test_server.crt/.key: rename to gateway.crt/.key, chown root:caddy, chmod 644 crt / 640 key)
    The Caddyfile needs the global option `default_sni <PUBLIC_IP>` (already in Caddyfile.ip-selfsigned), or every
    IP-based TLS handshake fails with an internal-error alert.
    Give the .crt to Johan and teammates (SYNORA_CA_CERT) and compare the printed SHA-256 out of band.
Then `sudo systemctl reload caddy`.

## 7. Start
    sudo cp tools/pipeline/deploy/synora-gateway.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now synora-gateway
    curl -s http://127.0.0.1:8000/health
    curl -s https://<HOST>/health          # add --cacert gateway.crt for self-signed
    ss -ltn | grep 8000                    # must show 127.0.0.1:8000 only

## 8. Johan's Worker (Windows PC; needs no inbound access)
Run it as a supervised scheduled task: see Part C (install, update, stop, logs). For a one-off foreground run:
    set SYNORA_WORKER_ID=worker-johan
    set SYNORA_GATEWAY_URL=wss://<HOST>
    set SYNORA_WORKER_KEY_FILE=<path to worker-johan.key>
    set SYNORA_CA_CERT=<gateway.crt>            (self-signed only)
    set SYNORA_BRIDGE_REPO=<path to the Synora checkout the worktrees come from>
    python -m tools.pipeline.worker_daemon
Budget limits default to 10 jobs/hour, 50/day, 2 GiB, 2 worktrees (SYNORA_WORKER_JOBS_PER_HOUR, _PER_DAY, _MAX_DISK_MB, _MAX_WORKTREES).

## 9. First end-to-end teammate test
On the teammate machine (pip install -r tools/pipeline/requirements-client.txt), from a checkout of the repository:
    set SYNORA_GATEWAY_URL=https://<HOST>
    set SYNORA_DEVELOPER_ID=<id>
    set SYNORA_DEVELOPER_KEY_FILE=<path to private key>
    set SYNORA_CA_CERT=<gateway.crt>            (self-signed only)
    set SYNORA_WORKER_PUBLIC_KEY=<worker-johan.pub, from Johan, not from the Gateway>
    python -m tools.pipeline.teammate_cli smoke
The job's base commit defaults to the HEAD of that checkout, which must be in the history of the Worker's repository
(see `base_commit` in Part C); pass `--base-commit <sha>` to choose another.
Passes when every step prints PASS: sign in, Worker online, job accepted, job finished, Worker signature verifies, result
returned. A non-zero exit code names the failing step (3 = Worker offline, 4 = rejected, 5 = timeout, 6 = job failed,
7 = the Worker's signature did not verify).

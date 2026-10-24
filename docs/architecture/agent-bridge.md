# Synora Agent Bridge: architecture

Status: Phase B verified end to end. Phase C step 1 hardens it. Repair loops are not implemented. Tooling lives in `tools/pipeline/`, separate from `frontend/`, `backend/`, `database/`, and `prototypes/`.

## Path

```text
Antigravity → MCP (synora-bridge) → bridge → Claude Code (headless)
                                       ↓
                       isolated worktree → verification → reviewer (read-only)
                                       ↓
                         job record (.agents/pipeline/jobs/, gitignored)
                                       ↓
                       Antigravity: get_status / get_result
```

## Job lifecycle

```text
QUEUED → RUNNING → VERIFYING → REVIEWING → SUCCEEDED
                                        ↘ CHANGES_REQUIRED
any unfinished state → FAILED
```

- `review` tasks skip `VERIFYING`: `RUNNING → REVIEWING → SUCCEEDED`.
- `FAILED` is set on any error. Nothing turns a failure into success.
- Illegal transitions raise an error. The allowed moves are in `ALLOWED_NEXT` in `bridge.py`. The check and the write happen under one lock.

## Task types

| Type | Writes | Verification | Review |
|---|---|---|---|
| `docs` | `docs/agent-bridge/` only | scope check (`SCOPE_ONLY` if no commands) | yes |
| `code` | `frontend/`, `backend/`, `database/`, `tests/` | commands required (`NOT_CONFIGURED` otherwise) | yes |
| `review` | nothing | none | yes, read-only |

## Ownership of a records directory

- One server owns one records directory. The owner holds an OS file lock on `.agents/pipeline/jobs/.owner.lock` (`records.py`).
- The lock is released by the OS when the process exits, including after a crash. A leftover file never blocks a new owner, and PIDs are never compared, so PID reuse cannot matter.
- The owner's PID and start time are written after byte 0 of the lock file, so a refused server can name the owner. Byte 0 itself is locked, and reading it fails on Windows by design.
- A second server exits with code 3 before it serves any request, and it does not touch the records.
- Verified with real processes: a second server was refused with exit code 3 while the first was alive. After the first was hard-killed, a new server started with exit code 0.

## Recovery

Recovery runs once, at startup. `Bridge.recover_abandoned(owner)` requires the `DirectoryOwner` that holds this records directory, and it refuses any other owner. Its safety does not depend on its caller remembering to take the lock.

- Every unfinished job is set to FAILED, and the error records the status it was in. Its record, task, and any diagnostic fields are kept.
- A bridge worktree is removed only if its name is a canonical job UUID, it sits directly under the worktree folder, it is not a symlink, and git lists it as a worktree or it has a `.git` file. Any other folder is left alone and reported.
- A removal failure is recorded on the job as `cleanup_error`, and reported at startup.
- A malformed record is reported and kept. It does not stop recovery.
- Temp files from interrupted writes are removed, but only those matching the bridge's own temp-name pattern.
- Recovery is idempotent. A second run finds nothing to do.

## Records

- JSON under `.agents/pipeline/jobs/`. Schema unchanged from Phase B.
- Writes go to a unique temp file, are flushed to disk, then replace the record in one step. A reader never sees half a record.
- Read-modify-write runs under one process-wide lock, so concurrent updates from several threads do not lose changes.
- Reads and replaces retry briefly on Windows if another handle has the file open.
- A record that is not valid JSON, or names a different job, is reported as corrupt. It is never silently overwritten.
- Records hold task, status, timestamps, Claude's result (capped), changed files, diff (capped), verification results, the review with its evidence, and any error. They hold no environment variables and no credentials.

## Executables

- `git` and `claude` are resolved by `executables.py`: an explicit variable (`SYNORA_BRIDGE_GIT`, `SYNORA_BRIDGE_CLAUDE`) first, then PATH.
- An explicit variable that is not a file is an error that names the variable. A missing tool is an error that says how to fix it.
- The server resolves both at startup and exits with code 2 if one is missing. Nothing is downloaded or installed.
- Commands are run as argument lists without a shell.

## Isolation and enforcement

- Each job gets its own detached git worktree under `.agents/pipeline/worktrees/<job_id>`. The path comes from a validated UUID, so task text cannot steer it.
- The bridge checks the repo's own status before and after each job, excluding `.agents/pipeline/`. A change to the checkout during a job fails it.
- A job records its base commit at start. A review worktree starts from the reviewed job's base commit, and the reviewed diff is applied there, so the review sees the candidate change.
- A job from the Gateway may name a `base_commit`. The Worker accepts only 7 to 40 hex characters that resolve to a commit in its own repository's current `HEAD` history, starts the worktree at exactly that commit, and refuses the job before any worktree exists otherwise. An absent value means `HEAD`. The Gateway checks only the format.
- Claude's result is signed twice: the outer envelope, which the Gateway verifies, and an attestation over the result's SHA-256 stored inside the result, which clients verify against the Worker's public key obtained from Johan (never from the Gateway).
- While Claude runs, the Worker keeps reading the Gateway connection so keepalive pings are answered, and it resends a signed result that the Gateway did not acknowledge after it reconnects.
- Claude's tools are set by `--tools`:
  - implementer: `Read,Write,Edit,Glob,Grep`, permission `acceptEdits`. Writes are limited to the job worktree.
  - reviewer: `Read,Glob,Grep`, permission `dontAsk`. No shell, no edit tool, no MCP. The bridge also checks that the reviewer left the worktree unchanged.
- `--strict-mcp-config` and `--setting-sources project` keep the headless Claude from loading the bridge, other MCP servers, or user-level hooks and plugins.
- Scope allowlists are checked after the run, in code.
- Verification commands come from the server's configuration, never from the task.

## Reviewer evidence

The reviewer gets facts the bridge computed, not facts it must infer:

- `files`, `documentation_only`, `lines_added`, `lines_removed`
- `diff_truncated`
- `verification_status` and a plain-language `verification_note`. For `SCOPE_ONLY` it says no test or build command ran.
- The implementer's claim, labelled UNVERIFIED.

Findings carry a `category`: `SCOPE_VIOLATION`, `IMPLEMENTATION_DEFECT`, `UNSUPPORTED_CLAIM`, `SECURITY_CONCERN`, `MISSING_TEST`, `DOCUMENTATION_PROBLEM`, or `OTHER`. An unknown category becomes `OTHER`.

The review result stores `evidence_limits`: what the reviewer says it could not check. If the reviewer omits it, the stored text says so explicitly.

### What the reviewer can prove

- The written file or diff matches, or does not match, the requested task.
- A change is outside the allowed scope, or looks like a defect, a security concern, or a missing test, judging by reading the code.
- A statement about work done is not supported by the evidence shown. That is an UNSUPPORTED_CLAIM.

### What the reviewer cannot prove

- That any test, build, or command passed or was run. It cannot run anything.
- That code works at runtime, or that a fix addresses a bug it did not reproduce.
- That files outside the worktree are unchanged, beyond the bridge's own checks.
- Anything in the diff's truncated part. Those jobs fail instead of being reviewed in part.

Requested content is not a claim. If the task asked for a sentence inside a file, the reviewer checks that the sentence is there. It flags UNSUPPORTED_CLAIM only for statements about work done that the evidence does not show.

The reviewer's text is model output. Its verdict is evidence to weigh, not a guarantee.

## What counts as enforcement

- **Tool-level (Claude Code):** the `--tools` list and the permission modes. The reviewer's write tool was not offered, so a write attempt was refused by absence. For the implementer, a write outside the worktree was refused with a tool-level denial.
- **Code-level (bridge):** UUID validation, a contained `working_dir`, scope allowlists, status transitions, the checkout-unchanged check, the reviewer worktree check, the owner lock, and the restricted recovery paths.
- **Prompt-level (not a boundary):** instructions in the prompt, such as "write only under docs/agent-bridge/". Scope is enforced in code after the run, so no security decision depends on the prompt.

## Open items

- No approval gate, commit, push, or merge. Those belong to a later phase.
- No repair loop and no background scheduler.
- Synora has no test suite, so `code` tasks cannot succeed until verification commands are configured.
- Paths with short Windows names can make the Claude harness refuse reads. Configure long paths.
- A single lock file per records directory means one server per repo. Two repos get two directories and two owners.


## Phase C Step 3: Team Identity and Dual-Network Foundation

Status: **IMPLEMENTED** (Foundation & Protocol Layer ready for Phase C Step 4).

### Implementation Status Matrix

- **IMPLEMENTED**:
  - `TeamRegistry` (`tools/pipeline/team_registry.py`): Developer entry management (`project_owner`, `developer`, `auditor`), Ed25519 public key validation, module scopes, allowed branch patterns, and active/suspended states.
  - `Authentication` (`tools/pipeline/auth.py`): Ed25519 cryptographic challenge-response authentication, replay-protected nonce store, and short-lived session tokens without IP binding.
  - `Authorization` (`tools/pipeline/authorization.py`): Role-based action checks, strict cross-developer job isolation, branch pattern matching, module scope enforcement, and project owner escalation.
  - `Contribution Gate` (`tools/pipeline/contribution_gate.py`): Validation of initial and repair tasks. Enforces non-empty developer diffs for repair, supports 1-line bug fixes (no crude line-count minimums), requires non-zero failure exit codes with output evidence, and rejects path traversal.
  - `Developer-Owned Jobs` (`tools/pipeline/records.py`, `bridge.py`, `server.py`): Immutable `developer_id` binding on records, preventing cross-developer mutation.
  - `Protocol Envelope` (`tools/pipeline/protocol.py`): Structured message definitions (`AUTHENTICATE`, `WORKER_REGISTER`, `HEARTBEAT`, `JOB_ASSIGN`, `JOB_ACK`, `JOB_PROGRESS`, `JOB_RESULT`, `JOB_FAILURE`, `JOB_CANCEL`, `WORKER_DISCONNECT`) with payload schema validation.
  - `Persistent Queue` (`tools/pipeline/queue.py`): Stateful SQLite job queue with transactional atomic claims, fair round-robin developer scheduling, bounded depth, and stale worker recovery.
  - `Audit Logger` (`tools/pipeline/audit.py`): Structured JSON Lines logging with recursive scrubbing of sensitive fields (`private_key`, `token`, `password`, `secret`, `authorization`, `signature`).
  - `Gateway Coordination Engine` (`tools/pipeline/gateway.py`): Unified gateway engine tying together Auth, Registry, Authorization, ContributionGate, Queue, and Audit.
  - `Outbound Worker Foundation` (`tools/pipeline/worker.py`): Outbound daemon client that polls gateway, delegates work to `Bridge` in isolated worktrees, and returns reviewable diffs/patches without Git credentials.

- **PLANNED** (Phase C Step 4):
  - Remote Gateway Service: Publicly hosted HTTPS/WSS coordination server.
  - Same-Network Mode: Local LAN listener with mTLS for same-subnet teammate collaboration.
  - Cryptographically signed result envelopes with formal key rotation and nonce replay protection.

- **NOT_IMPLEMENTED** (Deliberate Security Boundaries):
  - No public listening ports on Johan's PC (outbound-only worker architecture).
  - No client IP address binding or fingerprinting.
  - No crude 3-line contribution thresholds.
  - No Git write, commit, push, or merge permissions for Claude.

- **NOT_VERIFIED**:
  - Different-network physical WAN latency and WebSocket reconnection under poor connectivity (deferred to Step 4 deployment).


## Phase C Step 4: Secure Gateway & Outbound Worker Implementation

Status: **IMPLEMENTED & VERIFIED LOCALLY AND ON LAN SIMULATION**

Target Architecture:
`	ext
                  GitHub
              Source of Truth
                    ▲
                    │
          Developer Branch / PR
                    │
              Developer PC
              Antigravity
                    │
              HTTPS / TLS
                    │
                    ▼
        ┌─────────────────────┐
        │ Synora Agent Gateway│
        │                     │
        │ Authentication      │
        │ Authorization       │
        │ Queue (SQLite)      │
        │ Rate Limits         │
        │ Audit Logging       │
        └──────────┬──────────┘
                   │
             outbound WSS
                   │
                   ▼
        ┌─────────────────────┐
        │ Johan Claude Worker │
        │                     │
        │ Heartbeat           │
        │ Job execution       │
        │ Bridge integration  │
        └──────────┬──────────┘
                   │
             Existing Bridge
                   │
             isolated worktree
                   │
                 Claude
`

### Absolute Security Invariant: Outbound-Only Worker Architecture

Johan\'s personal computer **MUST NOT** be directly reachable from the public internet.
The worker establishes an outbound persistent TLS/WSS connection to the Public Gateway.
- Zero inbound listening ports on Johan\'s PC.
- No router port forwarding.
- No dynamic DNS.
- No exposing Claude CLI or Git filesystem to the network.

### Implementation Status Matrix

- **IMPLEMENTED**:
  - Gateway HTTP API (	ools/pipeline/gateway_app.py): Starlette-based REST API providing endpoints:
    - POST /auth/challenge: Ed25519 challenge generation with 300s TTL.
    - POST /auth/verify: Signature verification and HMAC-SHA256 session token issuance.
    - POST /jobs: Authenticated job submission enforcing caller identity, contribution gates, size limits (64KB task, 512KB diff), and concurrency quotas.
    - GET /jobs/{job_id}: Job status with strict cross-developer access checks.
    - GET /jobs/{job_id}/result: Full result retrieval with authorization enforcement.
    - POST /jobs/{job_id}/cancel: Cancellation of queued jobs.
    - GET /health: Health and uptime probe with security headers (
osniff, DENY, 
o-store).
    - GET /worker/status: Registered worker status and heartbeat metrics.
  - Worker Registry (	ools/pipeline/worker_registry.py): Registry tracking authorized workers, Ed25519 public keys, status (ctive/suspended), and supported capabilities.
  - Cryptographic Signed Result Envelopes (	ools/pipeline/result_envelope.py): Canonical deterministic JSON serialization (json.dumps(canonical, sort_keys=True, separators=(',', ':'))) signed by the worker\'s Ed25519 private key. Replay protection enforced via SQLite seen_nonces table, timestamp freshness window (300s), and cross-check against assigned worker and developer.
  - Outbound Worker Daemon (	ools/pipeline/worker.py): Persistent daemon client establishing strictly outbound WebSocket connections (/ws/worker). Zero inbound listening ports. Automatically performs handshake registration, periodic heartbeats, job polling, isolated execution via Bridge, result signing, and bounded exponential backoff reconnection.
  - Persistent Queue Concurrency & Fair Scheduling (	ools/pipeline/queue.py): Per-developer concurrent active job bounding (default 1 concurrent active job per developer), atomic conditional claiming (WHERE job_id = ? AND status = 'QUEUED'), fair round-robin developer interleaving, and SQLite transaction persistence across process restarts.
  - Stale Worker Detection & Safe Job Recovery: Gateway detects stale workers via 
eap_stale_workers and safely resets unfinished ASSIGNED/RUNNING jobs back to QUEUED so in-flight tasks are never lost on worker disconnect.
  - LAN Mode & TLS Hardening (	ools/pipeline/tls_config.py): TLS 1.2+ configuration with modern cipher suites and strict certificate validation (erify=True). Ephemeral CA and test certificate generation. Unauthenticated LAN access strictly rejected.
  - Remote MCP Shim (	ools/pipeline/remote_shim.py): MCP adapter enabling Antigravity to interact with the remote gateway over HTTPS using submit_task, get_status, get_result, and cancel_job without direct Claude execution or filesystem access.
  - Git Ownership Protection (	ools/pipeline/test_git_ownership.py): Verified invariant that Claude/worker never commits, pushes, or merges. Diffs and patches are returned to the human developer for manual review and staging.

- **VERIFIED**:
  - 204/204 combined tests passing (121 Phase C Step 1/2/3 tests + 60 Step 4 tests + 23 Step 6 deployment verification tests).
  - Production Gateway Server (`tools/pipeline/gateway_server.py`) with strict environment validation, persistent SQLite and registries, and refusal to generate ephemeral replacement secrets.
  - Production Worker Daemon (`tools/pipeline/worker_daemon.py`) with persistent Ed25519 key loading, graceful signal shutdown, and empty-queue idle sleep to eliminate busy-looping.
  - Mutual Ed25519 Challenge-Response WebSocket Authentication: Unauthenticated sockets cannot poll jobs; spoofing and eavesdropping on developer tasks are cryptographically blocked.
  - Background Recovery Scheduler (`RecoveryScheduler`): Periodic stale-worker reaping and job TTL expiration scheduled via Starlette lifespan with duplicate prevention.
  - All Gateway REST API endpoints, challenge-response auth, session token lifecycle, and audit scrubbing.
  - Role-based authorization, branch restrictions, and cross-developer job isolation.
  - Worker outbound WebSocket connection, registration handshake, heartbeats, and job lifecycle.
  - Signed result envelope generation and verification with tamper, replay, and expiration protection.
  - Stale worker timeout, job reclamation, and reconnect backoff.
  - Ephemeral TLS context creation and certificate validation.
  - Git ownership verification: zero branch ref advances and zero commits created by worker.
  - Local backward compatibility: existing stdio synora-bridge MCP server still fully functional.

- **NOT_VERIFIED**:
  - Live cross-WAN physical internet testing over mobile hotspot / VPS (no public VPS deployment was provisioned during this offline development phase).
  - Production TLS termination behind Caddy / reverse proxy on Cloud Run / Fly.io.

- **PLANNED** (Phase C Step 5):
  - Multi-developer verification across heterogeneous network environments (home, university, mobile networks).
  - Production deployment of Gateway coordination container to cloud host with Caddy TLS reverse proxy.

## Persistent Engineering Lead

Status: implemented locally on `feature/persistent-lead`. Not deployed. Production needs the Gateway's scope column
(migrated automatically on start), a Worker update, and the decisions listed under "Open items" below.

### Architecture

    Gateway (queue, authorization, signed results)
      |
      v
    Worker (one identity per process; outbound WebSocket only)
      |-- task_type "lead" ---> Engineering Lead: ONE persistent Claude session
      |                             (created once with --session-id, resumed with --resume)
      |                             guarded by the Lead mutex
      |                             |
      |                             v
      |                         independent reviewer: ephemeral, read-only, no session, outside the mutex
      |
      |-- other task types ---> bridge: per-job isolated worktree and branch (unchanged)

The Lead's own turns are serialized. Implementation jobs are not: independent Worker instances, each with its
own identity, run them at the same time, and each job keeps its own worktree or local job.

### Johan's usage

1. Set `SYNORA_LEAD_WORKSPACE` in the Worker's `worker.env` to a folder of its own. It must not be inside
   `%USERPROFILE%\.synora` or the bridge checkout. The Worker refuses to start otherwise.
2. Open the Lead from that folder:
   `python -m tools.pipeline.lead_attach` (it reads the same environment variables).
   Do not run a bare `claude --resume`: it does not take the Lead mutex, so Worker turns would not wait for it.
3. Keep one attachment open at a time. While it is open, Worker turns wait (up to two minutes, then the job fails
   with "Lead busy"). Exit the terminal to release the Lead.
4. Anything you type becomes part of the same conversation the Worker resumes for the next request.

The session ID is kept only in the Worker's local state folder (`lead_state.json`). It is an identifier, not a
credential, but it is not written to tracked files.

### Session lifecycle

    UNINITIALIZED -> CREATING -> ACTIVE -> (BROKEN on a session mismatch)

- The session ID is written to disk before Claude is asked to create the session.
- Claude's returned `session_id` must equal the stored one on creation and on every resume. A mismatch marks the Lead
  BROKEN and refuses further turns. The ID is never replaced.
- A creation interrupted by a restart fails closed: an administrator decides what to do.
- A configured `SYNORA_LEAD_SESSION_ID` that differs from the stored one fails closed.

### Queue, concurrency and duplicates

- The Gateway queue is unchanged in its ordering. Each job carries the scope approved for its developer, taken from
  the registry, never from the request body. A job without scope is refused by the Lead.
- The Lead mutex is an OS file lock. The OS releases it if the holder dies, so a killed turn cannot block the Lead.
- Each locked section uses its own handle, so one runner can be shared by threads.
- A repeated job ID returns its stored, redacted outcome and is not run again.
- A turn still pending after a restart is recorded as interrupted and reported to the Gateway as a failure once the
  Worker reconnects, so it is not left RUNNING.
- The Worker now sends heartbeats while a job runs. Before this, a run longer than the 60-second stale timeout got
  its Worker reaped and its job run twice. This also affected implementation jobs.

### Security model

- The Lead keeps the restricted posture of the bridge: `--restricted`, `--strict-mcp-config`, project settings only,
  and read-only tools (`Read,Glob,Grep`). No Bash, no MCP servers, no user-level plugins or hooks.
- Restricted mode confines file reads to the working directory. Verified: a read outside the workspace is refused and
  recorded in `permission_denials`.
- Lead instructions are passed on the command line with `--append-system-prompt`. A project `CLAUDE.md` is not loaded
  under `--restricted`.
- Every turn carries the requester, branch, and approved modules and branches. Teammate text is wrapped in a
  `<request>` block that cannot be closed from inside, and it is treated as data.
- The reviewer is a separate, read-only invocation with no session, so it does not inherit the Lead's context.
- Secrets matching known credential formats are redacted from stored outcomes and the turn log. The turn log holds
  metadata only: job ID, requester, branch, scope, Lead session identifier, turn number, status, cost, review verdict.
- Superpowers, ECC, Bash and unrestricted Claude are not enabled. Enabling any of them needs its own security review.

### Known limits and open items

- **Shared conversation.** One Lead conversation holds requests from every teammate. A later turn can see an earlier
  teammate's request, and transcripts on disk keep every request. This is a blocker for multi-teammate production use
  until it is reviewed. The Lead's instructions reduce, but do not prevent, cross-teammate exposure.
- **Lead cost grows with the conversation.** Costs are recorded per turn and cumulatively. Session rotation is a
  documented follow-up and is not automatic.
- **The Lead does not dispatch work itself.** Specialist jobs are submitted through the existing path. Automatic
  parsing of Lead decisions into sub-jobs is deferred.
- **Production concurrency needs more enrolled Worker identities.** One Worker process runs one job at a time. Running
  implementation jobs side by side in production means starting more Worker instances, each with its own enrolled
  identity. That is a Gateway administration action and has not been done.
- **Registry module scopes.** The registry normalizes `frontend/*` to `frontend/*/`, so wildcard module scopes do not
  match file paths. This predates the Lead and is not changed here.
- **Per-developer job limit.** The Gateway allows one active job per developer. A developer's Lead request and
  implementation job therefore cannot be in flight together.
- **Interactive attach is verified only by spike and unit tests.** The attach wrapper's lock and environment behaviour
  are tested with a stand-in process. Johan typing into a live attached session was observed in the local spike, not
  automated.
- **Not done:** live event streaming, Remote Control, automatic session rotation, a Lead web interface, and any
  production deployment.

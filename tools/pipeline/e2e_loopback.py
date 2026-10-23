"""Loopback end-to-end check for the Synora Agent Bridge.

Starts a real Gateway (HTTPS and WSS, ephemeral certificate), a real Worker daemon, and drives them
with the real teammate client:

    teammate client -> authenticated Gateway -> queued job -> Worker (outbound WSS) -> Claude
    -> signed result -> Gateway -> teammate client

It also checks, on the live processes, that an unauthenticated caller and a second developer are
refused, that plain HTTP to the TLS port fails, and that the Worker process has no listening socket.

Run from the repository root:
    python -m tools.pipeline.e2e_loopback --workdir <folder with a long path>

Uses real Claude Code for the job unless the Worker's executable is replaced via SYNORA_BRIDGE_CLAUDE.
"""

import argparse
import base64
import copy
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from .auth import generate_keypair
from .bridge import REPO_ROOT
from .executables import CLAUDE_ENV, GIT_ENV, resolve_executable
from .remote_shim import RemoteGatewayClient
from .result_envelope import AttestationError, verify_result_response
from .team_registry import DeveloperEntry, TeamRegistry
from .tls_config import generate_ephemeral_test_cert
from .worker_registry import WorkerRegistry

TERMINAL = {"SUCCEEDED", "FAILED", "ESCALATED", "CANCELLED", "EXPIRED"}
GATEWAY_LAUNCH = (
    "import os, uvicorn\n"
    "from tools.pipeline.gateway_server import create_production_app, load_gateway_config\n"
    "cfg = load_gateway_config()\n"
    "uvicorn.run(create_production_app(cfg), host=cfg['host'], port=cfg['port'],\n"
    "            ssl_certfile=os.environ['E2E_CERT'], ssl_keyfile=os.environ['E2E_KEY'], ws='wsproto')\n"
)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _key_file(folder, name, private_b64):
    path = folder / name
    path.write_bytes(base64.b64decode(private_b64))
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def _developer(developer_id, public_b64):
    return DeveloperEntry(
        developer_id=developer_id, developer_name=developer_id.title(), github_username=f"{developer_id}-gh",
        role="developer", status="active", public_key_ed25519=public_b64,
        assigned_modules=("docs/",), allowed_branches=("feature/*",),
    )


def _wait_for(check, seconds, what):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {what}.")


def _network_state(pid):
    """Listening and established TCP sockets for a process. Windows only; returns None elsewhere."""
    if os.name != "nt":
        return None
    script = (
        f"$c = Get-NetTCPConnection -OwningProcess {pid} -ErrorAction SilentlyContinue;"
        "$l = @($c | Where-Object State -eq 'Listen').Count;"
        "$e = @($c | Where-Object State -eq 'Established' | ForEach-Object { $_.RemotePort });"
        "\"$l|$($e -join ',')\""
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout.strip()
    listening, _, remote = out.partition("|")
    return int(listening or 0), [int(p) for p in remote.split(",") if p]


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    @property
    def passed(self):
        return all(ok for _, ok, _ in self.rows)


def _submit_and_wait(client, task, base_commit, branch, timeout):
    submitted = client.submit_task(task, task_type="docs", branch=branch, base_commit=base_commit)
    if not submitted.get("success"):
        return submitted, {}
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = client.get_status(submitted["job_id"])
        if status.get("status") in TERMINAL:
            break
        time.sleep(2)
    return submitted, status


def _check_base_commit_and_signature(report, ctx):
    """Real jobs through the real Gateway and Worker: what base_commit does, and what the client can verify."""
    alice, key, timeout = ctx["alice"], ctx["worker_public_key"], ctx["job_timeout"]

    submitted, status = _submit_and_wait(alice, "Create docs/agent-bridge/bad-base.md with one sentence.", "abc1234", "feature/e2e-bad", timeout)
    report.check("A base_commit that is not in the Worker's history passes the Gateway (format check only)", submitted.get("success"), str(submitted.get("error") or ""))
    result = alice.get_result(submitted["job_id"]) if submitted.get("job_id") else {}
    report.check("...but the Worker refuses it before doing any work", status.get("status") == "FAILED" and "base_commit" in str(result.get("error", "")), str(result.get("error")))
    report.check("The Worker is still running after refusing it", ctx["worker"].poll() is None)

    submitted, status = _submit_and_wait(alice, "Create docs/agent-bridge/hostile-base.md with one sentence.", "--output=/tmp/x", "feature/e2e-opt", timeout)
    report.check("An option-shaped base_commit never reaches git", status.get("status") == "FAILED" or not submitted.get("success"), str(status.get("status") or submitted.get("error")))

    submitted, status = _submit_and_wait(alice, "Create docs/agent-bridge/real-base.md with one sentence.", ctx["first_commit"], "feature/e2e-real", timeout)
    report.check("A real older commit is accepted and the job succeeds", status.get("status") == "SUCCEEDED", str(status.get("status")))
    verified = alice.get_verified_result(submitted["job_id"], key)
    report.check("The client verifies the Worker's signature on the result", verified.get("status") == "SUCCEEDED")
    report.check("The signed result records the requested older commit as its base", verified.get("base_commit") == ctx["first_commit"] != ctx["head_commit"], str(verified.get("base_commit")))

    tampered = copy.deepcopy(alice.get_result(submitted["job_id"]))
    tampered["result"]["changed_files"] = ["backend/server.js"]
    try:
        verify_result_response(tampered, key, submitted["job_id"], "alice")
        detected = False
    except AttestationError:
        detected = True
    report.check("A result altered in transit is rejected by the client", detected)
    try:
        alice.get_verified_result(submitted["job_id"], ed25519.Ed25519PrivateKey.generate().public_key())
        wrong_key = False
    except AttestationError:
        wrong_key = True
    report.check("A result is rejected when checked against any other key", wrong_key)


def _check_refusals(report, ctx):
    url, cert, bob = ctx["url"], ctx["cert"], ctx["bob"]
    forged = httpx.post(f"{url}/auth/verify", json={"developer_id": "alice", "nonce": "0" * 32, "signature": base64.b64encode(os.urandom(64)).decode()}, verify=cert, timeout=5)
    report.check("A forged login signature is refused", forged.status_code in (400, 401), str(forged.status_code))
    unknown = httpx.post(f"{url}/auth/challenge", json={"developer_id": "mallory"}, verify=cert, timeout=5)
    report.check("An unenrolled developer cannot start a login", unknown.status_code in (401, 403, 404), str(unknown.status_code))
    outside = bob.submit_task("Create docs/agent-bridge/x.md with one sentence.", task_type="docs", branch="main", base_commit=ctx["head_commit"])
    report.check("A developer cannot submit for a branch outside their scope", not outside.get("success"), str(outside.get("error")))
    token = bob.authenticate()
    junk = httpx.post(f"{url}/jobs", headers={"Authorization": f"Bearer {token}"}, json={"task": 5, "task_type": ["x"], "branch": None, "base_commit": {}}, verify=cert, timeout=5)
    report.check("Malformed job data is rejected with a client error, not a crash", 400 <= junk.status_code < 500, str(junk.status_code))
    try:
        httpx.get(f"{url}/health", timeout=5)
        untrusted = False
    except httpx.HTTPError:
        untrusted = True
    report.check("A client that does not hold the pinned certificate cannot connect", untrusted)
    try:
        httpx.get(f"{url}/health", verify=ctx["other_cert"], timeout=5)
        wrong_pin = False
    except httpx.HTTPError:
        wrong_pin = True
    report.check("A client pinned to a different certificate cannot connect", wrong_pin)


def _check_worker_tls_and_restart(report, ctx):
    url, cert, alice = ctx["url"], ctx["cert"], ctx["alice"]

    def workers():
        res = httpx.get(f"{url}/worker/status", headers={"Authorization": f"Bearer {alice.authenticate()}"}, verify=cert, timeout=5)
        return {w["worker_id"]: w for w in res.json()["workers"]}

    tls_worker = workers().get("worker-tls", {})
    report.check("A Worker pinned to the wrong certificate never registers", not tls_worker.get("online") and tls_worker.get("last_heartbeat") is None, str(tls_worker.get("last_heartbeat")))
    report.check("...and keeps retrying rather than exiting", ctx["tls_worker"].poll() is None)

    restarted_at = datetime.now(timezone.utc)
    old = ctx["gateway_holder"][0]
    old.terminate()
    old.wait(timeout=15)
    ctx["gateway_holder"][0] = ctx["launch_gateway"]()
    _wait_for(lambda: httpx.get(f"{url}/health", verify=cert, timeout=3).status_code == 200, 40, "the restarted Gateway")

    def heartbeat_after_restart():
        worker = workers()["worker-e2e"]
        return worker["online"] and datetime.fromisoformat(worker["last_heartbeat"]) > restarted_at

    _wait_for(heartbeat_after_restart, 90, "the Worker to reconnect after the Gateway restart")
    report.check("The Worker reconnects by itself after a real Gateway restart", True)
    submitted, status = _submit_and_wait(alice, "Create docs/agent-bridge/after-restart.md with one sentence.", ctx["head_commit"], "feature/e2e-restart", ctx["job_timeout"])
    verified = alice.get_verified_result(submitted["job_id"], ctx["worker_public_key"]) if submitted.get("job_id") else {}
    report.check("A job after the restart succeeds and its signature verifies", status.get("status") == "SUCCEEDED" and verified.get("status") == "SUCCEEDED", str(status.get("status")))


def run(workdir, job_timeout):
    base = Path(workdir) / f"e2e-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    report = Report()
    procs = []
    try:
        (base / "tls").mkdir()
        cert, key = generate_ephemeral_test_cert(str(base / "tls"), common_name="localhost", ip_addresses=["127.0.0.1"], valid_days=1)
        alice_pub, alice_priv = generate_keypair()
        bob_pub, bob_priv = generate_keypair()
        worker_pub, worker_priv = generate_keypair()
        registry = TeamRegistry([_developer("alice", alice_pub), _developer("bob", bob_pub)])
        registry.save(base / "team.json")
        tls_pub, tls_priv = generate_keypair()
        worker_registry = WorkerRegistry(str(base / "workers.json"))
        worker_registry.enroll("worker-e2e", worker_pub)
        worker_registry.enroll("worker-tls", tls_pub)

        repo = base / "worker-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "README.md").write_text("e2e repo\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".agents/pipeline/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        git_commit = ["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "commit", "-q", "-m"]
        subprocess.run([*git_commit, "init"], cwd=repo, check=True)
        first_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        (repo / "later.txt").write_text("added after the first commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run([*git_commit, "second"], cwd=repo, check=True)
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

        port = _free_port()
        url = f"https://localhost:{port}"
        gateway_env = {
            **os.environ,
            "SYNORA_GATEWAY_HOST": "127.0.0.1", "SYNORA_GATEWAY_PORT": str(port),
            "SYNORA_GATEWAY_SIGNING_SECRET": base64.b64encode(os.urandom(48)).decode(),
            "SYNORA_GATEWAY_REGISTRY_PATH": str(base / "team.json"),
            "SYNORA_GATEWAY_WORKER_REGISTRY_PATH": str(base / "workers.json"),
            "SYNORA_GATEWAY_DB_PATH": str(base / "gateway.db"),
            "SYNORA_GATEWAY_AUDIT_LOG_PATH": str(base / "audit.log"),
            "SYNORA_GATEWAY_RECOVERY_INTERVAL": "5",
            "E2E_CERT": cert, "E2E_KEY": key,
        }
        def launch_gateway():
            proc = subprocess.Popen([sys.executable, "-c", GATEWAY_LAUNCH], cwd=REPO_ROOT, env=gateway_env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(proc)
            return proc

        gateway_holder = [launch_gateway()]
        _wait_for(lambda: httpx.get(f"{url}/health", verify=cert, timeout=3).status_code == 200, 40, "the Gateway /health over TLS")
        report.check("Gateway serves HTTPS with a verified certificate", True, url)

        worker_env = {
            **os.environ,
            "SYNORA_WORKER_ID": "worker-e2e", "SYNORA_GATEWAY_URL": f"wss://localhost:{port}",
            "SYNORA_CA_CERT": cert, "SYNORA_WORKER_KEY_FILE": str(_key_file(base, "worker.key", worker_priv)),
            "SYNORA_BRIDGE_REPO": str(repo), "SYNORA_WORKER_POLL_INTERVAL": "1",
            GIT_ENV: resolve_executable("git", GIT_ENV), CLAUDE_ENV: resolve_executable("claude", CLAUDE_ENV),
        }
        worker = subprocess.Popen([sys.executable, "-m", "tools.pipeline.worker_daemon"], cwd=REPO_ROOT, env=worker_env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(worker)

        alice = RemoteGatewayClient(url, "alice", ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(alice_priv)), ca_certfile=cert)
        bob = RemoteGatewayClient(url, "bob", ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(bob_priv)), ca_certfile=cert)
        token = alice.authenticate()
        report.check("Teammate authenticates with a signed challenge", bool(token))

        def worker_online():
            res = httpx.get(f"{url}/worker/status", headers={"Authorization": f"Bearer {token}"}, verify=cert, timeout=3)
            return res.status_code == 200 and any(w.get("worker_id") == "worker-e2e" and w.get("online") for w in res.json().get("workers", []))

        _wait_for(worker_online, 60, "the Worker to register over WSS")
        report.check("Worker registered with the Gateway over outbound WSS", True)

        smoke_env = {**os.environ, "SYNORA_GATEWAY_URL": url, "SYNORA_DEVELOPER_ID": "alice", "SYNORA_CA_CERT": cert,
                     "SYNORA_DEVELOPER_KEY_FILE": str(_key_file(base, "alice.key", alice_priv)),
                     "SYNORA_WORKER_PUBLIC_KEY": worker_pub}
        smoke = subprocess.run([sys.executable, "-m", "tools.pipeline.teammate_cli", "smoke", "--timeout", str(job_timeout), "--base-commit", base_commit],
                               cwd=REPO_ROOT, env=smoke_env, capture_output=True, text=True, timeout=job_timeout + 60)
        report.check("The teammate_cli smoke command passes end to end", smoke.returncode == 0, smoke.stdout.strip().splitlines()[-1] if smoke.stdout.strip() else smoke.stderr.strip()[-120:])

        submitted = alice.submit_task(
            "Create docs/agent-bridge/e2e-check.md with one sentence saying the loopback end-to-end check ran.",
            task_type="docs", branch="feature/e2e", base_commit=base_commit,
        )
        report.check("Authorized job queued by the Gateway", submitted.get("success") and submitted.get("status") == "QUEUED", str(submitted.get("job_id")))
        job_id = submitted["job_id"]

        deadline = time.time() + job_timeout
        status = {}
        while time.time() < deadline:
            status = alice.get_status(job_id)
            if status.get("status") in TERMINAL:
                break
            time.sleep(2)
        report.check("Job reached a final state", status.get("status") in TERMINAL, str(status.get("status")))
        result = alice.get_result(job_id)
        report.check("Agent execution succeeded through the Worker", result.get("status") == "SUCCEEDED", str(result.get("error") or ""))
        files = result.get("changed_files") or []
        report.check("Result returned through the Gateway with the changed file", "docs/agent-bridge/e2e-check.md" in files, str(files))

        (base / "tls-other").mkdir()
        other_cert, _other_key = generate_ephemeral_test_cert(str(base / "tls-other"), common_name="localhost", ip_addresses=["127.0.0.1"], valid_days=1)
        tls_env = {**worker_env, "SYNORA_WORKER_ID": "worker-tls", "SYNORA_WORKER_KEY_FILE": str(_key_file(base, "tls.key", tls_priv)), "SYNORA_CA_CERT": other_cert}
        tls_worker = subprocess.Popen([sys.executable, "-m", "tools.pipeline.worker_daemon"], cwd=REPO_ROOT, env=tls_env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(tls_worker)
        ctx = {"url": url, "cert": cert, "other_cert": other_cert, "alice": alice, "bob": bob, "worker": worker, "tls_worker": tls_worker,
               "worker_public_key": ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(worker_pub)), "job_timeout": job_timeout,
               "first_commit": first_commit, "head_commit": base_commit, "gateway_holder": gateway_holder, "launch_gateway": launch_gateway}
        _check_base_commit_and_signature(report, ctx)
        _check_refusals(report, ctx)

        anonymous = httpx.get(f"{url}/jobs/{job_id}", verify=cert, timeout=5)
        report.check("Unauthenticated read of a job is refused", anonymous.status_code in (401, 403), str(anonymous.status_code))
        bob_token = bob.authenticate()
        other = httpx.get(f"{url}/jobs/{job_id}", headers={"Authorization": f"Bearer {bob_token}"}, verify=cert, timeout=5)
        report.check("A second developer cannot read the first developer's job", other.status_code in (401, 403, 404), str(other.status_code))
        try:
            httpx.get(f"http://localhost:{port}/health", timeout=5)
            plain_ok = False
        except httpx.HTTPError:
            plain_ok = True
        report.check("Plain HTTP to the TLS port is refused", plain_ok)

        _check_worker_tls_and_restart(report, ctx)
        state = _network_state(worker.pid)
        if state is None:
            report.check("Worker has no listening socket (Windows check only)", True, "skipped: not Windows")
        else:
            listening, remote_ports = state
            report.check("Worker process has no listening socket", listening == 0, f"listening={listening}")
            report.check("Worker holds an outbound connection to the Gateway port", port in remote_ports, f"remote ports={remote_ports}")
    except Exception as err:
        report.check("Harness ran to completion", False, f"{type(err).__name__}: {err}")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(base, onerror=lambda func, path, _exc: (os.chmod(path, stat.S_IWRITE), func(path)), ignore_errors=False) if base.exists() else None
    print("\nRESULT:", "PASS" if report.passed else "FAIL")
    return 0 if report.passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workdir", required=True, help="Folder for the temporary test files. Use a long path (no 8.3 short names).")
    parser.add_argument("--job-timeout", type=int, default=240)
    args = parser.parse_args()
    sys.exit(run(args.workdir, args.job_timeout))


if __name__ == "__main__":
    main()

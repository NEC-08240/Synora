"""Teammate command line for the Synora Agent Gateway.

Configuration (environment or flags):
    SYNORA_GATEWAY_URL        https://<gateway host>
    SYNORA_DEVELOPER_ID       your developer id
    SYNORA_DEVELOPER_KEY_FILE path to your private key file (from admin_cli keygen)
    SYNORA_CA_CERT            only for a self-signed Gateway: the .crt Johan gave you

    python -m tools.pipeline.teammate_cli smoke
    python -m tools.pipeline.teammate_cli submit "Create docs/agent-bridge/note.md with one sentence."
    python -m tools.pipeline.teammate_cli status <job_id>
    python -m tools.pipeline.teammate_cli result <job_id>

`smoke` is the first connectivity test: sign in, confirm the Worker is online, run one harmless
documentation job through the Worker, and report the result. Exit code 0 means every step worked.
"""

import argparse
import json
import os
import sys
import time

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from .remote_shim import RemoteGatewayClient

TERMINAL = {"SUCCEEDED", "FAILED", "ESCALATED", "CANCELLED", "EXPIRED"}
SMOKE_TASK = "Create docs/agent-bridge/connectivity-check.md with one sentence saying the Synora connectivity check ran."


def _client(args):
    url = args.url or os.environ.get("SYNORA_GATEWAY_URL")
    developer_id = args.developer_id or os.environ.get("SYNORA_DEVELOPER_ID")
    key_file = args.key_file or os.environ.get("SYNORA_DEVELOPER_KEY_FILE")
    ca_cert = args.ca_cert or os.environ.get("SYNORA_CA_CERT")
    missing = [name for name, value in (("--url / SYNORA_GATEWAY_URL", url), ("--developer-id / SYNORA_DEVELOPER_ID", developer_id),
                                        ("--key-file / SYNORA_DEVELOPER_KEY_FILE", key_file)) if not value]
    if missing:
        raise SystemExit("Missing configuration: " + ", ".join(missing))
    with open(key_file, "rb") as handle:
        raw = handle.read()
    if len(raw) != 32:
        raise SystemExit(f"{key_file} is not a 32-byte private key file. Create one with: python -m tools.pipeline.admin_cli keygen")
    key = ed25519.Ed25519PrivateKey.from_private_bytes(raw)
    return RemoteGatewayClient(url, developer_id, key, ca_certfile=ca_cert), ca_cert or True


def _wait(client, job_id, timeout):
    deadline = time.time() + timeout
    status = {}
    while time.time() < deadline:
        status = client.get_status(job_id)
        if status.get("status") in TERMINAL:
            return status
        time.sleep(2)
    return status


def _step(label, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    return ok


def smoke(client, verify, branch, timeout):
    try:
        token = client.authenticate()
    except Exception as err:
        _step("Sign in to the Gateway", False, str(err))
        return 1
    _step("Sign in to the Gateway", True)

    status = httpx.get(f"{client.gateway_url}/worker/status", headers={"Authorization": f"Bearer {token}"}, verify=verify, timeout=15)
    workers = status.json().get("workers", []) if status.status_code == 200 else []
    online = [w["worker_id"] for w in workers if w.get("status") == "active" and w.get("online")]
    if not _step("Johan's Worker is online", bool(online), ", ".join(online) or f"none online (HTTP {status.status_code})"):
        print("Ask Johan to start the Worker, then run this again.")
        return 3

    submitted = client.submit_task(SMOKE_TASK, task_type="docs", branch=branch)
    if not _step("Job accepted by the Gateway", bool(submitted.get("success")), str(submitted.get("job_id") or submitted.get("error"))):
        return 4
    job_id = submitted["job_id"]
    final = _wait(client, job_id, timeout)
    if not _step("Job finished", final.get("status") in TERMINAL, str(final.get("status"))):
        print(f"The job is still {final.get('status')}. Check later with: status {job_id}")
        return 5
    result = client.get_result(job_id)
    ok = result.get("status") == "SUCCEEDED"
    _step("Result returned through the Gateway", ok, f"status={result.get('status')} files={result.get('changed_files')}")
    if not ok:
        print("error:", result.get("error"))
    return 0 if ok else 6


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--url", "--developer-id", "--key-file", "--ca-cert"):
        parser.add_argument(flag)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("smoke")
    s.add_argument("--branch", default="feature/connectivity-check")
    s.add_argument("--timeout", type=int, default=300)
    s = sub.add_parser("submit")
    s.add_argument("task")
    s.add_argument("--task-type", default="docs", choices=["docs", "code", "review"])
    s.add_argument("--branch", default="feature/task")
    for name in ("status", "result"):
        s = sub.add_parser(name)
        s.add_argument("job_id")
    args = parser.parse_args(argv)

    client, verify = _client(args)
    if args.command == "smoke":
        return smoke(client, verify, args.branch, args.timeout)
    if args.command == "submit":
        print(json.dumps(client.submit_task(args.task, task_type=args.task_type, branch=args.branch), indent=2))
    elif args.command == "status":
        print(json.dumps(client.get_status(args.job_id), indent=2))
    else:
        print(json.dumps(client.get_result(args.job_id), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

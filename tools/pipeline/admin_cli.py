"""Bootstrap and enrolment commands for the Synora Agent Bridge.

Private keys are generated on the machine that will use them and never leave it. Only public keys are
given to the Gateway host. The Gateway loads its registries at start, so restart it after an enrolment.

    python -m tools.pipeline.admin_cli keygen --out-dir keys --name worker-johan
    python -m tools.pipeline.admin_cli add-developer --registry team.json --developer-id alice \\
        --name "Alice" --github alice-gh --public-key <base64>
    python -m tools.pipeline.admin_cli add-worker --registry workers.json --worker-id worker-johan --public-key <base64>
    python -m tools.pipeline.admin_cli gen-cert --out-dir tls --host 203.0.113.10 --days 90
"""

import argparse
import base64
import hashlib
import ipaddress
import os
import ssl
import sys
from pathlib import Path

from .auth import generate_keypair
from .team_registry import ROLES, DeveloperEntry, RegistryError, TeamRegistry
from .tls_config import generate_ephemeral_test_cert
from .worker_registry import WorkerRegistry, WorkerRegistryError


def _split(value):
    return tuple(part.strip() for part in value.split(",") if part.strip())


def keygen(out_dir, name):
    """Write <name>.key (raw 32 bytes, owner-only) and <name>.pub (base64). Never overwrites a key."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    public_b64, private_b64 = generate_keypair()
    private_path = folder / f"{name}.key"
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(base64.b64decode(private_b64))
    (folder / f"{name}.pub").write_text(public_b64 + "\n", encoding="utf-8")
    return private_path, public_b64


def add_developer(registry_path, developer_id, name, github, public_key, role="developer", modules=("docs/",), branches=("feature/*",)):
    for module in modules:
        if module != "*" and "*" in module:
            raise ValueError(f"Module scope {module!r} is not valid: scopes are directory prefixes such as 'docs/', not patterns.")
    path = Path(registry_path)
    registry = TeamRegistry.load(path) if path.exists() else TeamRegistry()
    registry.register(DeveloperEntry(
        developer_id=developer_id, developer_name=name, github_username=github, role=role, status="active",
        public_key_ed25519=public_key, assigned_modules=tuple(modules), allowed_branches=tuple(branches),
    ))
    registry.save(path)


def update_developer_scope(registry_path, developer_id, modules, branches):
    """Change only a developer's modules and branches. Identity, key, role and status are kept.

    The new entry is validated by the same rules as enrolment, and the file is rewritten only if every check passes.
    """
    for module in modules:
        if module != "*" and "*" in module:
            raise ValueError(f"Module scope {module!r} is not valid: scopes are directory prefixes such as 'docs/', not patterns.")
    path = Path(registry_path)
    registry = TeamRegistry.load(path)
    current = registry.get(developer_id)  # raises DeveloperNotFound for an unknown developer
    registry.update(DeveloperEntry(
        developer_id=current.developer_id, developer_name=current.developer_name,
        github_username=current.github_username, role=current.role, status=current.status,
        public_key_ed25519=current.public_key_ed25519, assigned_modules=tuple(modules),
        allowed_branches=tuple(branches), rate_limits=current.rate_limits,
    ))
    registry.save(path)


def add_worker(registry_path, worker_id, public_key):
    WorkerRegistry(str(registry_path)).enroll(worker_id, public_key)


def gen_cert(out_dir, host, days):
    """Self-signed certificate for a host with no public name. Clients must be given the .crt to trust it."""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = None
    cert_path, key_path = generate_ephemeral_test_cert(str(folder), common_name=host, ip_addresses=addresses, valid_days=days)
    if os.name != "nt":
        os.chmod(key_path, 0o600)
    pem = Path(cert_path).read_text(encoding="utf-8")
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    return cert_path, key_path, fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("keygen", help="Create an Ed25519 key pair on this machine.")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", required=True)

    p = sub.add_parser("add-developer", help="Enrol a developer by public key.")
    p.add_argument("--registry", required=True)
    p.add_argument("--developer-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--github", required=True)
    p.add_argument("--public-key", required=True, help="Base64 public key from the developer's keygen.")
    p.add_argument("--role", default="developer", choices=sorted(ROLES))
    p.add_argument("--modules", default="docs/", help="Comma-separated directory prefixes the developer may touch, e.g. docs/,frontend/")
    p.add_argument("--branches", default="feature/*", help="Comma-separated branch patterns the developer may use.")

    p = sub.add_parser("update-developer-scope", help="Change a developer's modules and branches only.")
    p.add_argument("--registry", required=True)
    p.add_argument("--developer-id", required=True)
    p.add_argument("--modules", required=True, help="Comma-separated directory prefixes ('docs/') or exact files ('README.md').")
    p.add_argument("--branches", required=True, help="Comma-separated branch patterns the developer may use.")

    p = sub.add_parser("add-worker", help="Enrol the Worker by public key.")
    p.add_argument("--registry", required=True)
    p.add_argument("--worker-id", required=True)
    p.add_argument("--public-key", required=True)

    p = sub.add_parser("gen-cert", help="Self-signed certificate for a host with no public name.")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--host", required=True, help="IP address or DNS name clients will connect to.")
    p.add_argument("--days", type=int, default=90)

    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            path, public_key = keygen(args.out_dir, args.name)
            print(f"Private key (keep on this machine only): {path}")
            print(f"Public key (send this to the Gateway admin): {public_key}")
        elif args.command == "add-developer":
            add_developer(args.registry, args.developer_id, args.name, args.github, args.public_key, args.role, _split(args.modules), _split(args.branches))
            print(f"Enrolled developer {args.developer_id!r} in {args.registry}. Restart the Gateway to load it.")
        elif args.command == "update-developer-scope":
            update_developer_scope(args.registry, args.developer_id, _split(args.modules), _split(args.branches))
            print(f"Updated scope for developer {args.developer_id!r} in {args.registry}. Restart the Gateway to load it.")
        elif args.command == "add-worker":
            add_worker(args.registry, args.worker_id, args.public_key)
            print(f"Enrolled worker {args.worker_id!r} in {args.registry}. Restart the Gateway to load it.")
        else:
            cert, key, fingerprint = gen_cert(args.out_dir, args.host, args.days)
            print(f"Certificate (give this to the Worker and teammates as the CA file): {cert}")
            print(f"Private key (stays on the Gateway host): {key}")
            print(f"SHA-256 fingerprint (compare out of band): {fingerprint}")
    except (RegistryError, WorkerRegistryError, ValueError, FileExistsError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

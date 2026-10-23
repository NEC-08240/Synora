# Standalone Production Server for Synora Agent Gateway
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from starlette.applications import Starlette

from .audit import AuditLogger
from .gateway import Gateway
from .gateway_app import create_gateway_app
from .queue import JobQueue
from .team_registry import TeamRegistry
from .worker_registry import WorkerRegistry


def load_gateway_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Load and strictly validate Gateway production configuration from environment."""
    environ = env if env is not None else os.environ

    # Host & Port (Strict Default: 127.0.0.1 - Never expose Uvicorn directly to public 0.0.0.0)
    host = environ.get('SYNORA_GATEWAY_HOST', '127.0.0.1')
    try:
        port = int(environ.get('SYNORA_GATEWAY_PORT', '8000'))
    except ValueError:
        raise ValueError('SYNORA_GATEWAY_PORT must be a valid integer.')

    # Signing Secret (Required - Never generate ephemeral random secret in production mode)
    signing_secret_str = environ.get('SYNORA_GATEWAY_SIGNING_SECRET')
    if not signing_secret_str or not signing_secret_str.strip():
        raise ValueError(
            'SYNORA_GATEWAY_SIGNING_SECRET environment variable is required in production mode. '
            'Refusing to generate ephemeral secret which would invalidate sessions on restart.'
        )
    signing_secret = signing_secret_str.strip().encode('utf-8')
    if len(signing_secret) < 32:
        raise ValueError(
            f'SYNORA_GATEWAY_SIGNING_SECRET must be at least 32 bytes for HMAC-SHA256 security (got {len(signing_secret)}).'
        )

    # Team Registry Path (Required & File must exist)
    registry_path = environ.get('SYNORA_GATEWAY_REGISTRY_PATH')
    if not registry_path:
        raise ValueError('SYNORA_GATEWAY_REGISTRY_PATH environment variable is required.')
    if not os.path.isfile(registry_path):
        raise FileNotFoundError(f'Team registry file does not exist: {registry_path}')

    # Worker Registry Path (Required & File must exist)
    worker_reg_path = environ.get('SYNORA_GATEWAY_WORKER_REGISTRY_PATH')
    if not worker_reg_path:
        raise ValueError('SYNORA_GATEWAY_WORKER_REGISTRY_PATH environment variable is required.')
    if not os.path.isfile(worker_reg_path):
        raise FileNotFoundError(f'Worker registry file does not exist: {worker_reg_path}')

    # Database Path (Persistent SQLite)
    db_path = environ.get('SYNORA_GATEWAY_DB_PATH', 'gateway.db')

    # Audit Log Path
    audit_path = environ.get('SYNORA_GATEWAY_AUDIT_LOG_PATH', 'audit.log')

    # Recovery Interval (seconds)
    try:
        recovery_interval = float(environ.get('SYNORA_GATEWAY_RECOVERY_INTERVAL', '30.0'))
    except ValueError:
        raise ValueError('SYNORA_GATEWAY_RECOVERY_INTERVAL must be a valid float.')

    return {
        'host': host,
        'port': port,
        'signing_secret': signing_secret,
        'registry_path': registry_path,
        'worker_reg_path': worker_reg_path,
        'db_path': db_path,
        'audit_path': audit_path,
        'recovery_interval': recovery_interval,
    }


def create_production_app(config: Optional[Dict[str, Any]] = None) -> Starlette:
    """Create a fully-wired production Gateway Starlette application from configuration."""
    cfg = config if config is not None else load_gateway_config()

    team_registry = TeamRegistry.load(cfg['registry_path'])
    worker_registry = WorkerRegistry(cfg['worker_reg_path'])
    queue = JobQueue(cfg['db_path'])
    audit = AuditLogger(cfg['audit_path'])

    gateway = Gateway(
        registry=team_registry,
        worker_registry=worker_registry,
        queue=queue,
        audit=audit,
        signing_secret=cfg['signing_secret'],
    )

    app = create_gateway_app(
        gateway=gateway,
        recovery_interval=cfg['recovery_interval'],
        enable_recovery_scheduler=True,
    )
    # Store references on app state for inspection/lifecycle management
    app.state.gateway = gateway
    app.state.config = cfg

    return app


def main():
    try:
        config = load_gateway_config()
    except Exception as err:
        print(f'Configuration error: {err}', file=sys.stderr)
        sys.exit(1)

    app = create_production_app(config)
    print(
        f'Starting Synora Gateway server on {config["host"]}:{config["port"]} '
        f'(DB: {config["db_path"]}, Registry: {config["registry_path"]})'
    )
    # wsproto is the WebSocket implementation this stack was tested with; pin it instead of letting uvicorn choose.
    uvicorn.run(app, host=config['host'], port=config['port'], ws='wsproto')


if __name__ == '__main__':
    main()

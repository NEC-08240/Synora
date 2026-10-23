# Standalone Production Daemon for Johan's Claude Worker
import os
import signal
import sys
import time
from typing import Any, Dict, Optional

from .bridge import Bridge
from .budget import DEFAULT_JOBS_PER_DAY, DEFAULT_MAX_DISK_BYTES, DEFAULT_MAX_WORKTREES, DEFAULT_JOBS_PER_WINDOW, DEFAULT_WINDOW_SECONDS, WorkerBudget
from .transport import normalize_gateway_url
from .worker import OutboundWorker, load_worker_private_key


def _positive_int(environ, name, default):
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f'{name} must be a whole number.') from None
    if value < 1:
        raise ValueError(f'{name} must be at least 1.')
    return value


def load_worker_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Load and validate Worker daemon configuration from environment."""
    environ = env if env is not None else os.environ

    worker_id = environ.get('SYNORA_WORKER_ID', 'worker-johan-primary').strip()
    if not worker_id:
        raise ValueError('SYNORA_WORKER_ID must be a non-empty string.')

    allow_insecure_lan = environ.get('SYNORA_WORKER_ALLOW_INSECURE_LAN', '').strip() == '1'
    gateway_url = environ.get('SYNORA_GATEWAY_URL')
    if not gateway_url:
        raise ValueError('SYNORA_GATEWAY_URL environment variable is required.')
    gateway_url = normalize_gateway_url(gateway_url, allow_insecure=allow_insecure_lan)

    key_file = environ.get('SYNORA_WORKER_KEY_FILE')
    key_b64 = environ.get('SYNORA_WORKER_PRIVATE_KEY_B64')
    if not key_file and not key_b64:
        raise ValueError(
            'SYNORA_WORKER_KEY_FILE or SYNORA_WORKER_PRIVATE_KEY_B64 is required. '
            'Refusing to generate ephemeral key in daemon mode to protect worker identity continuity.'
        )

    private_key = load_worker_private_key(key_file=key_file, key_b64=key_b64)

    repo_root = environ.get('SYNORA_BRIDGE_REPO', '.')
    claude_bin = environ.get('SYNORA_BRIDGE_CLAUDE')
    git_bin = environ.get('SYNORA_BRIDGE_GIT')

    try:
        poll_interval = float(environ.get('SYNORA_WORKER_POLL_INTERVAL', '3.0'))
    except ValueError:
        raise ValueError('SYNORA_WORKER_POLL_INTERVAL must be a valid float.')
    if poll_interval < 0.1:
        raise ValueError('SYNORA_WORKER_POLL_INTERVAL must be at least 0.1s to prevent busy-looping.')

    try:
        heartbeat_interval = float(environ.get('SYNORA_WORKER_HEARTBEAT_INTERVAL', '10.0'))
    except ValueError:
        raise ValueError('SYNORA_WORKER_HEARTBEAT_INTERVAL must be a valid float.')

    try:
        max_backoff = float(environ.get('SYNORA_WORKER_MAX_BACKOFF', '30.0'))
    except ValueError:
        raise ValueError('SYNORA_WORKER_MAX_BACKOFF must be a valid float.')

    ca_cert = environ.get('SYNORA_CA_CERT')
    ssl_context = None
    if ca_cert:
        if not os.path.isfile(ca_cert):
            raise FileNotFoundError(f'SYNORA_CA_CERT file not found: {ca_cert}')
        import ssl
        ssl_context = ssl.create_default_context(cafile=ca_cert)

    budget = {
        'jobs_per_window': _positive_int(environ, 'SYNORA_WORKER_JOBS_PER_HOUR', DEFAULT_JOBS_PER_WINDOW),
        'window_seconds': DEFAULT_WINDOW_SECONDS,
        'jobs_per_day': _positive_int(environ, 'SYNORA_WORKER_JOBS_PER_DAY', DEFAULT_JOBS_PER_DAY),
        'max_disk_bytes': _positive_int(environ, 'SYNORA_WORKER_MAX_DISK_MB', DEFAULT_MAX_DISK_BYTES // (1024 * 1024)) * 1024 * 1024,
        'max_worktrees': _positive_int(environ, 'SYNORA_WORKER_MAX_WORKTREES', DEFAULT_MAX_WORKTREES),
    }

    return {
        'budget': budget,
        'allow_insecure_lan': allow_insecure_lan,
        'worker_id': worker_id,
        'gateway_url': gateway_url,
        'private_key': private_key,
        'repo_root': repo_root,
        'claude_bin': claude_bin,
        'git_bin': git_bin,
        'poll_interval': poll_interval,
        'heartbeat_interval': heartbeat_interval,
        'max_backoff': max_backoff,
        'ssl_context': ssl_context,
    }


def create_worker_from_config(config: Optional[Dict[str, Any]] = None) -> OutboundWorker:
    """Instantiate OutboundWorker with Bridge and persistent Ed25519 identity."""
    cfg = config if config is not None else load_worker_config()

    bridge = Bridge(
        repo_root=cfg['repo_root'],
        git=cfg['git_bin'],
        claude=cfg['claude_bin'],
    )

    budget = WorkerBudget(bridge.records_dir.parent, **cfg['budget'])

    worker = OutboundWorker(
        worker_id=cfg['worker_id'],
        gateway_url=cfg['gateway_url'],
        bridge=bridge,
        private_key=cfg['private_key'],
        heartbeat_interval=cfg['heartbeat_interval'],
        max_backoff=cfg['max_backoff'],
        ssl_context=cfg.get('ssl_context'),
        poll_interval=cfg['poll_interval'],
        allow_insecure_lan=cfg['allow_insecure_lan'],
        budget=budget,
    )
    return worker


def main():
    try:
        config = load_worker_config()
    except Exception as err:
        print(f'Configuration error: {err}', file=sys.stderr)
        sys.exit(1)

    worker = create_worker_from_config(config)

    def _handle_signal(signum, frame):
        print(f'\nReceived shutdown signal ({signum}). Stopping worker daemon gracefully...')
        worker.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _handle_signal)

    print(
        f'Starting Synora Worker daemon [{config["worker_id"]}] connecting to {config["gateway_url"]} '
        f'(poll_interval={config["poll_interval"]}s, max_backoff={config["max_backoff"]}s)'
    )
    print('Absolute Security Invariant: Zero inbound listening sockets.')

    worker.run_reconnect_loop(max_cycles=None, poll_interval=config['poll_interval'])
    print('Synora Worker daemon stopped.')


if __name__ == '__main__':
    main()

# Standalone Production Daemon for Johan's Claude Worker
import argparse
import logging
import logging.handlers
import os
import re
import signal
import sys
import time
from typing import Any, Dict, Optional

from functools import partial
from pathlib import Path

from .bridge import Bridge
from .budget import DEFAULT_JOBS_PER_DAY, DEFAULT_MAX_DISK_BYTES, DEFAULT_MAX_WORKTREES, DEFAULT_JOBS_PER_WINDOW, DEFAULT_WINDOW_SECONDS, WorkerBudget
from .executables import CLAUDE_ENV, resolve_executable
from .lead import LeadRunner, run_claude_process, validate_lead_workspace
from .transport import normalize_gateway_url
from .worker import OutboundWorker, load_worker_private_key


logger = logging.getLogger('synora.worker')
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3


def load_env_file(path, environ=None):
    """Set SYNORA_* settings from a NAME=value file. Variables already in the environment win; other names are ignored.

    The file holds paths and names only. Private keys stay in their own files and are never read here.
    """
    environ = os.environ if environ is None else environ
    with open(path, 'r', encoding='utf-8') as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            name = name.strip()
            if re.fullmatch(r'SYNORA_[A-Z0-9_]+', name):
                environ.setdefault(name, value.strip())


def configure_logging(environ=None):
    """Timestamped logs to stderr, or to a size-rotated file when SYNORA_WORKER_LOG_FILE is set."""
    environ = os.environ if environ is None else environ
    log_file = environ.get('SYNORA_WORKER_LOG_FILE')
    handlers = None
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handlers = [logging.handlers.RotatingFileHandler(log_file, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding='utf-8')]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', handlers=handlers, force=True)


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

    home = environ.get('USERPROFILE') or environ.get('HOME') or str(Path.home())
    lead_state_dir = environ.get('SYNORA_LEAD_STATE_DIR') or str(Path(home) / '.synora' / 'lead')

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
        'home': home,
        'lead_workspace': environ.get('SYNORA_LEAD_WORKSPACE') or None,
        'lead_state_dir': lead_state_dir,
        'lead_session_id': environ.get('SYNORA_LEAD_SESSION_ID') or None,
    }


def create_lead_runner(cfg: Dict[str, Any]) -> Optional[LeadRunner]:
    """The persistent Lead is off unless SYNORA_LEAD_WORKSPACE is set. A bad workspace stops startup."""
    if not cfg.get('lead_workspace'):
        return None
    workspace = validate_lead_workspace(cfg['lead_workspace'], repo_root=cfg['repo_root'], home=cfg['home'])
    state_dir = Path(cfg['lead_state_dir'])
    executable = cfg.get('claude_bin')
    claude = partial(run_claude_process, executable=executable or resolve_executable('claude', CLAUDE_ENV))
    runner = LeadRunner(
        state_path=state_dir / 'lead_state.json',
        mutex_path=state_dir / 'lead.lock',
        workspace=workspace,
        log_path=state_dir / 'lead_turns.jsonl',
        claude=claude,
        expected_session_id=cfg.get('lead_session_id'),
    )
    interrupted = runner.recover()
    if interrupted:
        logger.warning(f'Lead jobs interrupted before this start and recorded as failed: {", ".join(interrupted)}')
    return runner


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
        lead=create_lead_runner(cfg),
    )
    return worker


def main(argv=None):
    parser = argparse.ArgumentParser(description='Synora Worker daemon')
    parser.add_argument('--env-file', help='NAME=value file with SYNORA_* settings (paths and names only).')
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            load_env_file(args.env_file)
        configure_logging()
        config = load_worker_config()
    except Exception as err:
        configure_logging()
        logger.critical(f'Configuration error: {err}')
        print(f'Configuration error: {err}', file=sys.stderr)
        sys.exit(1)

    try:
        worker = create_worker_from_config(config)

        def _handle_signal(signum, frame):
            logger.info(f'Received shutdown signal ({signum}). Stopping worker daemon gracefully...')
            worker.stop()

        signal.signal(signal.SIGINT, _handle_signal)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _handle_signal)

        logger.info(
            f'Starting Synora Worker daemon [{config["worker_id"]}] connecting to {config["gateway_url"]} '
            f'(poll_interval={config["poll_interval"]}s, max_backoff={config["max_backoff"]}s)'
        )
        logger.info('Absolute Security Invariant: Zero inbound listening sockets.')

        worker.run_reconnect_loop(max_cycles=None, poll_interval=config['poll_interval'])
        logger.info('Synora Worker daemon stopped.')
    except Exception:
        logger.critical('Worker daemon crashed', exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

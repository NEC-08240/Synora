"""Gateway transport rules for the Worker.

Production uses wss:// only. Plain ws:// or http:// is accepted only when the operator explicitly
enables LAN development mode, and that choice comes from local configuration, never from a job.
A bad URL is refused, never silently downgraded or repaired.
"""

import ssl
from urllib.parse import urlsplit

SECURE_SCHEMES = {'wss': 'wss', 'https': 'wss'}          # https is an upgrade to wss, never a downgrade
INSECURE_SCHEMES = {'ws': 'ws', 'http': 'ws'}            # plaintext: LAN development mode only
WS_PATH = '/ws/worker'


def normalize_gateway_url(raw, allow_insecure=False):
    """Return the WebSocket base URL for the Gateway, or raise ValueError."""
    if not isinstance(raw, str) or not raw:
        raise ValueError('Gateway URL is required.')
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in raw):
        raise ValueError('Gateway URL must not contain whitespace or control characters.')
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme in SECURE_SCHEMES:
        target = SECURE_SCHEMES[scheme]
    elif scheme in INSECURE_SCHEMES:
        if not allow_insecure:
            raise ValueError(
                f'{scheme}:// is refused. Use wss://. Plain connections are only allowed when '
                'SYNORA_WORKER_ALLOW_INSECURE_LAN=1 is set for a LAN development gateway.'
            )
        target = INSECURE_SCHEMES[scheme]
    else:
        raise ValueError(f'Unsupported Gateway URL scheme: {parts.scheme!r}.')
    if not parts.hostname:
        raise ValueError('Gateway URL needs a host name.')
    if '@' in parts.netloc:
        raise ValueError('Gateway URL must not contain credentials.')
    if parts.query or parts.fragment:
        raise ValueError('Gateway URL must not contain a query or fragment.')
    path = parts.path.rstrip('/')
    if path.endswith(WS_PATH):
        path = path[:-len(WS_PATH)]
    return f'{target}://{parts.netloc}{path}'


def websocket_url(base):
    return base.rstrip('/') + WS_PATH


def certificate_options(target_url, ssl_context=None):
    """TLS options for websocket-client. Verification stays on for wss; it is never disabled."""
    if not target_url.startswith('wss://'):
        return None
    if ssl_context is not None:
        return {'context': ssl_context}
    return {'cert_reqs': ssl.CERT_REQUIRED}

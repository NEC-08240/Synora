# Cryptographic authentication using Ed25519 for Synora Agent Bridge
import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from .team_registry import DeveloperEntry, TeamRegistry

class AuthenticationError(ValueError):
    pass

class ChallengeExpired(AuthenticationError):
    pass

class ReplayDetected(AuthenticationError):
    pass

class DeveloperSuspended(AuthenticationError):
    pass

def generate_keypair() -> Tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    priv = ed25519.Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption()
    )
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw
    )
    return (
        base64.b64encode(raw_pub).decode('ascii'),
        base64.b64encode(raw_priv).decode('ascii')
    )

def sign_message(private_key_b64: str, message: bytes | str) -> str:
    raw_priv = base64.b64decode(private_key_b64.strip(), validate=True)
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(raw_priv)
    if isinstance(message, str):
        message = message.encode('utf-8')
    sig = priv.sign(message)
    return base64.b64encode(sig).decode('ascii')

class ChallengeStore:
    def __init__(self, default_ttl_seconds: int = 300):
        self.default_ttl = default_ttl_seconds
        self._challenges: Dict[str, dict] = {}
        self._used_nonces: set = set()

    def create(self, developer_id: str, ttl_seconds: Optional[int] = None) -> dict:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        nonce = secrets.token_hex(32)
        now = time.time()
        record = {
            'developer_id': developer_id,
            'nonce': nonce,
            'issued_at': now,
            'expires_at': now + ttl,
            'message': f'synora-challenge:{developer_id}:{nonce}',
            'used': False,
        }
        self._challenges[nonce] = record
        self._prune_expired()
        return {
            'developer_id': developer_id,
            'nonce': nonce,
            'message': record['message'],
            'expires_at': record['expires_at'],
        }

    def consume(self, developer_id: str, nonce: str) -> str:
        self._prune_expired()
        if nonce in self._used_nonces:
            raise ReplayDetected('Challenge nonce was already used.')
        if nonce not in self._challenges:
            raise AuthenticationError('Challenge nonce is unknown, invalid, or expired.')
        record = self._challenges[nonce]
        if record['developer_id'] != developer_id:
            raise AuthenticationError('Challenge nonce does not match developer_id.')
        if record['used']:
            raise ReplayDetected('Challenge nonce was already used.')
        if time.time() > record['expires_at']:
            del self._challenges[nonce]
            raise ChallengeExpired('Challenge nonce has expired.')
        self._used_nonces.add(nonce)
        del self._challenges[nonce]
        return record['message']

    def _prune_expired(self):
        now = time.time()
        to_del = [n for n, r in self._challenges.items() if now > r['expires_at'] + 60]
        for n in to_del:
            del self._challenges[n]

def verify_developer_signature(developer: DeveloperEntry, message: str | bytes, signature_b64: str) -> bool:
    if not developer.is_active():
        raise DeveloperSuspended(f'Developer {developer.developer_id!r} is {developer.status}.')
    if isinstance(message, str):
        message = message.encode('utf-8')
    try:
        raw_pub = base64.b64decode(developer.public_key_ed25519.strip(), validate=True)
        pub = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)
        raw_sig = base64.b64decode(signature_b64.strip(), validate=True)
        pub.verify(raw_sig, message)
        return True
    except InvalidSignature:
        raise AuthenticationError('Invalid cryptographic signature.') from None
    except Exception as err:
        raise AuthenticationError(f'Signature validation error: {err}') from None

def create_session_token(developer: DeveloperEntry, signing_secret: bytes, ttl_seconds: int = 3600) -> str:
    now = int(time.time())
    payload = {
        'jti': secrets.token_hex(16),
        'sub': developer.developer_id,
        'role': developer.role,
        'iat': now,
        'exp': now + ttl_seconds,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('ascii').rstrip('=')
    sig = hmac.new(signing_secret, payload_b64.encode('ascii'), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode('ascii').rstrip('=')
    return f'{payload_b64}.{sig_b64}'

def verify_session_token(token_str: str, signing_secret: bytes, registry: TeamRegistry) -> DeveloperEntry:
    parts = token_str.strip().split('.')
    if len(parts) != 2:
        raise AuthenticationError('Malformed session token.')
    payload_b64, sig_b64 = parts
    try:
        padded_sig = sig_b64 + '=' * (-len(sig_b64) % 4)
        raw_sig = base64.urlsafe_b64decode(padded_sig.encode('ascii'))
        expected = hmac.new(signing_secret, payload_b64.encode('ascii'), hashlib.sha256).digest()
        if not hmac.compare_digest(raw_sig, expected):
            raise AuthenticationError('Session token signature verification failed.')

        padded_payload = payload_b64 + '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_payload.encode('ascii')).decode('utf-8'))
    except Exception as err:
        raise AuthenticationError(f'Invalid token: {err}') from None

    if time.time() > payload.get('exp', 0):
        raise AuthenticationError('Session token has expired.')

    developer_id = payload.get('sub')
    if not developer_id:
        raise AuthenticationError('Token missing subject (developer_id).')

    developer = registry.get(developer_id)
    if not developer.is_active():
        raise DeveloperSuspended(f'Developer {developer_id!r} is {developer.status}.')
    return developer

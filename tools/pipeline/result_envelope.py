# Cryptographic signed result envelope protocol for Synora Agent Bridge
import base64
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

CANONICAL_FIELDS = (
    'job_id',
    'developer_id',
    'worker_id',
    'attempt',
    'status',
    'result',
    'timestamp',
    'nonce',
)


class ResultEnvelopeError(ValueError):
    pass


class InvalidResultSignature(ResultEnvelopeError):
    pass


class ResultExpired(ResultEnvelopeError):
    pass


class ResultReplayDetected(ResultEnvelopeError):
    pass


class ResultMismatchError(ResultEnvelopeError):
    pass


def canonical_serialize(payload_dict: Dict[str, Any]) -> bytes:
    canonical = {k: payload_dict[k] for k in CANONICAL_FIELDS if k in payload_dict}
    if len(canonical) != len(CANONICAL_FIELDS):
        missing = set(CANONICAL_FIELDS) - set(canonical.keys())
        raise ResultEnvelopeError(f'Missing canonical fields in payload: {sorted(missing)}')
    return json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode('utf-8')


class ResultEnvelope:
    @staticmethod
    def create(
        private_key: ed25519.Ed25519PrivateKey,
        job_id: str,
        developer_id: str,
        worker_id: str,
        status: str,
        result: Dict[str, Any],
        attempt: int = 1,
        nonce: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not nonce:
            nonce = secrets.token_hex(16)
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat()

        payload = {
            'job_id': job_id,
            'developer_id': developer_id,
            'worker_id': worker_id,
            'attempt': int(attempt),
            'status': status,
            'result': result,
            'timestamp': timestamp,
            'nonce': nonce,
        }

        canonical_bytes = canonical_serialize(payload)
        sig_raw = private_key.sign(canonical_bytes)
        signature_b64 = base64.b64encode(sig_raw).decode('ascii')

        envelope = dict(payload)
        envelope['signature'] = signature_b64
        return envelope

    @staticmethod
    def verify(
        envelope: Dict[str, Any],
        public_key: ed25519.Ed25519PublicKey,
        expected_job_id: Optional[str] = None,
        expected_developer_id: Optional[str] = None,
        expected_worker_id: Optional[str] = None,
        max_age_seconds: float = 300.0,
    ) -> Dict[str, Any]:
        if not isinstance(envelope, dict):
            raise ResultEnvelopeError('Envelope must be a dictionary.')

        for field in CANONICAL_FIELDS:
            if field not in envelope:
                raise ResultEnvelopeError(f'Missing envelope field {field!r}.')
        if 'signature' not in envelope:
            raise ResultEnvelopeError('Missing envelope signature.')

        sig_b64 = envelope['signature']
        try:
            sig_raw = base64.b64decode(sig_b64, validate=True)
        except Exception as err:
            raise InvalidResultSignature(f'Signature is not valid base64: {err}') from None

        if expected_job_id and envelope['job_id'] != expected_job_id:
            raise ResultMismatchError(
                f"Envelope job_id {envelope['job_id']!r} does not match expected {expected_job_id!r}."
            )
        if expected_developer_id and envelope['developer_id'] != expected_developer_id:
            raise ResultMismatchError(
                f"Envelope developer_id {envelope['developer_id']!r} does not match expected {expected_developer_id!r}."
            )
        if expected_worker_id and envelope['worker_id'] != expected_worker_id:
            raise ResultMismatchError(
                f"Envelope worker_id {envelope['worker_id']!r} does not match expected {expected_worker_id!r}."
            )

        try:
            dt = datetime.fromisoformat(envelope['timestamp'])
            now = datetime.now(timezone.utc)
            age = (now - dt).total_seconds()
            if abs(age) > max_age_seconds:
                raise ResultExpired(f'Result envelope is outside acceptable time window (age={age:.1f}s, max={max_age_seconds}s).')
        except ResultExpired:
            raise
        except Exception as err:
            raise ResultEnvelopeError(f'Malformed timestamp in envelope: {err}') from None

        canonical_bytes = canonical_serialize(envelope)
        try:
            public_key.verify(sig_raw, canonical_bytes)
        except InvalidSignature:
            raise InvalidResultSignature('Result envelope signature verification failed.') from None

        return envelope

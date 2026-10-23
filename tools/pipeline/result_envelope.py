# Cryptographic signed result envelope protocol for Synora Agent Bridge
import base64
import hashlib
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


# --- Client-verifiable attestation -------------------------------------------------------------
# The Gateway stores only the signed envelope's `result` and drops the signature, so a client cannot
# check the outer envelope. The Worker therefore signs a second, small envelope over a digest of the
# result and stores it inside the result under ATTESTATION_KEY. The client verifies it with the
# Worker's public key, which it must hold from a channel other than the Gateway.

ATTESTATION_KEY = 'attestation'
ATTESTATION_KIND = 'synora-result-v1'
CLIENT_MAX_AGE_SECONDS = 365 * 24 * 3600.0  # the client may read a result long after it was signed


class AttestationError(ResultEnvelopeError):
    pass


def result_digest(result: Dict[str, Any]) -> str:
    body = {k: v for k, v in result.items() if k != ATTESTATION_KEY}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def attest_result(private_key, job_id, developer_id, worker_id, status, result):
    """Return the result with a signed attestation of its content added under ATTESTATION_KEY."""
    attestation = ResultEnvelope.create(
        private_key=private_key, job_id=job_id, developer_id=developer_id, worker_id=worker_id, status=status,
        result={'kind': ATTESTATION_KIND, 'result_sha256': result_digest(result)},
    )
    return {**result, ATTESTATION_KEY: attestation}


def verify_result_response(response, public_key, expected_job_id, expected_developer_id, expected_worker_id=None):
    """Check a Gateway /jobs/<id>/result response against the Worker's public key.

    Returns the verified result dict, or raises AttestationError (the only failure type). Use that, not the response's top-level fields: the Gateway merges
    the result over its own job record and a compromised Gateway can change anything outside `result`.
    """
    result = response.get('result') if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise AttestationError('The response has no result to verify.')
    attestation = result.get(ATTESTATION_KEY)
    if not isinstance(attestation, dict):
        raise AttestationError('The result carries no Worker attestation (unsigned or from an older Worker).')
    try:
        ResultEnvelope.verify(
            attestation, public_key, expected_job_id=expected_job_id, expected_developer_id=expected_developer_id,
            expected_worker_id=expected_worker_id, max_age_seconds=CLIENT_MAX_AGE_SECONDS,
        )
    except ResultEnvelopeError as err:
        raise AttestationError(str(err)) from None
    signed = attestation.get('result')
    if not isinstance(signed, dict) or signed.get('kind') != ATTESTATION_KIND:
        raise AttestationError('The attestation is not a Synora result attestation.')
    if signed.get('result_sha256') != result_digest(result):
        raise AttestationError('The result content does not match what the Worker signed.')
    return result

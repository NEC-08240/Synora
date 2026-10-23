# Protocol message schemas and serialization for Gateway and Worker
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

MSG_AUTHENTICATE = 'AUTHENTICATE'
MSG_WORKER_REGISTER = 'WORKER_REGISTER'
MSG_WORKER_CHALLENGE = 'WORKER_CHALLENGE'
MSG_WORKER_AUTH = 'WORKER_AUTH'
MSG_HEARTBEAT = 'HEARTBEAT'
MSG_JOB_ASSIGN = 'JOB_ASSIGN'
MSG_JOB_ACK = 'JOB_ACK'
MSG_JOB_PROGRESS = 'JOB_PROGRESS'
MSG_JOB_RESULT = 'JOB_RESULT'
MSG_JOB_FAILURE = 'JOB_FAILURE'
MSG_JOB_CANCEL = 'JOB_CANCEL'
MSG_WORKER_DISCONNECT = 'WORKER_DISCONNECT'

KNOWN_MESSAGES = {
    MSG_AUTHENTICATE,
    MSG_WORKER_REGISTER,
    MSG_WORKER_CHALLENGE,
    MSG_WORKER_AUTH,
    MSG_HEARTBEAT,
    MSG_JOB_ASSIGN,
    MSG_JOB_ACK,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_JOB_FAILURE,
    MSG_JOB_CANCEL,
    MSG_WORKER_DISCONNECT,
}

class ProtocolError(ValueError):
    pass

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

class ProtocolMessage:
    def __init__(self, message_type: str, sender_id: str, payload: Dict[str, Any], message_id: str = None, timestamp: str = None):
        if message_type not in KNOWN_MESSAGES:
            raise ProtocolError(f'Unknown message_type: {message_type!r}')
        if not sender_id or not isinstance(sender_id, str):
            raise ProtocolError('sender_id must be a non-empty string.')
        if not isinstance(payload, dict):
            raise ProtocolError('payload must be a dictionary.')

        required_fields = {
            MSG_AUTHENTICATE: ('developer_id', 'nonce', 'signature'),
            MSG_WORKER_REGISTER: ('worker_id',),
            MSG_WORKER_CHALLENGE: ('worker_id', 'nonce', 'message'),
            MSG_WORKER_AUTH: ('worker_id', 'nonce', 'signature'),
            MSG_JOB_ASSIGN: ('job_id',),
            MSG_JOB_ACK: ('job_id', 'worker_id'),
            MSG_JOB_PROGRESS: ('job_id', 'status'),
            MSG_JOB_RESULT: ('job_id', 'status'),
            MSG_JOB_FAILURE: ('job_id', 'error'),
            MSG_JOB_CANCEL: ('job_id',),
        }
        for req in required_fields.get(message_type, ()):
            if req not in payload:
                raise ProtocolError(f'Missing required payload field {req!r} for message type {message_type!r}.')

        self.message_id = message_id or str(uuid.uuid4())
        self.message_type = message_type
        self.sender_id = sender_id
        self.timestamp = timestamp or _now_iso()
        self.payload = payload

    def to_dict(self) -> dict:
        return {
            'message_id': self.message_id,
            'message_type': self.message_type,
            'sender_id': self.sender_id,
            'timestamp': self.timestamp,
            'payload': self.payload,
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> 'ProtocolMessage':
        if not isinstance(data, dict):
            raise ProtocolError('Message data must be a JSON object.')
        for field in ('message_id', 'message_type', 'sender_id', 'timestamp', 'payload'):
            if field not in data:
                raise ProtocolError(f'Missing required envelope field: {field!r}')
        return cls(
            message_type=data['message_type'],
            sender_id=data['sender_id'],
            payload=data['payload'],
            message_id=data['message_id'],
            timestamp=data['timestamp'],
        )

    @classmethod
    def parse(cls, raw_json: str) -> 'ProtocolMessage':
        try:
            data = json.loads(raw_json)
        except Exception as err:
            raise ProtocolError(f'Malformed JSON: {err}') from None
        return cls.from_dict(data)

ProtocolEnvelope = ProtocolMessage

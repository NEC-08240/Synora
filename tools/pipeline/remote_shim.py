# Remote MCP shim for Synora Agent Gateway
import base64
import contextlib
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519
from mcp.server.mcpserver import MCPServer

STATUS_FIELDS = (
    'job_id',
    'developer_id',
    'status',
    'task_type',
    'branch',
    'created_at',
    'updated_at',
    'assigned_at',
    'finished_at',
    'error',
)


class RemoteGatewayClient:
    def __init__(
        self,
        gateway_url: str,
        developer_id: str,
        private_key: ed25519.Ed25519PrivateKey,
        ca_certfile: Optional[str] = None,
        timeout: float = 30.0,
        custom_client: Optional[Any] = None,
    ):
        self.gateway_url = gateway_url.rstrip('/')
        self.developer_id = developer_id
        self.private_key = private_key
        self.ca_certfile = ca_certfile
        self.timeout = timeout
        self.token: Optional[str] = None
        self.token_expiry: float = 0.0
        self._custom_client = custom_client

    @contextlib.contextmanager
    def _session(self):
        if self._custom_client is not None:
            yield self._custom_client
        else:
            verify = self.ca_certfile if self.ca_certfile else True
            with httpx.Client(timeout=self.timeout, verify=verify) as client:
                yield client

    def authenticate(self) -> str:
        with self._session() as client:
            chal_res = client.post(
                f'{self.gateway_url}/auth/challenge',
                json={'developer_id': self.developer_id},
            )
            if chal_res.status_code != 200:
                raise RuntimeError(f'Challenge request failed ({chal_res.status_code}): {chal_res.text}')

            data = chal_res.json()
            nonce = data['nonce']
            message = data['message']

            sig_raw = self.private_key.sign(message.encode('utf-8'))
            sig_b64 = base64.b64encode(sig_raw).decode('ascii')

            verify_res = client.post(
                f'{self.gateway_url}/auth/verify',
                json={'developer_id': self.developer_id, 'nonce': nonce, 'signature': sig_b64},
            )
            if verify_res.status_code != 200:
                raise RuntimeError(f'Authentication failed ({verify_res.status_code}): {verify_res.text}')

            token = verify_res.json()['token']
            self.token = token
            self.token_expiry = time.time() + 3500.0  # Session lasts 3600s
            return token

    def ensure_token(self) -> str:
        if not self.token or time.time() >= self.token_expiry:
            return self.authenticate()
        return self.token

    def submit_task(
        self,
        task: str,
        task_type: str = 'docs',
        branch: str = 'feature/task',
        base_commit: str = 'abc1234',
        diff: str = '',
        is_repair: bool = False,
        local_evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = self.ensure_token()
        payload = {
            'developer_id': self.developer_id,
            'task': task,
            'task_type': task_type,
            'branch': branch,
            'base_commit': base_commit,
            'diff': diff,
            'is_repair': is_repair,
            'local_evidence': local_evidence,
        }
        with self._session() as client:
            res = client.post(
                f'{self.gateway_url}/jobs',
                headers={'Authorization': f'Bearer {token}'},
                json=payload,
            )
            if res.status_code not in (200, 201):
                return {'success': False, 'error': res.json().get('error', res.text)}
            return res.json()

    def get_status(self, job_id: str) -> Dict[str, Any]:
        token = self.ensure_token()
        with self._session() as client:
            res = client.get(
                f'{self.gateway_url}/jobs/{job_id}',
                headers={'Authorization': f'Bearer {token}'},
            )
            if res.status_code != 200:
                return {'error': res.json().get('error', res.text)}
            return res.json()

    def get_result(self, job_id: str) -> Dict[str, Any]:
        token = self.ensure_token()
        with self._session() as client:
            res = client.get(
                f'{self.gateway_url}/jobs/{job_id}/result',
                headers={'Authorization': f'Bearer {token}'},
            )
            if res.status_code != 200:
                return {'error': res.json().get('error', res.text)}
            return res.json()

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        token = self.ensure_token()
        with self._session() as client:
            res = client.post(
                f'{self.gateway_url}/jobs/{job_id}/cancel',
                headers={'Authorization': f'Bearer {token}'},
            )
            if res.status_code != 200:
                return {'error': res.json().get('error', res.text)}
            return res.json()


mcp = MCPServer(name='synora-remote-bridge')
_client_instance: Optional[RemoteGatewayClient] = None


def _get_client() -> RemoteGatewayClient:
    global _client_instance
    if _client_instance is not None:
        return _client_instance

    url = os.environ.get('SYNORA_GATEWAY_URL')
    if not url:
        raise ValueError('SYNORA_GATEWAY_URL environment variable is required.')
    dev_id = os.environ.get('SYNORA_DEVELOPER_ID')
    if not dev_id:
        raise ValueError('SYNORA_DEVELOPER_ID environment variable is required.')

    key_b64 = os.environ.get('SYNORA_DEVELOPER_PRIVATE_KEY_B64')
    key_file = os.environ.get('SYNORA_DEVELOPER_KEY_FILE')

    if key_b64:
        raw_key = base64.b64decode(key_b64.strip())
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_key)
    elif key_file and os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(f.read())
    else:
        raise ValueError('SYNORA_DEVELOPER_PRIVATE_KEY_B64 or valid SYNORA_DEVELOPER_KEY_FILE required.')

    ca_cert = os.environ.get('SYNORA_CA_CERT')
    _client_instance = RemoteGatewayClient(
        gateway_url=url,
        developer_id=dev_id,
        private_key=priv_key,
        ca_certfile=ca_cert,
    )
    return _client_instance


def _reply(data: Any) -> str:
    return json.dumps(data, indent=2)


@mcp.tool()
def submit_task(
    task: str,
    task_type: str = 'docs',
    branch: str = 'feature/task',
    base_commit: str = 'abc1234',
    diff: str = '',
    is_repair: bool = False,
) -> str:
    """Submit a task to the remote Synora Gateway."""
    try:
        client = _get_client()
        res = client.submit_task(
            task=task,
            task_type=task_type,
            branch=branch,
            base_commit=base_commit,
            diff=diff,
            is_repair=is_repair,
        )
        return _reply(res)
    except Exception as err:
        return _reply({'success': False, 'error': str(err)})


@mcp.tool()
def get_status(job_id: str) -> str:
    """Get the status of a job from the remote Synora Gateway."""
    try:
        client = _get_client()
        res = client.get_status(job_id)
        return _reply(res)
    except Exception as err:
        return _reply({'error': str(err)})


@mcp.tool()
def get_result(job_id: str) -> str:
    """Get the result of a finished job from the remote Synora Gateway."""
    try:
        client = _get_client()
        res = client.get_result(job_id)
        return _reply(res)
    except Exception as err:
        return _reply({'error': str(err)})


def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()

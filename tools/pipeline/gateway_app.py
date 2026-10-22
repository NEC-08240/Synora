# Starlette HTTP & WebSocket application for Synora Agent Gateway
import json
from datetime import datetime, timezone
from typing import Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth import AuthenticationError
from .authorization import AuthorizationError
from .contribution_gate import ContributionGateError
from .gateway import Gateway
from .protocol import (
    MSG_HEARTBEAT,
    MSG_JOB_ACK,
    MSG_JOB_ASSIGN,
    MSG_JOB_FAILURE,
    MSG_JOB_PROGRESS,
    MSG_JOB_RESULT,
    MSG_WORKER_DISCONNECT,
    MSG_WORKER_REGISTER,
    ProtocolEnvelope,
    ProtocolError,
)
from .queue import QueueFullError, RateLimitExceeded
from .result_envelope import (
    InvalidResultSignature,
    ResultEnvelopeError,
    ResultExpired,
    ResultMismatchError,
    ResultReplayDetected,
)
from .team_registry import DeveloperNotFound, RegistryError
from .worker_registry import WorkerNotFound, WorkerRegistryError

MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024  # 2 MB


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Enforce content length ceiling
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse({'error': 'Payload Too Large', 'max_bytes': MAX_REQUEST_BODY_BYTES}, status_code=413)

        response: Response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        return response


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        raise AuthenticationError('Missing Authorization header.')
    parts = auth_header.split(' ', 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise AuthenticationError('Authorization header must use Bearer scheme.')
    return parts[1].strip()


def create_gateway_app(gateway: Gateway) -> Starlette:
    async def handle_challenge(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({'error': 'Malformed JSON body.'}, status_code=400)

        dev_id = body.get('developer_id')
        if not dev_id:
            return JSONResponse({'error': 'developer_id is required.'}, status_code=400)

        try:
            challenge = gateway.request_challenge(dev_id)
            return JSONResponse(challenge, status_code=200)
        except DeveloperNotFound as err:
            return JSONResponse({'error': str(err)}, status_code=404)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=403)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_verify(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({'error': 'Malformed JSON body.'}, status_code=400)

        dev_id = body.get('developer_id')
        nonce = body.get('nonce')
        sig = body.get('signature')
        if not dev_id or not nonce or not sig:
            return JSONResponse({'error': 'developer_id, nonce, and signature are required.'}, status_code=400)

        try:
            token = gateway.authenticate(dev_id, nonce, sig)
            return JSONResponse({'token': token, 'developer_id': dev_id}, status_code=200)
        except DeveloperNotFound as err:
            return JSONResponse({'error': str(err)}, status_code=404)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_submit_job(request: Request):
        try:
            token = _extract_bearer_token(request)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({'error': 'Malformed JSON body.'}, status_code=400)

        try:
            res = gateway.submit_job(token, body)
            return JSONResponse(res, status_code=201)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)
        except (AuthorizationError, PermissionError) as err:
            return JSONResponse({'error': str(err)}, status_code=403)
        except (ContributionGateError, ValueError) as err:
            err_str = str(err).lower()
            if 'not authorized' in err_str:
                return JSONResponse({'error': str(err)}, status_code=403)
            if 'exceeds maximum allowed' in err_str:
                return JSONResponse({'error': str(err)}, status_code=413)
            return JSONResponse({'error': str(err)}, status_code=400)
        except RateLimitExceeded as err:
            return JSONResponse({'error': str(err)}, status_code=429)
        except QueueFullError as err:
            return JSONResponse({'error': str(err)}, status_code=503)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_get_job(request: Request):
        try:
            token = _extract_bearer_token(request)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)

        job_id = request.path_params.get('job_id')
        try:
            job = gateway.get_status(token, job_id)
            return JSONResponse(job, status_code=200)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)
        except KeyError as err:
            return JSONResponse({'error': str(err)}, status_code=404)
        except AuthorizationError as err:
            return JSONResponse({'error': str(err)}, status_code=403)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_get_result(request: Request):
        try:
            token = _extract_bearer_token(request)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)

        job_id = request.path_params.get('job_id')
        try:
            res = gateway.get_result(token, job_id)
            return JSONResponse(res, status_code=200)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)
        except KeyError as err:
            return JSONResponse({'error': str(err)}, status_code=404)
        except AuthorizationError as err:
            return JSONResponse({'error': str(err)}, status_code=403)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_cancel_job(request: Request):
        try:
            token = _extract_bearer_token(request)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)

        job_id = request.path_params.get('job_id')
        try:
            res = gateway.cancel_job(token, job_id)
            return JSONResponse(res, status_code=200)
        except AuthenticationError as err:
            return JSONResponse({'error': str(err)}, status_code=401)
        except (KeyError, RuntimeError) as err:
            return JSONResponse({'error': str(err)}, status_code=400)
        except AuthorizationError as err:
            return JSONResponse({'error': str(err)}, status_code=403)
        except Exception as err:
            return JSONResponse({'error': str(err)}, status_code=500)

    async def handle_health(request: Request):
        return JSONResponse(
            {
                'status': 'HEALTHY',
                'service': 'Synora Agent Gateway',
                'timestamp': datetime.now(timezone.utc).isoformat(),
            },
            status_code=200,
        )

    async def handle_worker_status(request: Request):
        status = gateway.get_worker_status()
        return JSONResponse(status, status_code=200)

    async def worker_ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        current_worker_id: Optional[str] = None
        try:
            # Expect initial register or auth message
            init_data = await websocket.receive_json()
            msg_type = init_data.get('message_type')
            payload = init_data.get('payload', {})

            if msg_type != MSG_WORKER_REGISTER:
                await websocket.send_json({'error': 'First message must be WORKER_REGISTER.'})
                await websocket.close(code=1008)
                return

            worker_id = payload.get('worker_id')
            if not worker_id:
                await websocket.send_json({'error': 'worker_id is required in registration.'})
                await websocket.close(code=1008)
                return

            try:
                worker_entry = gateway.worker_registry.get(worker_id)
                if not worker_entry.is_active():
                    await websocket.send_json({'error': f'Worker {worker_id} is suspended.'})
                    await websocket.close(code=1008)
                    return
            except WorkerNotFound:
                await websocket.send_json({'error': f'Worker {worker_id} is not registered.'})
                await websocket.close(code=1008)
                return

            current_worker_id = worker_id
            gateway.register_worker(worker_id, 'ws-session', payload.get('capabilities', {}))
            await websocket.send_json({
                'message_type': 'WORKER_REGISTER_ACK',
                'status': 'REGISTERED',
                'worker_id': worker_id,
            })

            # Main bidirectional event loop
            while True:
                msg = await websocket.receive_json()
                m_type = msg.get('message_type')
                p = msg.get('payload', {})

                if m_type == MSG_HEARTBEAT:
                    gateway.worker_heartbeat(current_worker_id)
                    await websocket.send_json({
                        'message_type': 'HEARTBEAT_ACK',
                        'worker_id': current_worker_id,
                        'status': 'PONG',
                    })

                elif m_type == 'JOB_POLL':
                    job = gateway.worker_poll_job(current_worker_id)
                    if job:
                        await websocket.send_json({
                            'message_type': MSG_JOB_ASSIGN,
                            'payload': job,
                        })
                    else:
                        await websocket.send_json({
                            'message_type': 'JOB_POLL_EMPTY',
                        })

                elif m_type == MSG_JOB_ACK:
                    job_id = p.get('job_id')
                    if job_id:
                        gateway.queue.update_progress(job_id, current_worker_id, 'RUNNING')

                elif m_type == MSG_JOB_PROGRESS:
                    job_id = p.get('job_id')
                    status = p.get('status', 'RUNNING')
                    error = p.get('error', '')
                    if job_id:
                        gateway.queue.update_progress(job_id, current_worker_id, status, error)

                elif m_type == MSG_JOB_RESULT:
                    # Expect signed result envelope in payload
                    try:
                        res = gateway.worker_submit_signed_result(p)
                        await websocket.send_json({
                            'message_type': 'JOB_RESULT_ACK',
                            'status': 'ACCEPTED',
                            'job_id': p.get('job_id'),
                        })
                    except Exception as err:
                        await websocket.send_json({
                            'message_type': 'JOB_RESULT_REJECTED',
                            'error': str(err),
                            'job_id': p.get('job_id'),
                        })

                elif m_type == MSG_JOB_FAILURE:
                    job_id = p.get('job_id')
                    error = p.get('error', 'Unknown worker failure')
                    if job_id:
                        gateway.worker_submit_failure(current_worker_id, job_id, error)
                        await websocket.send_json({
                            'message_type': 'JOB_FAILURE_ACK',
                            'job_id': job_id,
                        })

                elif m_type == MSG_WORKER_DISCONNECT:
                    break

        except WebSocketDisconnect:
            pass
        finally:
            if current_worker_id:
                gateway.audit.record('WORKER_DISCONNECTED', current_worker_id, {})

    routes = [
        Route('/auth/challenge', handle_challenge, methods=['POST']),
        Route('/auth/verify', handle_verify, methods=['POST']),
        Route('/jobs', handle_submit_job, methods=['POST']),
        Route('/jobs/{job_id}', handle_get_job, methods=['GET']),
        Route('/jobs/{job_id}/result', handle_get_result, methods=['GET']),
        Route('/jobs/{job_id}/cancel', handle_cancel_job, methods=['POST']),
        Route('/health', handle_health, methods=['GET']),
        Route('/worker/status', handle_worker_status, methods=['GET']),
        WebSocketRoute('/ws/worker', worker_ws_endpoint),
    ]

    middleware = [
        Middleware(SecurityHeadersMiddleware),
    ]

    return Starlette(routes=routes, middleware=middleware)

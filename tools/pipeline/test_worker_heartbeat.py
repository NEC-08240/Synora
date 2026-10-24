"""A running job must keep the Worker's heartbeat fresh.

The Gateway marks a Worker offline when its last heartbeat is older than 60 s, and requeues every job that
Worker holds. Before this fix the heartbeat was sent only between jobs, so a Claude run longer than about a
minute (the bridge allows 180 s) got its Worker reaped and its job run again.
Run: python -m unittest tools.pipeline.test_worker_heartbeat -v
"""

import json
import time
import unittest

import websocket

from .worker import OutboundWorker


class FakeSocket:
    """Records outbound messages. recv() times out like websocket-client when nothing arrives."""

    def __init__(self):
        self.sent = []
        self.timeout = None

    def send(self, data):
        self.sent.append(json.loads(data))

    def settimeout(self, seconds):
        self.timeout = seconds

    def recv(self):
        time.sleep(min(self.timeout or 0.05, 0.05))
        raise websocket.WebSocketTimeoutException()


class HeartbeatDuringJobTest(unittest.TestCase):
    def test_heartbeats_are_sent_while_a_job_runs(self):
        # Arrange
        worker = OutboundWorker(worker_id="worker-test", heartbeat_interval=0.2)
        worker._ws = FakeSocket()
        worker._is_connected = True

        def long_job():
            time.sleep(1.2)  # about six heartbeat intervals
            return {"status": "SUCCEEDED"}

        # Act
        result = worker._run_keeping_connection_alive(long_job)

        # Assert
        beats = [m for m in worker._ws.sent if m.get("message_type") == "HEARTBEAT"]
        self.assertEqual(result, {"status": "SUCCEEDED"})
        self.assertGreaterEqual(len(beats), 4, f"expected several heartbeats during the job, got {len(beats)}")


if __name__ == "__main__":
    unittest.main()

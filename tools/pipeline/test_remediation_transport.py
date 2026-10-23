"""F5: Worker transport must be secure by default. Run: python -m unittest tools.pipeline.test_remediation_transport -v"""

import ssl
import sys
import types
import unittest
from unittest import mock

from .transport import certificate_options, normalize_gateway_url
from .worker import OutboundWorker
from .worker_daemon import load_worker_config


def _worker_key_b64():
    import base64
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return base64.b64encode(ed25519.Ed25519PrivateKey.generate().private_bytes_raw()).decode()


class TransportRuleTest(unittest.TestCase):
    def test_f5_1_plain_websocket_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            normalize_gateway_url("ws://gateway.example")
        self.assertIn("wss://", str(caught.exception))

    def test_f5_2_plain_http_is_refused(self):
        with self.assertRaises(ValueError):
            normalize_gateway_url("http://gateway.example")

    def test_f5_3_wss_is_accepted(self):
        self.assertEqual(normalize_gateway_url("wss://gateway.example"), "wss://gateway.example")

    def test_f5_4_plain_transport_needs_the_explicit_lan_flag(self):
        self.assertEqual(normalize_gateway_url("ws://10.0.0.5:8000", allow_insecure=True), "ws://10.0.0.5:8000")
        self.assertEqual(normalize_gateway_url("http://10.0.0.5:8000", allow_insecure=True), "ws://10.0.0.5:8000")

    def test_mixed_case_and_https_are_upgraded_never_downgraded(self):
        self.assertEqual(normalize_gateway_url("WSS://GW.example/"), "wss://GW.example")
        self.assertEqual(normalize_gateway_url("https://gw.example"), "wss://gw.example")

    def test_malformed_and_smuggled_urls_are_refused(self):
        bad = [
            "", " wss://gw.example", "wss://gw.example ", "wss://gw.example\n", "wss://gw.example\x00",
            "wss://", "ftp://gw.example", "file:///etc/passwd", "wss://user:pass@gw.example",
            "wss://gw.example?next=ws://evil", "wss://gw.example#frag", "javascript:alert(1)",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_gateway_url(value)

    def test_f5_6_certificate_verification_is_required_for_wss(self):
        options = certificate_options("wss://gw.example")

        self.assertEqual(options, {"cert_reqs": ssl.CERT_REQUIRED})
        self.assertNotIn(ssl.CERT_NONE, options.values())

    def test_certificate_options_never_disable_verification(self):
        context = ssl.create_default_context()
        self.assertIs(certificate_options("wss://gw.example", context)["context"], context)
        self.assertIsNone(certificate_options("ws://10.0.0.5:8000", None))


class DaemonConfigTest(unittest.TestCase):
    def _env(self, **extra):
        return {"SYNORA_WORKER_PRIVATE_KEY_B64": _worker_key_b64(), "SYNORA_GATEWAY_URL": "wss://gw.example", **extra}

    def test_f5_1_daemon_refuses_ws_by_default(self):
        with self.assertRaises(ValueError):
            load_worker_config(self._env(SYNORA_GATEWAY_URL="ws://gw.example"))

    def test_f5_2_daemon_refuses_http_by_default(self):
        with self.assertRaises(ValueError):
            load_worker_config(self._env(SYNORA_GATEWAY_URL="http://gw.example"))

    def test_f5_3_daemon_accepts_wss(self):
        cfg = load_worker_config(self._env())
        self.assertEqual(cfg["gateway_url"], "wss://gw.example")
        self.assertFalse(cfg["allow_insecure_lan"])

    def test_f5_4_lan_mode_is_explicit_and_exact(self):
        lan = self._env(SYNORA_GATEWAY_URL="ws://10.0.0.5:8000", SYNORA_WORKER_ALLOW_INSECURE_LAN="1")
        self.assertTrue(load_worker_config(lan)["allow_insecure_lan"])

        for value in ("true", "yes", "0", " 1x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_worker_config(self._env(SYNORA_GATEWAY_URL="ws://10.0.0.5:8000", SYNORA_WORKER_ALLOW_INSECURE_LAN=value))

    def test_lan_flag_alone_does_not_allow_plaintext_without_the_flag_value(self):
        with self.assertRaises(ValueError):
            load_worker_config(self._env(SYNORA_GATEWAY_URL="ws://10.0.0.5:8000", SYNORA_WORKER_ALLOW_INSECURE_LAN="0"))


class ConnectionTest(unittest.TestCase):
    def test_connect_uses_wss_with_verification_and_no_downgrade(self):
        captured = {}

        def fake_create_connection(url, sslopt=None, timeout=None, **options):
            captured["url"] = url
            captured["sslopt"] = sslopt
            captured["redirect_limit"] = options.get("redirect_limit")
            raise ConnectionError("stop here: the test only inspects the options")

        fake_module = types.SimpleNamespace(create_connection=fake_create_connection)
        worker = OutboundWorker(worker_id="worker-test", gateway_url="wss://gw.example", private_key=None)
        with mock.patch.dict(sys.modules, {"websocket": fake_module}):
            with self.assertRaises(Exception):
                worker.connect_ws()

        self.assertTrue(captured["url"].startswith("wss://gw.example"))
        self.assertEqual(captured["sslopt"], {"cert_reqs": ssl.CERT_REQUIRED})
        self.assertEqual(captured["redirect_limit"], 0)

    def test_worker_refuses_to_construct_with_plain_transport(self):
        with self.assertRaises(ValueError):
            OutboundWorker(worker_id="worker-test", gateway_url="ws://gw.example", private_key=None)

    def test_job_payload_cannot_change_the_transport(self):
        worker = OutboundWorker(worker_id="worker-test", gateway_url="wss://gw.example", private_key=None)
        job = {"job_id": "j1", "developer_id": "alice", "task": "t", "task_type": "docs", "gateway_url": "ws://evil.example"}

        from .metadata import validate_job_payload

        validate_job_payload(job)
        self.assertEqual(worker.gateway_url, "wss://gw.example")


if __name__ == "__main__":
    unittest.main()

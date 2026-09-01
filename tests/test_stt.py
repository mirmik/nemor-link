"""Tests for the synchronous STT client."""

import unittest
from unittest.mock import Mock, patch

from inference_link.stt import STTClient


def make_client(response, runtime=None):
    service = {
        "name": "test",
        "kind": "stt",
        "backends": [{"url": "http://backend"}],
    }
    if runtime:
        service["runtime"] = runtime
    client = STTClient(service)
    client._session.post = Mock(return_value=response)
    return client


class STTRuntimeTests(unittest.TestCase):
    def test_transcribe_sends_configured_runtime(self):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "hello"}
        client = make_client(response, runtime="stt-gigaam")

        client.transcribe(b"audio")

        headers = client._session.post.call_args.kwargs["headers"]
        self.assertEqual(headers["X-STT-Runtime"], "stt-gigaam")

    def test_transcribe_omits_runtime_header_when_not_configured(self):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "hello"}
        client = make_client(response)

        client.transcribe(b"audio")

        headers = client._session.post.call_args.kwargs["headers"]
        self.assertNotIn("X-STT-Runtime", headers)

    def test_health_headers_include_runtime_and_auth(self):
        service = {
            "name": "test",
            "kind": "stt",
            "runtime": "stt-gigaam",
            "backends": [
                {
                    "url": "http://backend",
                    "_host": {"token": "secret", "host_id": "desktop"},
                }
            ],
        }
        client = STTClient(service)

        headers = client.health_headers(service["backends"][0])

        self.assertEqual(headers["X-STT-Runtime"], "stt-gigaam")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(headers["X-LLM-Proxy-Host-ID"], "desktop")

    @patch("inference_link.pool.requests.Session")
    def test_probe_targets_stt_health_with_runtime(self, session_class):
        response = Mock(status_code=200)
        session_class.return_value.get.return_value = response
        client = make_client(response, runtime="stt-gigaam")

        ok, _latency = client.pool.probe("http://backend")

        self.assertTrue(ok)
        session_class.return_value.get.assert_called_once_with(
            "http://backend/stt/health",
            headers={"X-STT-Runtime": "stt-gigaam"},
            timeout=0.6,
        )


if __name__ == "__main__":
    unittest.main()

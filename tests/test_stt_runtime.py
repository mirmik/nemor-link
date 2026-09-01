import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from inference_link.config import ConfigError, load
from inference_link.stt import STTClient


class STTRuntimeTests(unittest.TestCase):
    def make_client(self):
        return STTClient(
            {
                "name": "gigaam",
                "kind": "stt",
                "backends": [
                    {
                        "url": "https://proxy.example/stt",
                        "runtime": "stt-gigaam",
                        "_host": {"token": "secret", "host_id": "client"},
                    }
                ],
            }
        )

    def test_transcribe_sends_runtime_header(self):
        client = self.make_client()
        response = Mock(status_code=200)
        response.json.return_value = {"text": "ok"}
        try:
            with patch.object(client._session, "post", return_value=response) as post:
                self.assertEqual(client.transcribe(b"audio"), {"text": "ok"})
        finally:
            client.close()

        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["X-STT-Runtime"], "stt-gigaam")
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_health_probe_sends_runtime_header(self):
        client = self.make_client()
        response = Mock(status_code=200)
        session = Mock()
        session.get.return_value = response
        try:
            with patch("inference_link.pool.requests.Session", return_value=session):
                ok, _latency = client.pool.probe("https://proxy.example/stt")
        finally:
            client.close()

        self.assertTrue(ok)
        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["X-STT-Runtime"], "stt-gigaam")
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_runtime_is_rejected_for_non_stt_profile(self):
        config = {
            "profiles": {
                "bad": {
                    "kind": "tts",
                    "backends": [{"url": "https://proxy.example", "runtime": "tts-main"}],
                }
            },
            "defaults": {"tts": "bad"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llm.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load(str(path))


if __name__ == "__main__":
    unittest.main()

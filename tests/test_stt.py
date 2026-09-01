"""Tests for the synchronous STT client."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from inference_link.stt import (
    ENCODED_INITIAL_PROMPT_HEADER,
    INITIAL_PROMPT_HEADER,
    InitialPromptEncodingError,
    STTClient,
    decode_initial_prompt,
)


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


class PromptServerHandler(BaseHTTPRequestHandler):
    received_prompt = None

    def do_POST(self):
        type(self).received_prompt = decode_initial_prompt(self.headers)
        body = json.dumps({"text": "ok"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class STTRuntimeTests(unittest.TestCase):
    def test_transcribe_preserves_ascii_initial_prompt_header(self):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "hello"}
        client = make_client(response)

        client.transcribe(b"audio", initial_prompt="Avalon names")

        headers = client._session.post.call_args.kwargs["headers"]
        self.assertEqual(headers[INITIAL_PROMPT_HEADER], "Avalon names")
        self.assertNotIn(ENCODED_INITIAL_PROMPT_HEADER, headers)
        self.assertEqual(decode_initial_prompt(headers), "Avalon names")

    def test_transcribe_round_trips_unicode_initial_prompt(self):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "привет"}
        client = make_client(response)
        prompt = "Авалон — голосовой ассистент 🎙️"

        client.transcribe(b"audio", initial_prompt=prompt)

        headers = client._session.post.call_args.kwargs["headers"]
        self.assertNotIn(INITIAL_PROMPT_HEADER, headers)
        self.assertTrue(headers[ENCODED_INITIAL_PROMPT_HEADER].startswith("v1:"))
        self.assertTrue(headers[ENCODED_INITIAL_PROMPT_HEADER].isascii())
        self.assertEqual(decode_initial_prompt(headers), prompt)

    def test_server_receives_unicode_initial_prompt_unchanged(self):
        PromptServerHandler.received_prompt = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), PromptServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = STTClient(
            {
                "name": "test",
                "kind": "stt",
                "backends": [
                    {"url": f"http://127.0.0.1:{server.server_port}/stt"}
                ],
            }
        )
        prompt = "Авалон — голосовой ассистент 🎙️"
        try:
            self.assertEqual(
                client.transcribe(b"audio", initial_prompt=prompt), {"text": "ok"}
            )
        finally:
            client._session.close()
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(PromptServerHandler.received_prompt, prompt)

    def test_transcribe_omits_empty_initial_prompt(self):
        response = Mock(status_code=200)
        response.json.return_value = {"text": "hello"}
        client = make_client(response)

        client.transcribe(b"audio", initial_prompt="")

        headers = client._session.post.call_args.kwargs["headers"]
        self.assertNotIn(INITIAL_PROMPT_HEADER, headers)
        self.assertNotIn(ENCODED_INITIAL_PROMPT_HEADER, headers)
        self.assertIsNone(decode_initial_prompt(headers))

    def test_decode_initial_prompt_rejects_malformed_encoded_values(self):
        malformed = (
            "v2:0J/RgNC40LLQtdGC",
            "v1:not base64!",
            "v1://4=",  # invalid UTF-8 bytes
            "v1:кириллица",
        )
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(
                InitialPromptEncodingError
            ):
                decode_initial_prompt({ENCODED_INITIAL_PROMPT_HEADER: value})

    def test_decode_initial_prompt_rejects_ambiguous_headers(self):
        with self.assertRaises(InitialPromptEncodingError):
            decode_initial_prompt(
                {
                    INITIAL_PROMPT_HEADER: "plain",
                    ENCODED_INITIAL_PROMPT_HEADER: "v1:cGxhaW4=",
                }
            )

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

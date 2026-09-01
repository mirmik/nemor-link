"""Tests for the synchronous LLM client."""

import unittest
from unittest.mock import Mock

from inference_link.llm import LLMClient, LLMError


def make_client(response):
    service = {
        "name": "test",
        "kind": "llm",
        "backends": [{"url": "http://backend", "model": "test-model"}],
    }
    client = LLMClient(service)
    client._session.post = Mock(return_value=response)
    return client


class LLMErrorTests(unittest.TestCase):
    def test_chat_error_includes_full_response_body(self):
        body = "error: " + "x" * 500
        response = Mock(status_code=404, text=body)
        client = make_client(response)

        with self.assertRaises(LLMError) as context:
            client.chat([{"role": "user", "content": "hello"}])

        self.assertIn(body, str(context.exception))

    def test_streaming_error_includes_full_response_body(self):
        body = "error: " + "x" * 500
        response = Mock(status_code=404, text=body)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        client = make_client(response)

        with self.assertRaises(LLMError) as context:
            list(client.chat_stream_raw([{"role": "user", "content": "hello"}]))

        self.assertIn(body, str(context.exception))


if __name__ == "__main__":
    unittest.main()

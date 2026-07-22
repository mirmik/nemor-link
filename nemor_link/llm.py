"""LLM client — OpenAI-compatible chat completions with per-backend model/auth."""

import json

import requests

from nemor_link.base import ServiceClient
from nemor_link.tls import prepare_session_for_backend


class LLMClient(ServiceClient):
    """Synchronous OpenAI-compatible chat client.

    chat(...)           → dict (full response)
    chat_stream(...)    → iter of str (content tokens)
    chat_stream_raw(..) → iter of dict (OpenAI SSE chunks)

    Each backend in the pool can carry its own model name; the payload's
    `model` field is taken from whichever backend ends up handling the call.
    """

    def __init__(self, service, timeout=300.0, **pool_kwargs):
        super().__init__(service, **pool_kwargs)
        if self.kind != "llm":
            raise ValueError(f"LLMClient requires kind=llm, got {self.kind!r}")
        self.timeout = timeout
        self._session = requests.Session()

    def active_backend(self):
        return self.pool.active()

    def _endpoint(self, base_url):
        return f"{base_url.rstrip('/')}/v1/chat/completions"

    def _payload(self, backend, messages, **kwargs):
        payload = {"model": backend["model"], "messages": messages}
        payload.update(kwargs)
        return payload

    def chat(self, messages, **kwargs):
        """Non-streaming chat. Returns parsed JSON from the server."""
        last_err = None
        for backend in self.pool.failover_candidates():
            payload = self._payload(backend, messages, **kwargs)
            payload["stream"] = False
            headers = {"Content-Type": "application/json", **self.auth_headers(backend)}
            try:
                request_kwargs = prepare_session_for_backend(self._session, backend)
                resp = self._session.post(
                    self._endpoint(backend["url"]),
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                    **request_kwargs,
                )
                self.pool._mark(backend["url"], resp.status_code < 500)
                if resp.status_code >= 400:
                    raise LLMError(
                        f"{backend['url']} ({backend['model']}) returned "
                        f"{resp.status_code}: {resp.text}"
                    )
                return resp.json()
            except (requests.RequestException, LLMError) as e:
                self.pool._mark(backend["url"], False)
                last_err = e
                continue
        raise LLMError(f"All LLM backends failed for {self.name}: {last_err}")

    def chat_stream_raw(self, messages, **kwargs):
        last_err = None
        for backend in self.pool.failover_candidates():
            payload = self._payload(backend, messages, **kwargs)
            payload["stream"] = True
            headers = {"Content-Type": "application/json", **self.auth_headers(backend)}
            try:
                request_kwargs = prepare_session_for_backend(self._session, backend)
                with self._session.post(
                    self._endpoint(backend["url"]),
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=self.timeout,
                    **request_kwargs,
                ) as resp:
                    self.pool._mark(backend["url"], resp.status_code < 500)
                    if resp.status_code >= 400:
                        raise LLMError(
                            f"{backend['url']} ({backend['model']}) returned "
                            f"{resp.status_code}: {resp.text}"
                        )
                    yield from _parse_sse(resp)
                return
            except (requests.RequestException, LLMError) as e:
                self.pool._mark(backend["url"], False)
                last_err = e
                continue
        raise LLMError(f"All LLM backends failed for {self.name}: {last_err}")

    def chat_stream(self, messages, **kwargs):
        for chunk in self.chat_stream_raw(messages, **kwargs):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


class LLMError(Exception):
    pass


def _parse_sse(response):
    for raw in response.iter_lines(decode_unicode=False):
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue

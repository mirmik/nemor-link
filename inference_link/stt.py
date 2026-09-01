"""STT client and prompt-header codec for the ``/stt`` endpoint."""

import base64
import binascii
import os

import requests

from inference_link.base import ServiceClient
from inference_link.tls import prepare_session_for_backend


INITIAL_PROMPT_HEADER = "X-Initial-Prompt"
ENCODED_INITIAL_PROMPT_HEADER = "X-Initial-Prompt-Encoded"
_INITIAL_PROMPT_ENCODING_PREFIX = "v1:"


class InitialPromptEncodingError(ValueError):
    """An encoded STT initial prompt is malformed or ambiguous."""


def encode_initial_prompt_headers(prompt):
    """Encode an STT prompt into ASCII-safe HTTP headers.

    Printable ASCII keeps the original header for compatibility. Other text is
    UTF-8/Base64 encoded in a versioned header so it can pass through Python's
    latin-1-limited HTTP stack without changing the prompt.
    """
    if prompt is None or prompt == "":
        return {}
    if not isinstance(prompt, str):
        raise TypeError(f"initial_prompt must be str or None, got {type(prompt)}")
    if all(0x20 <= ord(char) <= 0x7E for char in prompt):
        return {INITIAL_PROMPT_HEADER: prompt}
    try:
        payload = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    except UnicodeEncodeError as exc:
        raise InitialPromptEncodingError("initial_prompt is not valid Unicode") from exc
    return {
        ENCODED_INITIAL_PROMPT_HEADER: _INITIAL_PROMPT_ENCODING_PREFIX + payload
    }


def _get_header(headers, name):
    value = headers.get(name)
    if value is not None:
        return value
    lower_name = name.lower()
    for key, candidate in headers.items():
        if key.lower() == lower_name:
            return candidate
    return None


def decode_initial_prompt(headers):
    """Decode the STT prompt headers on a server, returning ``str | None``.

    Servers should turn :class:`InitialPromptEncodingError` into a 400 response.
    Header names are matched case-insensitively.
    """
    plain = _get_header(headers, INITIAL_PROMPT_HEADER)
    encoded = _get_header(headers, ENCODED_INITIAL_PROMPT_HEADER)
    if plain is not None and encoded is not None:
        raise InitialPromptEncodingError(
            "both plain and encoded initial prompt headers are present"
        )
    if encoded is None:
        return plain
    if not isinstance(encoded, str) or not encoded.startswith(
        _INITIAL_PROMPT_ENCODING_PREFIX
    ):
        raise InitialPromptEncodingError("unsupported initial prompt encoding")
    payload = encoded[len(_INITIAL_PROMPT_ENCODING_PREFIX):]
    try:
        prompt_bytes = base64.b64decode(payload, validate=True)
        return prompt_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InitialPromptEncodingError("malformed encoded initial prompt") from exc


class STTClient(ServiceClient):
    """Sync STT client.

    transcribe(audio, initial_prompt=None, timeout=120) → dict
        audio: bytes (raw float32 PCM), str path to file, or file-like.
    """

    def __init__(self, service, timeout=120.0, **pool_kwargs):
        self.runtime = service.get("runtime")
        super().__init__(service, **pool_kwargs)
        if self.kind != "stt":
            raise ValueError(f"STTClient requires kind=stt, got {self.kind!r}")
        self.timeout = timeout
        self._session = requests.Session()
        self.default_prompt = service.get("initial_prompt")

    def runtime_headers(self):
        if not self.runtime:
            return {}
        return {"X-STT-Runtime": self.runtime}

    def health_headers(self, backend):
        return {**self.runtime_headers(), **self.auth_headers(backend)}

    def _endpoint(self, base_url):
        # URLs in config may already include /stt suffix; if not, add it.
        base = base_url.rstrip("/")
        return base if base.endswith("/stt") else base + "/stt"

    def transcribe(self, audio, initial_prompt=None, timeout=None):
        if isinstance(audio, str):
            path = os.path.expanduser(audio)
            with open(path, "rb") as f:
                body = f.read()
        elif isinstance(audio, (bytes, bytearray)):
            body = bytes(audio)
        elif hasattr(audio, "read"):
            body = audio.read()
        else:
            raise TypeError(f"audio must be bytes, path, or file-like, got {type(audio)}")

        headers = {"Content-Type": "application/octet-stream"}
        headers.update(self.runtime_headers())
        prompt = initial_prompt if initial_prompt is not None else self.default_prompt
        headers.update(encode_initial_prompt_headers(prompt))

        last_err = None
        for backend in self.pool.failover_candidates():
            auth = self.auth_headers(backend)
            hdr = {**headers, **auth}
            try:
                request_kwargs = prepare_session_for_backend(self._session, backend)
                resp = self._session.post(
                    self._endpoint(backend["url"]),
                    data=body,
                    headers=hdr,
                    timeout=timeout or self.timeout,
                    **request_kwargs,
                )
                self.pool._mark(backend["url"], resp.status_code < 500)
                if resp.status_code >= 400:
                    raise STTError(
                        f"{backend['url']} returned {resp.status_code}: {resp.text[:300]}"
                    )
                return resp.json()
            except (requests.RequestException, STTError) as e:
                self.pool._mark(backend["url"], False)
                last_err = e
                continue
        raise STTError(f"All STT backends failed for {self.name}: {last_err}")


class STTError(Exception):
    pass

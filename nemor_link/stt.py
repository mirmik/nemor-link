"""STT client — POST audio to /stt endpoint."""

import os

import requests

from nemor_link.base import ServiceClient


class STTClient(ServiceClient):
    """Sync STT client.

    transcribe(audio, initial_prompt=None, timeout=120) → dict
        audio: bytes (raw float32 PCM), str path to file, or file-like.
    """

    def __init__(self, service, timeout=120.0, **pool_kwargs):
        super().__init__(service, **pool_kwargs)
        if self.kind != "stt":
            raise ValueError(f"STTClient requires kind=stt, got {self.kind!r}")
        self.timeout = timeout
        self._session = requests.Session()
        self.default_prompt = service.get("initial_prompt")

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
        prompt = initial_prompt if initial_prompt is not None else self.default_prompt
        if prompt:
            headers["X-Initial-Prompt"] = prompt

        last_err = None
        for backend in self.pool.failover_candidates():
            auth = self.auth_headers(backend)
            hdr = {**headers, **auth}
            try:
                resp = self._session.post(
                    self._endpoint(backend["url"]),
                    data=body,
                    headers=hdr,
                    timeout=timeout or self.timeout,
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

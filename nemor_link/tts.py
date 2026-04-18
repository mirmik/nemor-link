"""TTS client — synthesize speech, returns audio bytes."""

import requests

from nemor_link.base import ServiceClient


class TTSClient(ServiceClient):
    """Sync TTS client.

    synthesize(text, ...) → bytes (raw audio, typically float32 PCM from XTTS)
    """

    def __init__(self, service, timeout=120.0, **pool_kwargs):
        super().__init__(service, **pool_kwargs)
        if self.kind != "tts":
            raise ValueError(f"TTSClient requires kind=tts, got {self.kind!r}")
        self.timeout = timeout
        self._session = requests.Session()
        self.default_language = service.get("language")
        self.default_speed = float(service.get("speed", 1.0))
        self.default_temperature = float(service.get("temperature", 0.75))
        self.sample_rate = int(service.get("sample_rate", 24000))

    def _endpoint(self, base_url):
        base = base_url.rstrip("/")
        if base.endswith("/tts"):
            return base + "/generate"
        if base.endswith("/v1/audio/speech"):
            return base  # full OpenAI-style URL
        return base + "/tts/generate"

    def synthesize(self, text, language=None, speed=None, temperature=None, timeout=None):
        payload = {
            "text": text,
            "language": language or self.default_language,
            "speed": speed if speed is not None else self.default_speed,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        last_err = None
        for backend in self.pool.failover_candidates():
            headers = {"Content-Type": "application/json", **self.auth_headers(backend)}
            try:
                resp = self._session.post(
                    self._endpoint(backend["url"]),
                    json=payload,
                    headers=headers,
                    timeout=timeout or self.timeout,
                )
                self.pool._mark(backend["url"], resp.status_code < 500)
                if resp.status_code >= 400:
                    raise TTSError(
                        f"{backend['url']} returned {resp.status_code}: {resp.text[:300]}"
                    )
                return resp.content
            except (requests.RequestException, TTSError) as e:
                self.pool._mark(backend["url"], False)
                last_err = e
                continue
        raise TTSError(f"All TTS backends failed for {self.name}: {last_err}")


class TTSError(Exception):
    pass

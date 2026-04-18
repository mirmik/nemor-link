"""nemor-link — unified client for local LLM/STT/TTS services.

Quick start:
    import nemor_link as nl
    llm = nl.llm()                     # default LLM
    print(llm.chat([{"role": "user", "content": "hi"}])["choices"][0]["message"]["content"])

    for token in llm.chat_stream([{"role": "user", "content": "hi"}]):
        print(token, end="", flush=True)

    stt = nl.stt()
    print(stt.transcribe(open("audio.raw", "rb").read()))

    tts = nl.tts()
    audio = tts.synthesize("hello")
"""

from nemor_link.config import ConfigError, load, resolve_service
from nemor_link.llm import LLMClient, LLMError
from nemor_link.stt import STTClient, STTError
from nemor_link.tts import TTSClient, TTSError
from nemor_link.pool import ServicePool


__all__ = [
    "llm", "stt", "tts", "probe",
    "LLMClient", "STTClient", "TTSClient", "ServicePool",
    "ConfigError", "LLMError", "STTError", "TTSError",
    "load_config",
]


_KIND_TO_CLIENT = {
    "llm": LLMClient,
    "stt": STTClient,
    "tts": TTSClient,
}


def load_config(path=None):
    return load(path)


def _build(kind, name=None, tool=None, monitor=False, config=None, **client_kwargs):
    cfg = config or load()
    svc = resolve_service(cfg, name=name, kind=kind, tool=tool)
    return _KIND_TO_CLIENT[kind](svc, monitor=monitor, **client_kwargs)


def llm(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return an LLMClient for the named service (or default)."""
    return _build("llm", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def stt(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return an STTClient."""
    return _build("stt", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def tts(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return a TTSClient."""
    return _build("tts", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def probe(config=None, kind=None):
    """Probe every service (optionally filtered by kind). Returns a dict:

        {service_name: {
            "kind": ..., "active": url,
            "urls": [{"url": ..., "ok": bool, "latency_ms": float}, ...]
        }}
    """
    cfg = config or load()
    report = {}
    for name, svc in cfg["services"].items():
        if kind and svc["kind"] != kind:
            continue
        resolved = resolve_service(cfg, name=name)
        client = _KIND_TO_CLIENT[svc["kind"]](resolved)
        try:
            results = client.pool.probe_all()
        finally:
            client.close()
        by_url = {b["url"]: b for b in resolved["backends"]}
        report[name] = {
            "kind": svc["kind"],
            "active": client.pool.active_url(),
            "backends": [
                {
                    "url": url,
                    "model": by_url[url].get("model"),
                    "auth": by_url[url].get("auth"),
                    "ok": ok,
                    "latency_ms": round(latency * 1000, 1) if latency is not None else None,
                }
                for url, ok, latency in results
            ],
        }
    return report

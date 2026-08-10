"""nemor-link — trusted connection to local LLM/STT/TTS services.

Quick start:
    import nemor_link as nl
    llm = nl.llm()                     # default LLM profile
    print(llm.chat([{"role": "user", "content": "hi"}])["choices"][0]["message"]["content"])

    for token in llm.chat_stream([{"role": "user", "content": "hi"}]):
        print(token, end="", flush=True)

    stt = nl.stt()
    print(stt.transcribe(open("audio.raw", "rb").read()))

    tts = nl.tts()
    audio = tts.synthesize("hello")
"""

from nemor_link.config import ConfigError, load, resolve_profile
from nemor_link.llm import LLMClient, LLMError
from nemor_link.stt import STTClient, STTError
from nemor_link.tts import TTSClient, TTSError
from nemor_link.pool import ServicePool
from nemor_link.connection import (
    AuthenticationRequired,
    LinkError,
    ModelNotSelected,
    NotConnected,
    ServerIdentityChanged,
    ServerUnavailable,
    add_connection_arguments,
    handle_connection_action,
)


__all__ = [
    "llm", "stt", "tts", "probe",
    "LLMClient", "STTClient", "TTSClient", "ServicePool",
    "ConfigError", "LinkError", "NotConnected", "ModelNotSelected",
    "AuthenticationRequired", "ServerIdentityChanged", "ServerUnavailable",
    "LLMError", "STTError", "TTSError",
    "add_connection_arguments", "handle_connection_action",
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
    if config is not None or name is not None:
        cfg = config or load()
        prof = resolve_profile(cfg, name=name, kind=kind, tool=tool)
    else:
        from nemor_link.connection import resolved_service
        prof = resolved_service(kind, command=tool)
    return _KIND_TO_CLIENT[kind](prof, monitor=monitor, **client_kwargs)


def llm(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return an LLMClient for the named profile (or default)."""
    return _build("llm", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def stt(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return an STTClient."""
    return _build("stt", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def tts(name=None, tool=None, monitor=False, config=None, **kwargs):
    """Return a TTSClient."""
    return _build("tts", name=name, tool=tool, monitor=monitor, config=config, **kwargs)


def probe(config=None, kind=None):
    """Probe every profile (optionally filtered by kind). Returns a dict:

        {profile_name: {
            "kind": ..., "active": url,
            "backends": [{url, model, auth, ok, latency_ms}, ...]
        }}
    """
    cfg = config or load()
    report = {}
    for name, prof in cfg["profiles"].items():
        if kind and prof["kind"] != kind:
            continue
        resolved = resolve_profile(cfg, name=name)
        client = _KIND_TO_CLIENT[prof["kind"]](resolved)
        try:
            results = client.pool.probe_all()
        finally:
            client.close()
        by_url = {b["url"]: b for b in resolved["backends"]}
        report[name] = {
            "kind": prof["kind"],
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

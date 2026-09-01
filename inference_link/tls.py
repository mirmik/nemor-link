"""HTTPS helpers for self-signed backends with fingerprint pinning."""

import re
import ssl
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter


_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def backend_fingerprint(backend):
    value = (
        backend.get("tls_fingerprint")
        or backend.get("server_fingerprint")
        or backend.get("fingerprint")
    )
    return normalize_fingerprint(value) if value else None


def normalize_fingerprint(value):
    compact = str(value or "").strip().lower().replace(":", "")
    if not _FINGERPRINT_RE.match(compact):
        raise ValueError("TLS fingerprint must be a SHA-256 hex digest")
    return ":".join(compact[i:i + 2] for i in range(0, len(compact), 2))


def prepare_session_for_backend(session, backend):
    fingerprint = backend_fingerprint(backend)
    if not fingerprint:
        return {}
    prefix = _mount_prefix(backend["url"])
    session.mount(prefix, FingerprintAdapter(fingerprint))
    return {"verify": False}


class FingerprintAdapter(HTTPAdapter):
    """Requests adapter that trusts only the certificate with this fingerprint."""

    def __init__(self, fingerprint, *args, **kwargs):
        self.fingerprint = normalize_fingerprint(fingerprint)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs.update(_pool_kwargs(self.fingerprint))
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs.update(_pool_kwargs(self.fingerprint))
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _pool_kwargs(fingerprint):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return {
        "assert_fingerprint": fingerprint,
        "ssl_context": context,
    }


def _mount_prefix(url):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return url.rstrip("/") + "/"
    return f"{parsed.scheme}://{parsed.netloc}/"

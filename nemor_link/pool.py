"""ServicePool — priority list of backends with health probing and failover.

Each backend is a dict with at least `url` and (for LLM) `model`, and may
carry its own `auth` / `_host`. The pool tracks reachability per URL and
picks the highest-priority reachable backend.
"""

import threading
import time
from urllib.parse import urlparse, urlunparse

import requests

from nemor_link.tls import prepare_session_for_backend


DEFAULT_HEALTH_PATH = {
    "llm": "/health",
    "stt": "/health",
    "tts": "/health",
}


def derive_health_url(url, health_path="/health"):
    """Convert 'http://host:port/some/endpoint' → 'http://host:port{health_path}'."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, health_path, "", "", ""))


class ServicePool:
    """Holds a priority list of backends and tracks which URLs are reachable."""

    def __init__(
        self,
        name,
        backends,
        kind="llm",
        health_path=None,
        health_timeout=0.6,
        check_interval=2.0,
    ):
        if not backends:
            raise ValueError(f"ServicePool {name!r} needs at least one backend")
        self.name = name
        self.kind = kind
        # Preserve order, key by url
        self.backends = [dict(b) for b in backends]
        self.urls = [b["url"] for b in self.backends]
        self._by_url = {b["url"]: b for b in self.backends}

        self.health_path = health_path or DEFAULT_HEALTH_PATH.get(kind, "/health")
        self.health_timeout = float(health_timeout)
        self.check_interval = float(check_interval)

        self._lock = threading.Lock()
        self._healthy = {u: None for u in self.urls}
        self._active_url = self.urls[0]
        self._monitor_thread = None
        self._monitor_stop = threading.Event()

    def health_url(self, url):
        return derive_health_url(url, self.health_path)

    def probe(self, url):
        """Single probe. Returns (ok: bool, latency_sec: float)."""
        started = time.perf_counter()
        try:
            backend = self._by_url[url]
            session = requests.Session()
            request_kwargs = prepare_session_for_backend(session, backend)
            resp = session.get(
                self.health_url(url),
                timeout=self.health_timeout,
                **request_kwargs,
            )
            ok = resp.status_code < 500  # 401 (auth gate) also counts as alive
        except requests.RequestException:
            ok = False
        elapsed = time.perf_counter() - started
        self._mark(url, ok)
        return ok, elapsed

    def probe_all(self):
        return [(u, *self.probe(u)) for u in self.urls]

    def _mark(self, url, ok):
        with self._lock:
            self._healthy[url] = ok
            self._active_url = self._best_available_locked()

    def _best_available_locked(self, exclude=None):
        exclude = exclude or set()
        for u in self.urls:
            if u in exclude:
                continue
            if self._healthy.get(u) is not False:
                return u
        for u in self.urls:
            if u not in exclude:
                return u
        return self.urls[0]

    def active(self):
        """Return the currently active backend dict."""
        with self._lock:
            return dict(self._by_url[self._active_url])

    def active_url(self):
        with self._lock:
            return self._active_url

    def failover_candidates(self):
        """Ordered list of backend dicts to try: active first, then others."""
        with self._lock:
            active = self._active_url
            out = [dict(self._by_url[active])]
            for u in self.urls:
                if u != active:
                    out.append(dict(self._by_url[u]))
            return out

    def status(self):
        with self._lock:
            return {
                "name": self.name,
                "kind": self.kind,
                "active": self._active_url,
                "backends": [
                    {
                        "url": b["url"],
                        "model": b.get("model"),
                        "auth": b.get("auth"),
                        "healthy": self._healthy[b["url"]],
                    }
                    for b in self.backends
                ],
            }

    # --- background monitoring ---

    def start_monitor(self):
        if self._monitor_thread is not None:
            return
        self._monitor_stop.clear()
        t = threading.Thread(
            target=self._monitor_loop, daemon=True, name=f"pool-{self.name}"
        )
        t.start()
        self._monitor_thread = t

    def stop_monitor(self):
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1.0)
            self._monitor_thread = None

    def _monitor_loop(self):
        while not self._monitor_stop.is_set():
            preferred = self.urls[0]
            for url in self.urls:
                if self._monitor_stop.is_set():
                    return
                ok, _ = self.probe(url)
                if url == preferred and ok:
                    break
            self._monitor_stop.wait(self.check_interval)

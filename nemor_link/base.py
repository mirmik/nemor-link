"""Common base for service clients."""

from nemor_link.pool import ServicePool


class ServiceClient:
    """Base class: holds a pool of backends, per-backend auth.

    Subclasses implement the actual API calls (chat, transcribe, synthesize).
    """

    def __init__(self, service, monitor=False, health_timeout=0.6, check_interval=2.0):
        """service: dict produced by config.resolve_service()."""
        self.service = service
        self.name = service["name"]
        self.kind = service["kind"]
        self.pool = ServicePool(
            self.name,
            service["backends"],
            kind=self.kind,
            health_timeout=health_timeout,
            check_interval=check_interval,
        )
        if monitor:
            self.pool.start_monitor()

    def auth_headers(self, backend):
        """Return auth headers for a specific backend (uses its _host)."""
        host = backend.get("_host")
        if not host or not host.get("token"):
            return {}
        headers = {"Authorization": f"Bearer {host['token']}"}
        if host.get("host_id"):
            headers["X-LLM-Proxy-Host-ID"] = host["host_id"]
        return headers

    def close(self):
        self.pool.stop_monitor()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

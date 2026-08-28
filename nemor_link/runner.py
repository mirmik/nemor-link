"""Run OpenAI-compatible applications through a trusted Nemor connection."""

import json
import os
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from nemor_link.connection import LinkError
from nemor_link.tls import prepare_session_for_backend


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class OpenAIRelay:
    def __init__(self, backend):
        self.token = secrets.token_urlsafe(32)
        self.server = _RelayServer(("127.0.0.1", 0), backend, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def run_command(command, service):
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise LinkError("run requires a command after --")

    backend = service["backends"][0]
    with OpenAIRelay(backend) as relay:
        env = os.environ.copy()
        env.update(
            OPENAI_API_KEY=relay.token,
            OPENAI_BASE_URL=relay.base_url,
            OPENAI_MODEL=backend["model"],
        )
        try:
            return subprocess.run(command, env=env).returncode
        except OSError as exc:
            raise LinkError(f"Cannot run {command[0]!r}: {exc}") from exc


class _RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, backend, token):
        self.backend = backend
        self.token = token
        super().__init__(address, _RelayHandler)


class _RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_DELETE(self):
        self._proxy()

    def do_GET(self):
        self._proxy()

    def do_HEAD(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def log_message(self, _format, *_args):
        pass

    def _proxy(self):
        if self.headers.get("Authorization") != f"Bearer {self.server.token}":
            self._send_json(401, {"error": "invalid relay token"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower()
            not in _HOP_BY_HOP_HEADERS | {"authorization", "content-length", "host"}
        }
        token = (self.server.backend.get("_host") or {}).get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        session = requests.Session()
        response_started = False
        try:
            request_kwargs = prepare_session_for_backend(session, self.server.backend)
            response = session.request(
                self.command,
                self.server.backend["url"].rstrip("/") + self.path,
                data=body,
                headers=headers,
                stream=True,
                timeout=(10, None),
                allow_redirects=False,
                **request_kwargs,
            )
            with response:
                self.send_response(response.status_code)
                for name, value in response.headers.items():
                    if name.lower() not in _HOP_BY_HOP_HEADERS | {
                        "content-encoding",
                        "content-length",
                    }:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                response_started = True
                if self.command != "HEAD":
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
        except (requests.RequestException, OSError) as exc:
            if not response_started:
                self._send_json(502, {"error": f"Nemor upstream failed: {exc}"})
        finally:
            self.close_connection = True
            session.close()

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

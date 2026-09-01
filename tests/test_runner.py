import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import requests

from inference_link.cli import build_parser, deprecated_main
from inference_link.runner import OpenAIRelay, run_command


class UpstreamHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.server.request_body = self.rfile.read(length)
        self.server.authorization = self.headers.get("Authorization")
        body = b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


def test_relay_forwards_stream_and_upstream_token():
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    backend = {
        "url": f"http://127.0.0.1:{upstream.server_port}",
        "model": "test-model",
        "_host": {"token": "upstream-token"},
    }
    try:
        with OpenAIRelay(backend) as relay:
            unauthorized = requests.post(
                relay.base_url + "/chat/completions",
                json={"model": "test-model", "messages": []},
            )
            response = requests.post(
                relay.base_url + "/chat/completions",
                headers={"Authorization": f"Bearer {relay.token}"},
                json={"model": "test-model", "messages": []},
            )
        assert unauthorized.status_code == 401
        assert response.status_code == 200
        assert "data: [DONE]" in response.text
        assert upstream.authorization == "Bearer upstream-token"
        assert json.loads(upstream.request_body)["model"] == "test-model"
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join()


def test_run_command_exports_openai_environment_and_returns_exit_code():
    service = {
        "backends": [
            {
                "url": "http://upstream",
                "model": "test-model",
                "_host": {"token": "upstream-token"},
            }
        ]
    }
    completed = SimpleNamespace(returncode=17)
    with patch.object(subprocess, "run", return_value=completed) as run:
        result = run_command(["example", "arg"], service)

    assert result == 17
    assert run.call_args.args[0] == ["example", "arg"]
    env = run.call_args.kwargs["env"]
    assert env["OPENAI_MODEL"] == "test-model"
    assert env["OPENAI_BASE_URL"].startswith("http://127.0.0.1:")
    assert env["OPENAI_API_KEY"]
    assert env["OPENAI_API_KEY"] != "upstream-token"


def test_run_cli_preserves_child_arguments():
    args = build_parser().parse_args(
        ["--app", "qwen", "run", "--", "qwen", "--approval-mode", "auto-edit"]
    )

    assert args.app == "qwen"
    assert args.command_args == ["--", "qwen", "--approval-mode", "auto-edit"]


def test_deprecated_cli_warns_and_delegates(capsys):
    with patch("inference_link.cli.main") as main:
        deprecated_main()

    main.assert_called_once_with()
    assert "renamed to 'inference-link'" in capsys.readouterr().err

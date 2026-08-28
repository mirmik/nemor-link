"""Tests for machine-managed connection state and onboarding actions."""

import os
import tempfile
import unittest
import socket
from types import SimpleNamespace
from unittest.mock import patch

from nemor_link.connection import (
    AuthenticationRequired,
    ModelNotSelected,
    NotConnected,
    handle_connection_action,
    normalize_server_url,
    resolved_service,
    server_key,
    set_model,
    trust_server,
    _certificate_fingerprint,
)
from nemor_link.state import StateStore


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = StateStore(os.path.join(self.temporary.name, "state.json"))

    def tearDown(self):
        self.temporary.cleanup()

    def observation(self):
        return {
            "endpoint": "https://192.168.0.90:8090",
            "fingerprint": "ab:" * 31 + "ab",
            "capabilities": {"protocol": 1, "services": {"llm": True}},
        }

    def test_bare_address_uses_https_and_default_port(self):
        self.assertEqual(
            normalize_server_url("192.168.0.90"),
            "https://192.168.0.90:8090",
        )

    def test_new_state_is_not_connected(self):
        with self.assertRaisesRegex(NotConnected, r"commit --connect"):
            resolved_service("llm", store=self.store, command="commit")

    def test_trusted_server_needs_model(self):
        trust_server(self.observation(), store=self.store, command="commit")
        with self.assertRaisesRegex(ModelNotSelected, r"commit --list-models"):
            resolved_service("llm", store=self.store, command="commit")

    def test_authentication_is_requested_before_creating_client(self):
        observation = self.observation()
        observation["capabilities"]["auth_required"] = True
        trust_server(observation, store=self.store, command="commit")
        with self.assertRaisesRegex(AuthenticationRequired, r"commit --set-token"):
            resolved_service("llm", store=self.store, command="commit")

    def test_resolved_service_contains_pin_token_and_model(self):
        trust_server(self.observation(), store=self.store, command="commit")
        state = self.store.load()
        state["applications"]["commit"]["token"] = "secret"
        state["applications"]["commit"]["model"] = "very-good-model"
        self.store.save(state)

        service = resolved_service("llm", store=self.store, command="commit")

        backend = service["backends"][0]
        self.assertEqual(backend["model"], "very-good-model")
        self.assertEqual(backend["_host"], {"token": "secret"})
        self.assertEqual(backend["tls_fingerprint"], self.observation()["fingerprint"])

    def test_connect_prompts_once_then_recognizes_fingerprint(self):
        args = _args(connect="192.168.0.90")
        output = []
        with patch("nemor_link.connection.inspect_server", return_value=self.observation()):
            handled = handle_connection_action(
                args, "commit", store=self.store,
                input_fn=lambda _prompt: "y", output_fn=output.append,
            )
            handle_connection_action(
                args, "commit", store=self.store,
                input_fn=lambda _prompt: self.fail("known server must not prompt"),
                output_fn=output.append,
            )
        self.assertTrue(handled)
        self.assertIn("This server has not been seen before.", output)
        self.assertEqual(
            self.store.load()["applications"]["commit"]["server"],
            server_key(self.observation()),
        )

    def test_set_model_validates_server_list(self):
        trust_server(self.observation(), store=self.store, command="commit")
        with patch("nemor_link.connection.list_models", return_value=[{"id": "good"}]):
            set_model("good", store=self.store, command="commit")
        self.assertEqual(self.store.load()["applications"]["commit"]["model"], "good")

    def test_applications_have_independent_connections(self):
        trust_server(self.observation(), store=self.store, command="commit")

        with self.assertRaisesRegex(NotConnected, r"ask --connect"):
            resolved_service("llm", store=self.store, command="ask")

    def test_applications_have_independent_tokens_and_models(self):
        observation = self.observation()
        trust_server(observation, store=self.store, command="commit")
        trust_server(observation, store=self.store, command="ask")
        state = self.store.load()
        state["applications"]["commit"].update(token="commit-token", model="commit-model")
        state["applications"]["ask"].update(token="ask-token", model="ask-model")
        self.store.save(state)

        commit_backend = resolved_service(
            "llm", store=self.store, command="commit"
        )["backends"][0]
        ask_backend = resolved_service(
            "llm", store=self.store, command="ask"
        )["backends"][0]

        self.assertEqual(commit_backend["model"], "commit-model")
        self.assertEqual(commit_backend["_host"], {"token": "commit-token"})
        self.assertEqual(ask_backend["model"], "ask-model")
        self.assertEqual(ask_backend["_host"], {"token": "ask-token"})
        server = self.store.load()["servers"][server_key(observation)]
        self.assertNotIn("token", server)
        self.assertNotIn("model", server)

    def test_switching_server_clears_application_token_and_model(self):
        first = self.observation()
        trust_server(first, store=self.store, command="commit")
        state = self.store.load()
        state["applications"]["commit"].update(token="secret", model="model")
        self.store.save(state)
        second = {
            **first,
            "endpoint": "https://192.168.0.91:8090",
            "fingerprint": "cd:" * 31 + "cd",
        }

        trust_server(second, store=self.store, command="commit")

        self.assertEqual(
            self.store.load()["applications"]["commit"],
            {"server": server_key(second)},
        )

    def test_tcp_timeout_is_distinguished_from_tls_timeout(self):
        with patch("nemor_link.connection.socket.create_connection", side_effect=socket.timeout):
            with self.assertRaisesRegex(Exception, r"TCP connection .* timed out"):
                _certificate_fingerprint("192.168.0.61", 8090, 1)


def _args(**overrides):
    values = {
        "connect": None,
        "disconnect": False,
        "link_status": False,
        "list_models": False,
        "set_model": None,
        "set_token": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


if __name__ == "__main__":
    unittest.main()

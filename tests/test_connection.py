"""Tests for machine-managed connection state and onboarding actions."""

import os
import tempfile
import unittest
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
        trust_server(self.observation(), store=self.store)
        with self.assertRaisesRegex(ModelNotSelected, r"commit --list-models"):
            resolved_service("llm", store=self.store, command="commit")

    def test_authentication_is_requested_before_creating_client(self):
        observation = self.observation()
        observation["capabilities"]["auth_required"] = True
        trust_server(observation, store=self.store)
        with self.assertRaisesRegex(AuthenticationRequired, r"commit --set-token"):
            resolved_service("llm", store=self.store, command="commit")

    def test_resolved_service_contains_pin_token_and_model(self):
        trust_server(self.observation(), store=self.store)
        state = self.store.load()
        key = state["active_server"]
        state["servers"][key]["token"] = "secret"
        state["servers"][key]["selections"]["llm"] = "very-good-model"
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
        self.assertEqual(self.store.load()["active_server"], server_key(self.observation()))

    def test_set_model_validates_server_list(self):
        trust_server(self.observation(), store=self.store)
        with patch("nemor_link.connection.list_models", return_value=[{"id": "good"}]):
            set_model("good", store=self.store, command="commit")
        key = self.store.load()["active_server"]
        self.assertEqual(self.store.load()["servers"][key]["selections"]["llm"], "good")


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

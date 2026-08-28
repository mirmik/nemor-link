"""Persistent, machine-managed nemor-link connection state."""

import json
import os
import tempfile

from nemor_link.config import ConfigError


def default_state_path():
    if os.name == "nt" and os.environ.get("APPDATA"):
        root = os.environ["APPDATA"]
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, "nemor-link", "state.json")


STATE_PATH = default_state_path()


class StateStore:
    """Load and atomically update state that users should not edit by hand."""

    def __init__(self, path=None):
        self.path = path or STATE_PATH

    def load(self):
        if not os.path.isfile(self.path):
            return {"version": 2, "applications": {}, "servers": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                state = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"Cannot read nemor-link state at {self.path}: {exc}") from exc
        if state.get("version") == 1 and isinstance(state.get("servers"), dict):
            servers = state["servers"]
            for record in servers.values():
                record.pop("token", None)
                record.pop("selections", None)
            return {"version": 2, "applications": {}, "servers": servers}
        if (
            state.get("version") != 2
            or not isinstance(state.get("applications"), dict)
            or not isinstance(state.get("servers"), dict)
        ):
            raise StateError(f"Unsupported nemor-link state at {self.path}")
        return state

    def save(self, state):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=directory)
        try:
            try:
                os.fchmod(fd, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


class StateError(ConfigError):
    pass

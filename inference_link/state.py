"""Persistent, machine-managed inference-link connection state."""

import json
import os
import tempfile

from inference_link.config import ConfigError


def default_state_path():
    if os.name == "nt" and os.environ.get("APPDATA"):
        root = os.environ["APPDATA"]
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, "inference-link", "state.json")


STATE_PATH = default_state_path()
LEGACY_STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(STATE_PATH)), "nemor-link", "state.json")
_UNSET = object()


class StateStore:
    """Load and atomically update state that users should not edit by hand."""

    def __init__(self, path=None, legacy_path=_UNSET):
        self.path = path or STATE_PATH
        if legacy_path is _UNSET:
            self.legacy_path = LEGACY_STATE_PATH if path is None else None
        else:
            self.legacy_path = legacy_path

    def load(self):
        source_path = self.path
        if not os.path.isfile(source_path):
            if self.legacy_path and os.path.isfile(self.legacy_path):
                source_path = self.legacy_path
            else:
                return {"version": 2, "default": {}, "applications": {}, "servers": {}}
        try:
            with open(source_path, "r", encoding="utf-8") as stream:
                state = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"Cannot read inference-link state at {source_path}: {exc}") from exc
        if state.get("version") == 1 and isinstance(state.get("servers"), dict):
            servers = state["servers"]
            active = state.get("active_server")
            active_record = servers.get(active) or {}
            default = {"server": active} if active in servers else {}
            if active_record.get("token"):
                default["token"] = active_record["token"]
            model = (active_record.get("selections") or {}).get("llm")
            if model:
                default["model"] = model
            for record in servers.values():
                record.pop("token", None)
                record.pop("selections", None)
            return {
                "version": 2,
                "default": default,
                "applications": {},
                "servers": servers,
            }
        if (
            state.get("version") != 2
            or not isinstance(state.get("applications"), dict)
            or not isinstance(state.get("servers"), dict)
        ):
            raise StateError(f"Unsupported inference-link state at {source_path}")
        state.setdefault("default", {})
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

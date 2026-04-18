"""Config loader for ~/.config/llm.json."""

import json
import os


CONFIG_PATH = os.path.expanduser("~/.config/llm.json")
VALID_KINDS = {"llm", "stt", "tts"}


class ConfigError(Exception):
    """Raised when config is missing, malformed, or refers to unknown entities."""


def load(path=None):
    """Load and validate config. Returns a dict with profiles/defaults/hosts.

    Legacy format (top-level `profiles` with `url`+`model` scalars and a
    top-level `default`) is detected and rejected with a helpful message —
    migration is manual per user request.
    """
    path = path or CONFIG_PATH
    if not os.path.isfile(path):
        raise ConfigError(
            f"Config not found at {path}.\n"
            f"Create it with at least one profile, e.g.:\n"
            f'  {{"profiles": {{"fast": {{"kind": "llm", '
            f'"backends": [{{"url": "http://127.0.0.1:8080", "model": "..."}}]}}}}, '
            f'"defaults": {{"llm": "fast"}}}}'
        )
    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path}: {e}")

    # Legacy format detection: top-level `default` + profile entries with scalar `url`
    if "default" in raw and "defaults" not in raw:
        raise ConfigError(
            f"{path} uses the legacy format with top-level 'default'. "
            f"Migrate it manually to the new schema: "
            f"rename 'default' → 'defaults.llm'; each profile should have "
            f"'kind' and a 'backends' list of {{url, model, auth?}} objects. "
            f"See README for an example."
        )

    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict):
        raise ConfigError("'profiles' must be an object")
    hosts = raw.get("hosts") or {}
    if not isinstance(hosts, dict):
        raise ConfigError("'hosts' must be an object")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be an object")

    for name, prof in profiles.items():
        if not isinstance(prof, dict):
            raise ConfigError(f"profile {name!r} must be an object")
        kind = prof.get("kind")
        if kind not in VALID_KINDS:
            raise ConfigError(
                f"profile {name!r}: 'kind' must be one of {sorted(VALID_KINDS)}, got {kind!r}"
            )
        backends = prof.get("backends")
        if not backends or not isinstance(backends, list):
            raise ConfigError(
                f"profile {name!r}: 'backends' must be a non-empty list of objects"
            )
        for i, b in enumerate(backends):
            if not isinstance(b, dict):
                raise ConfigError(f"profile {name!r}.backends[{i}] must be an object")
            if not b.get("url") or not isinstance(b["url"], str):
                raise ConfigError(f"profile {name!r}.backends[{i}]: 'url' is required")
            if kind == "llm" and not b.get("model"):
                raise ConfigError(
                    f"profile {name!r}.backends[{i}]: 'model' is required for kind=llm"
                )
            auth_name = b.get("auth")
            if auth_name and auth_name not in hosts:
                raise ConfigError(
                    f"profile {name!r}.backends[{i}] references unknown host {auth_name!r}; "
                    f"available: {sorted(hosts)}"
                )

    for kind, default_name in defaults.items():
        if kind not in VALID_KINDS:
            raise ConfigError(f"defaults.{kind}: unknown kind")
        if default_name not in profiles:
            raise ConfigError(
                f"defaults.{kind} points to unknown profile {default_name!r}"
            )
        if profiles[default_name]["kind"] != kind:
            raise ConfigError(
                f"defaults.{kind} = {default_name!r}, "
                f"but that profile has kind={profiles[default_name]['kind']!r}"
            )

    return {
        "profiles": profiles,
        "defaults": defaults,
        "hosts": hosts,
        "_path": path,
    }


def resolve_profile(config, name=None, kind=None, tool=None):
    """Find a profile by name, or pick default for a kind.

    tool: if given, reads ~/.config/{tool}.json and takes its "profile" field
    as override for name (matches existing utility convention).
    """
    if tool and not name:
        tool_cfg_path = os.path.expanduser(f"~/.config/{tool}.json")
        if os.path.isfile(tool_cfg_path):
            with open(tool_cfg_path, "r", encoding="utf-8") as f:
                try:
                    tool_cfg = json.load(f)
                except json.JSONDecodeError:
                    tool_cfg = {}
            name = tool_cfg.get("profile")

    if name is None:
        if kind is None:
            raise ConfigError("either name, kind, or tool must be given")
        name = config["defaults"].get(kind)
        if not name:
            raise ConfigError(
                f"no default for kind={kind!r}; available defaults: {config['defaults']}"
            )

    prof = config["profiles"].get(name)
    if not prof:
        raise ConfigError(
            f"unknown profile {name!r}; available: {sorted(config['profiles'])}"
        )
    if kind and prof["kind"] != kind:
        raise ConfigError(
            f"profile {name!r} has kind={prof['kind']!r}, but {kind!r} was requested"
        )

    resolved = dict(prof)
    resolved["name"] = name
    resolved_backends = []
    for b in prof["backends"]:
        nb = dict(b)
        auth_name = b.get("auth")
        nb["_host"] = config["hosts"][auth_name] if auth_name else None
        resolved_backends.append(nb)
    resolved["backends"] = resolved_backends
    return resolved


# Back-compat alias — some code may import resolve_service from earlier drafts.
resolve_service = resolve_profile

"""Config loader for ~/.config/llm.json."""

import json
import os


CONFIG_PATH = os.path.expanduser("~/.config/llm.json")
VALID_KINDS = {"llm", "stt", "tts"}


class ConfigError(Exception):
    """Raised when config is missing, malformed, or refers to unknown entities."""


def load(path=None):
    """Load and validate config. Returns a dict with services/defaults/hosts.

    Old format (with `profiles` + `default` at top level) is detected and
    rejected with a helpful message — migration is manual per user request.
    """
    path = path or CONFIG_PATH
    if not os.path.isfile(path):
        raise ConfigError(
            f"Config not found at {path}.\n"
            f"Create it with at least one service, e.g.:\n"
            f'  {{"services": {{"fast": {{"kind": "llm", '
            f'"urls": ["http://127.0.0.1:8080"], "model": "..."}}}}, '
            f'"defaults": {{"llm": "fast"}}}}'
        )
    with open(path, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path}: {e}")

    if "profiles" in raw and "services" not in raw:
        raise ConfigError(
            f"{path} uses the legacy format with top-level 'profiles'. "
            f"Migrate it manually to the new schema: "
            f"rename 'profiles' → 'services', add 'kind': 'llm' to each, "
            f"rename 'default' → 'defaults.llm'. "
            f"Optionally add a 'hosts' map for shared auth tokens. "
            f"See README for an example."
        )

    services = raw.get("services") or {}
    if not isinstance(services, dict):
        raise ConfigError("'services' must be an object")
    hosts = raw.get("hosts") or {}
    if not isinstance(hosts, dict):
        raise ConfigError("'hosts' must be an object")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be an object")

    # Validate services
    for name, svc in services.items():
        if not isinstance(svc, dict):
            raise ConfigError(f"service {name!r} must be an object")
        kind = svc.get("kind")
        if kind not in VALID_KINDS:
            raise ConfigError(
                f"service {name!r}: 'kind' must be one of {sorted(VALID_KINDS)}, got {kind!r}"
            )
        backends = svc.get("backends")
        if not backends or not isinstance(backends, list):
            raise ConfigError(
                f"service {name!r}: 'backends' must be a non-empty list of objects"
            )
        for i, b in enumerate(backends):
            if not isinstance(b, dict):
                raise ConfigError(f"service {name!r}.backends[{i}] must be an object")
            if not b.get("url") or not isinstance(b["url"], str):
                raise ConfigError(f"service {name!r}.backends[{i}]: 'url' is required")
            if kind == "llm" and not b.get("model"):
                raise ConfigError(
                    f"service {name!r}.backends[{i}]: 'model' is required for kind=llm"
                )
            auth_name = b.get("auth")
            if auth_name and auth_name not in hosts:
                raise ConfigError(
                    f"service {name!r}.backends[{i}] references unknown host {auth_name!r}; "
                    f"available: {sorted(hosts)}"
                )

    # Validate defaults
    for kind, default_name in defaults.items():
        if kind not in VALID_KINDS:
            raise ConfigError(f"defaults.{kind}: unknown kind")
        if default_name not in services:
            raise ConfigError(
                f"defaults.{kind} points to unknown service {default_name!r}"
            )
        if services[default_name]["kind"] != kind:
            raise ConfigError(
                f"defaults.{kind} = {default_name!r}, "
                f"but that service has kind={services[default_name]['kind']!r}"
            )

    return {
        "services": services,
        "defaults": defaults,
        "hosts": hosts,
        "_path": path,
    }


def resolve_service(config, name=None, kind=None, tool=None):
    """Find a service by name, or pick default for a kind.

    tool: if given, reads ~/.config/{tool}.json and takes its "profile" or
    "service" field as override for name (matches existing utility convention).
    """
    if tool and not name:
        tool_cfg_path = os.path.expanduser(f"~/.config/{tool}.json")
        if os.path.isfile(tool_cfg_path):
            with open(tool_cfg_path, "r", encoding="utf-8") as f:
                try:
                    tool_cfg = json.load(f)
                except json.JSONDecodeError:
                    tool_cfg = {}
            name = tool_cfg.get("service") or tool_cfg.get("profile")

    if name is None:
        if kind is None:
            raise ConfigError("either name, kind, or tool must be given")
        name = config["defaults"].get(kind)
        if not name:
            raise ConfigError(f"no default for kind={kind!r}; available defaults: {config['defaults']}")

    svc = config["services"].get(name)
    if not svc:
        raise ConfigError(f"unknown service {name!r}; available: {sorted(config['services'])}")
    if kind and svc["kind"] != kind:
        raise ConfigError(
            f"service {name!r} has kind={svc['kind']!r}, but {kind!r} was requested"
        )

    resolved = dict(svc)
    resolved["name"] = name
    # Expand per-backend host reference into the full host record.
    resolved_backends = []
    for b in svc["backends"]:
        nb = dict(b)
        auth_name = b.get("auth")
        nb["_host"] = config["hosts"][auth_name] if auth_name else None
        resolved_backends.append(nb)
    resolved["backends"] = resolved_backends
    return resolved

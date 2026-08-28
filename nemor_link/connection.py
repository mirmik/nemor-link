"""Connection discovery, TOFU trust, and application-scoped CLI actions."""

import hashlib
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit

import requests

from nemor_link.config import ConfigError
from nemor_link.state import StateStore
from nemor_link.tls import normalize_fingerprint, prepare_session_for_backend


DEFAULT_PORT = 8090


class LinkError(ConfigError):
    """An actionable problem with a nemor-link connection."""


class NotConnected(LinkError):
    pass


class ModelNotSelected(LinkError):
    pass


class AuthenticationRequired(LinkError):
    pass


class ServerIdentityChanged(LinkError):
    pass


class ServerUnavailable(LinkError):
    pass


def normalize_server_url(address):
    value = (address or "").strip()
    if not value:
        raise LinkError("server address is required")
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LinkError(f"invalid server address: {address!r}")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise LinkError("server address must not contain a path, query, or fragment")
    port = parsed.port or DEFAULT_PORT
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urlunsplit((parsed.scheme, f"{host}:{port}", "", "", ""))


def inspect_server(address, timeout=10.0):
    """Observe identity and public capabilities without changing local trust."""
    endpoint = normalize_server_url(address)
    parsed = urlsplit(endpoint)
    fingerprint = None
    if parsed.scheme == "https":
        fingerprint = _certificate_fingerprint(parsed.hostname, parsed.port, timeout)
    backend = {"url": endpoint}
    if fingerprint:
        backend["tls_fingerprint"] = fingerprint
    try:
        capabilities = _get_json(endpoint + "/v1/capabilities", backend, timeout=timeout)
    except ServerUnavailable:
        # Older llm-proxy versions have no capabilities endpoint. Health is
        # sufficient to establish that the endpoint speaks HTTP.
        _get_json(endpoint + "/health", backend, timeout=timeout)
        capabilities = {"protocol": 0, "services": {"llm": True}}
    return {
        "endpoint": endpoint,
        "fingerprint": fingerprint,
        "capabilities": capabilities,
    }


def server_key(observation):
    fingerprint = observation.get("fingerprint")
    if fingerprint:
        return "sha256:" + normalize_fingerprint(fingerprint)
    return "http:" + hashlib.sha256(observation["endpoint"].encode("utf-8")).hexdigest()


def trust_server(observation, store=None, command=None):
    store = store or StateStore()
    state = store.load()
    key = server_key(observation)
    endpoint = observation["endpoint"]

    # An endpoint previously pinned to another certificate is a noteworthy
    # replacement. Explicit connect + trust is the only operation that changes it.
    for old_key, old in list(state["servers"].items()):
        if old_key == key or endpoint not in old.get("endpoints", []):
            continue
        old["endpoints"] = [item for item in old.get("endpoints", []) if item != endpoint]

    record = state["servers"].setdefault(key, {
        "fingerprint": observation.get("fingerprint"),
        "endpoints": [],
    })
    if endpoint not in record["endpoints"]:
        record["endpoints"].append(endpoint)
    record["capabilities"] = observation.get("capabilities") or {}
    if command:
        application = state["applications"].get(command)
        if not application or application.get("server") != key:
            state["applications"][command] = {"server": key}
    store.save(state)
    return record


def active_record(store=None, command=None):
    store = store or StateStore()
    state = store.load()
    if not command:
        raise LinkError("application name is required")
    application = state["applications"].get(command) or {}
    key = application.get("server")
    record = state.get("servers", {}).get(key)
    if not record or not record.get("endpoints"):
        hint = f"Run: {command} --connect <address>"
        raise NotConnected(f"Nemor server is not connected.\n{hint}")
    return key, record, application


def resolved_service(kind, store=None, command=None):
    _key, record, application = active_record(store=store, command=command)
    capabilities = record.get("capabilities") or {}
    if capabilities.get("auth_required") and not application.get("token"):
        hint = f"Run: {command} --set-token <token>"
        raise AuthenticationRequired(f"Server requires authentication.\n{hint}")
    endpoint = record["endpoints"][-1]
    backend = {"url": endpoint}
    if record.get("fingerprint"):
        backend["tls_fingerprint"] = record["fingerprint"]
    if application.get("token"):
        backend["_host"] = {"token": application["token"]}
    if kind == "llm":
        model = application.get("model")
        if not model:
            hint = f"Run: {command} --list-models"
            raise ModelNotSelected(f"No LLM model selected.\n{hint}")
        backend["model"] = model
    return {"name": endpoint, "kind": kind, "backends": [backend]}


def list_models(store=None, timeout=10.0, command=None):
    _key, record, application = active_record(store=store, command=command)
    backend = _backend_from_record(record)
    headers = _auth_headers(application)
    try:
        payload = _get_json(backend["url"] + "/v1/models", backend, headers, timeout)
    except AuthenticationRequired:
        hint = f"Run: {command} --set-token <token>"
        raise AuthenticationRequired(f"Server requires authentication.\n{hint}")
    return payload.get("data") or []


def set_model(model, store=None, command=None):
    store = store or StateStore()
    models = list_models(store=store, command=command)
    names = [item.get("id") for item in models]
    if model not in names:
        raise LinkError(f"Unknown model {model!r}. Available: {', '.join(names) or '(none)'}")
    _key, _record, _application = active_record(store=store, command=command)
    state = store.load()
    state["applications"][command]["model"] = model
    store.save(state)


def set_token(token, store=None, command=None):
    store = store or StateStore()
    _key, _record, _application = active_record(store=store, command=command)
    state = store.load()
    state["applications"][command]["token"] = token.strip() or None
    store.save(state)


def disconnect(store=None, command=None):
    store = store or StateStore()
    active_record(store=store, command=command)
    state = store.load()
    state["applications"].pop(command, None)
    store.save(state)


def connect_interactive(address, store=None, command=None, input_fn=input, output_fn=print):
    store = store or StateStore()
    if not command:
        raise LinkError("application name is required")
    observation = inspect_server(address)
    state = store.load()
    key = server_key(observation)
    if key not in state["servers"]:
        fingerprint = observation.get("fingerprint")
        if fingerprint:
            output_fn("This server has not been seen before.")
            output_fn("TLS fingerprint:\n  SHA256:" + fingerprint)
            answer = input_fn("Trust this server? [y/N] ").strip().lower()
        else:
            output_fn("Warning: this HTTP connection has no authenticated server identity.")
            answer = input_fn("Use this server anyway? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            output_fn("Not connected.")
            return False
    trust_server(observation, store=store, command=command)
    output_fn(f"Connected to {observation['endpoint']}")
    return True


def add_connection_arguments(parser):
    group = parser.add_argument_group("nemor-link connection")
    actions = group.add_mutually_exclusive_group()
    actions.add_argument("--connect", metavar="ADDRESS", help="trust and use a Nemor server")
    actions.add_argument("--disconnect", action="store_true", help="disconnect the active server")
    actions.add_argument(
        "--status", dest="link_status", action="store_true",
        help="show the active server",
    )
    actions.add_argument("--list-models", action="store_true", help="list server LLM models")
    actions.add_argument("--set-model", metavar="MODEL", help="select the LLM model")
    actions.add_argument("--set-token", metavar="TOKEN", help="set the server access token")
    return parser


def handle_connection_action(args, command, store=None, input_fn=input, output_fn=print):
    store = store or StateStore()
    if args.connect:
        connect_interactive(
            args.connect, store=store, command=command,
            input_fn=input_fn, output_fn=output_fn,
        )
        return True
    if args.disconnect:
        disconnect(store=store, command=command)
        output_fn("Disconnected.")
        return True
    if args.link_status:
        _key, record, application = active_record(store=store, command=command)
        output_fn("Server: " + record["endpoints"][-1])
        output_fn("LLM model: " + (application.get("model") or "not selected"))
        return True
    if args.list_models:
        selected = None
        try:
            _key, _record, application = active_record(store=store, command=command)
            selected = application.get("model")
        except NotConnected:
            raise
        for item in list_models(store=store, command=command):
            marker = "*" if item.get("id") == selected else " "
            status = item.get("status")
            suffix = f" ({status})" if status else ""
            output_fn(f"{marker} {item.get('id')}{suffix}")
        return True
    if args.set_model:
        set_model(args.set_model, store=store, command=command)
        output_fn(f"Selected LLM model: {args.set_model}")
        return True
    if args.set_token is not None:
        set_token(args.set_token, store=store, command=command)
        output_fn("Server token updated.")
        return True
    return False


def _backend_from_record(record):
    backend = {"url": record["endpoints"][-1]}
    if record.get("fingerprint"):
        backend["tls_fingerprint"] = record["fingerprint"]
    return backend


def _auth_headers(application):
    token = application.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_json(url, backend, headers=None, timeout=5.0):
    session = requests.Session()
    try:
        kwargs = prepare_session_for_backend(session, backend)
        response = session.get(url, headers=headers or {}, timeout=timeout, **kwargs)
    except requests.exceptions.SSLError as exc:
        raise ServerIdentityChanged(
            f"TLS identity of {backend['url']} does not match the trusted fingerprint"
        ) from exc
    except requests.RequestException as exc:
        raise ServerUnavailable(f"Cannot reach {backend['url']}: {exc}") from exc
    finally:
        session.close()
    if response.status_code == 401:
        raise AuthenticationRequired("Server requires authentication")
    if response.status_code >= 400:
        raise ServerUnavailable(f"{url} returned {response.status_code}: {response.text}")
    try:
        return response.json()
    except ValueError as exc:
        raise ServerUnavailable(f"{url} did not return JSON") from exc


def _certificate_fingerprint(host, port, timeout):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
    except socket.timeout as exc:
        raise ServerUnavailable(
            f"TCP connection to {host}:{port} timed out"
        ) from exc
    except OSError as exc:
        raise ServerUnavailable(
            f"Cannot open TCP connection to {host}:{port}: {exc}"
        ) from exc
    try:
        with raw:
            with context.wrap_socket(raw, server_hostname=host) as secure:
                certificate = secure.getpeercert(binary_form=True)
    except socket.timeout as exc:
        raise ServerUnavailable(
            f"TLS handshake with {host}:{port} timed out"
        ) from exc
    except ssl.SSLError as exc:
        raise ServerUnavailable(
            f"TLS handshake with {host}:{port} failed: {exc}"
        ) from exc
    except OSError as exc:
        raise ServerUnavailable(
            f"TLS connection to {host}:{port} failed: {exc}"
        ) from exc
    digest = hashlib.sha256(certificate).hexdigest()
    return normalize_fingerprint(digest)

"""CLI — `nemor-link <command>`."""

import argparse
import json
import sys

from nemor_link import config as _config
from nemor_link import llm as _llm, probe as _probe
from nemor_link.connection import (
    LinkError,
    active_record,
    connect_interactive,
    disconnect,
    list_models,
    set_model,
    set_token,
)


def cmd_list(args):
    cfg = _config.load(args.config)
    for name, prof in cfg["profiles"].items():
        is_default = cfg["defaults"].get(prof["kind"]) == name
        tag = " (default)" if is_default else ""
        print(f"[{prof['kind']:3s}] {name}{tag}")
        for i, b in enumerate(prof["backends"]):
            arrow = "*" if i == 0 else " "
            parts = [b["url"]]
            if b.get("model"):
                parts.append(f"model={b['model']}")
            if b.get("auth"):
                parts.append(f"auth={b['auth']}")
            print(f"      {arrow} {'  '.join(parts)}")


def cmd_probe(args):
    cfg = _config.load(args.config)
    report = _probe(config=cfg, kind=args.kind)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    for name, info in report.items():
        print(f"[{info['kind']:3s}] {name}  active={info['active']}")
        for b in info["backends"]:
            flag = "OK " if b["ok"] else "FAIL"
            lat = f"{b['latency_ms']}ms" if b["latency_ms"] is not None else "-"
            model = f"  model={b['model']}" if b.get("model") else ""
            print(f"       {flag}  {lat:>8s}  {b['url']}{model}")


def cmd_test(args):
    cfg = _config.load(args.config)
    client = _llm(name=args.name, config=cfg)
    try:
        resp = client.chat(
            [{"role": "user", "content": args.prompt}],
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    finally:
        client.close()
    content = resp["choices"][0]["message"].get("content", "")
    if args.json:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    else:
        print(content.strip())


def cmd_set_default(args):
    import os
    cfg = _config.load(args.config)
    if args.name not in cfg["profiles"]:
        print(f"unknown profile {args.name!r}", file=sys.stderr)
        sys.exit(1)
    if cfg["profiles"][args.name]["kind"] != args.kind:
        print(
            f"profile {args.name!r} has kind={cfg['profiles'][args.name]['kind']!r}, "
            f"not {args.kind!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    path = args.config or _config.CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw.setdefault("defaults", {})[args.kind] = args.name
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    print(f"defaults.{args.kind} = {args.name}")


def cmd_connect(args):
    connect_interactive(args.address, command=args.app)


def cmd_status(args):
    _key, record, application = active_record(command=args.app)
    print("Server: " + record["endpoints"][-1])
    print("LLM model: " + (application.get("model") or "not selected"))


def cmd_disconnect(args):
    disconnect(command=args.app)
    print("Using default connection." if args.app else "Disconnected.")


def cmd_list_models(args):
    _key, _record, application = active_record(command=args.app)
    selected = application.get("model")
    for item in list_models(command=args.app):
        marker = "*" if item.get("id") == selected else " "
        status = f" ({item['status']})" if item.get("status") else ""
        print(f"{marker} {item.get('id')}{status}")


def cmd_set_model(args):
    set_model(args.model, command=args.app)
    print(f"Selected LLM model: {args.model}")


def cmd_set_token(args):
    set_token(args.token, command=args.app)
    print("Server token updated.")


def build_parser():
    p = argparse.ArgumentParser(prog="nemor-link")
    p.add_argument("-c", "--config", help="Path to config (default: ~/.config/llm.json)")
    p.add_argument("--app", help="Application whose connection is being managed")
    sub = p.add_subparsers(dest="command", required=True)

    s_connect = sub.add_parser("connect", help="Trust and use a Nemor server")
    s_connect.add_argument("address")
    s_connect.set_defaults(func=cmd_connect)

    s_status = sub.add_parser("status", help="Show the active server")
    s_status.set_defaults(func=cmd_status)

    s_disconnect = sub.add_parser("disconnect", help="Disconnect the active server")
    s_disconnect.set_defaults(func=cmd_disconnect)

    s_models = sub.add_parser("list-models", help="List LLM models")
    s_models.set_defaults(func=cmd_list_models)

    s_model = sub.add_parser("set-model", help="Select the LLM model")
    s_model.add_argument("model")
    s_model.set_defaults(func=cmd_set_model)

    s_token = sub.add_parser("set-token", help="Set the server access token")
    s_token.add_argument("token")
    s_token.set_defaults(func=cmd_set_token)

    s_list = sub.add_parser("list", help="List all configured profiles")
    s_list.set_defaults(func=cmd_list)

    s_probe = sub.add_parser("probe", help="Probe availability of all profiles")
    s_probe.add_argument("--kind", choices=["llm", "stt", "tts"], help="Filter by kind")
    s_probe.add_argument("--json", action="store_true", help="JSON output")
    s_probe.set_defaults(func=cmd_probe)

    s_test = sub.add_parser("test", help="Send a test prompt to an LLM profile")
    s_test.add_argument("name", nargs="?", help="Profile name (default LLM if omitted)")
    s_test.add_argument("-p", "--prompt", default="Say hi in one short sentence.")
    s_test.add_argument("--max-tokens", type=int, default=200)
    s_test.add_argument("--temperature", type=float, default=0.3)
    s_test.add_argument("--json", action="store_true")
    s_test.set_defaults(func=cmd_test)

    s_def = sub.add_parser("set-default", help="Set defaults.<kind> = <name>")
    s_def.add_argument("kind", choices=["llm", "stt", "tts"])
    s_def.add_argument("name")
    s_def.set_defaults(func=cmd_set_default)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (_config.ConfigError, LinkError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

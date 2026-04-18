"""CLI — `nemor-link <command>`."""

import argparse
import json
import sys

from nemor_link import config as _config
from nemor_link import llm as _llm, probe as _probe


def cmd_list(args):
    cfg = _config.load(args.config)
    for name, svc in cfg["services"].items():
        is_default = cfg["defaults"].get(svc["kind"]) == name
        tag = " (default)" if is_default else ""
        print(f"[{svc['kind']:3s}] {name}{tag}")
        for i, b in enumerate(svc["backends"]):
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
    if args.name not in cfg["services"]:
        print(f"unknown service {args.name!r}", file=sys.stderr)
        sys.exit(1)
    if cfg["services"][args.name]["kind"] != args.kind:
        print(
            f"service {args.name!r} has kind={cfg['services'][args.name]['kind']!r}, "
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


def build_parser():
    p = argparse.ArgumentParser(prog="nemor-link")
    p.add_argument("-c", "--config", help="Path to config (default: ~/.config/llm.json)")
    sub = p.add_subparsers(dest="command", required=True)

    s_list = sub.add_parser("list", help="List all configured services")
    s_list.set_defaults(func=cmd_list)

    s_probe = sub.add_parser("probe", help="Probe availability of all services")
    s_probe.add_argument("--kind", choices=["llm", "stt", "tts"], help="Filter by kind")
    s_probe.add_argument("--json", action="store_true", help="JSON output")
    s_probe.set_defaults(func=cmd_probe)

    s_test = sub.add_parser("test", help="Send a test prompt to an LLM service")
    s_test.add_argument("name", nargs="?", help="Service name (default LLM if omitted)")
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
    except _config.ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

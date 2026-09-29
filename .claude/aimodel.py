#!/usr/bin/env python3
"""Switch the Claude Code gateway model for this project (QuantDesk / IBKR).

All traffic goes through the local WorkBuddy Manager gateway
(Anthropic-protocol /v1/messages), which routes to the CodeBuddy account
pool. Model ids are prefixed by realm: `cn:...` (CN accounts).

Usage:
  python aimodel.py list                 show every model the gateway offers
  python aimodel.py <model-id>           set ONE model into all slots
                                         (e.g. python aimodel.py cn:glm-5.3)
  python aimodel.py --opus cn:auto --sonnet cn:balanced-model --haiku cn:fast-model
                                         set the three /model slots separately

Slots map to Claude Code's in-session `/model` picker:
  --opus   -> ANTHROPIC_DEFAULT_OPUS_MODEL
  --sonnet -> ANTHROPIC_DEFAULT_SONNET_MODEL
  --haiku  -> ANTHROPIC_DEFAULT_HAIKU_MODEL
`ANTHROPIC_MODEL` / `ANTHROPIC_SMALL_FAST_MODEL` are only touched when a
single <model-id> is given.

Takes effect on the NEXT `claude` start (or after /model in-session switch).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent / "settings.local.json"
DEFAULT_BASE = "http://127.0.0.1:16689"
SLOTS = ("ANTHROPIC_DEFAULT_OPUS_MODEL",
         "ANTHROPIC_DEFAULT_SONNET_MODEL",
         "ANTHROPIC_DEFAULT_HAIKU_MODEL")


def load_settings() -> dict:
    if not SETTINGS.exists():
        sys.exit(f"settings file not found: {SETTINGS}")
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def save_settings(cfg: dict) -> None:
    SETTINGS.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def gateway_models(base: str, key: str) -> list[str]:
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/models",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def main(argv: list[str]) -> int:
    cfg = load_settings()
    env = cfg.setdefault("env", {})
    base = env.get("ANTHROPIC_BASE_URL", DEFAULT_BASE)
    key = env.get("ANTHROPIC_AUTH_TOKEN", "")

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    # ---- list ------------------------------------------------------------
    if argv[0] == "list":
        try:
            ids = gateway_models(base, key)
        except Exception as exc:  # noqa: BLE001
            print(f"[X] cannot reach gateway at {base}: {exc}")
            print("    Run aistart.bat first, then retry.")
            return 1
        tiers = [m for m in ids if any(
            t in m for t in ("auto", "fast-model", "balanced-model", "deep-model"))]
        print(f"gateway {base} - {len(ids)} models")
        print("tier aliases:", ", ".join(tiers))
        print("all models:")
        for m in ids:
            print(" ", m)
        return 0

    # ---- per-slot mode ----------------------------------------------------
    updates: dict[str, str] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--opus", "--sonnet", "--haiku"):
            if i + 1 >= len(argv):
                print(f"[X] {arg} needs a model id")
                return 1
            slot = {"--opus": SLOTS[0], "--sonnet": SLOTS[1],
                    "--haiku": SLOTS[2]}[arg]
            updates[slot] = argv[i + 1]
            i += 2
            continue
        # ---- single-model mode -------------------------------------------
        model = arg
        updates = {s: model for s in SLOTS}
        env["ANTHROPIC_MODEL"] = model
        env["ANTHROPIC_SMALL_FAST_MODEL"] = model
        break

    # ---- validate against the gateway -------------------------------------
    try:
        ids = gateway_models(base, key)
        unknown = sorted({m for m in updates.values() if m not in ids})
        if unknown:
            print(f"[X] gateway does not offer: {', '.join(unknown)}")
            print("    run `aimodel.bat list` to see valid ids")
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[!] gateway unreachable ({exc}) - writing anyway")

    env.update(updates)
    save_settings(cfg)
    print("[OK] settings.local.json updated:")
    for k, v in updates.items():
        print(f"     {k} = {v}")
    print("     restart `claude` (or use /model in-session) to take effect")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Lancement local.
  python -m chat_rodi.cli chat --mode single|multi --client C --message "..." [--approve oui|non] [--store FILE]
  python -m chat_rodi.cli compare       # mono vs multi sur les 3 scénarios prescrits (store jetable)
"""
import argparse
import json
import os
import time

from . import agent, multi
from .rodium import RodiumClient
from .scenarios import PRESCRIBED
from .store import JsonStore


def auto_gate(decision):
    """Validation gérant simulée en CLI. En production, la validation vient de AFI_CHAT_ID."""
    return lambda pid, pend: decision == "oui"


def run(mode, store, client, message, gate, rodium, verbose=False):
    fn = agent.run_single if mode == "single" else multi.run_multi
    return fn(store, client, message, manager_gate=gate, rodium=rodium, verbose=verbose)


def main():
    ap = argparse.ArgumentParser(prog="chat_rodi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat")
    c.add_argument("--mode", choices=["single", "multi"], default="single")
    c.add_argument("--client", default="demo")
    c.add_argument("--message", required=True)
    c.add_argument("--approve", choices=["oui", "non"], default=None)
    c.add_argument("--store", default=os.environ.get("STORE_PATH", "data/store.json"))
    sub.add_parser("compare")
    args = ap.parse_args()
    rodium = RodiumClient()
    if args.cmd == "chat":
        out = run(args.mode, JsonStore(args.store), args.client, args.message,
                  auto_gate(args.approve) if args.approve else None, rodium, verbose=True)
        print("\nRÉPONSE :", out["reply"])
        return
    os.makedirs("data", exist_ok=True)
    rows = []
    for sc in PRESCRIBED:
        for mode in ["single", "multi"]:
            path = f"data/compare-{mode}-{sc['id']}.json"
            if os.path.exists(path):
                os.remove(path)
            t0 = time.time()
            out = run(mode, JsonStore(path), sc["client"], sc["message"], None, rodium)
            rows.append({"scenario": sc["id"], "mode": mode, "tool_calls": out["tool_calls"],
                         "llm_calls": out["llm_calls"], "elapsed_s": round(time.time() - t0, 4),
                         "reply": out["reply"]})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

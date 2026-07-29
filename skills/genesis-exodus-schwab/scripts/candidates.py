#!/usr/bin/env python3
"""
Genesis + Exodus — buy-candidate snapshot for the dashboard.

Runs the SAME deterministic discovery rules the scan uses (screener -> trend template
-> relative strength -> liquidity -> earnings guard -> sizing fit) and writes the
ranked result to state/candidates.json for the dashboard's "next-run candidates" panel.

ADVISORY / PREVIEW ONLY: this file never places orders. The scheduled scan re-derives
everything live at decision time (with fresh quotes, regime, preview-order, and the
LLM judgment layer for hard-scope disqualifiers) — so the actual pick can differ.

Usage: python3 candidates.py [--cap 100] [--top 10]
FMP responses are daily-cached, so re-runs are cheap.
"""

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
OUT = os.path.join(STATE, "candidates.json")
sys.path.insert(0, HERE)
import fmp  # noqa: E402


def live_cap(default_cap):
    """Per-name cap = min($100, 33% of live equity); falls back to default on error."""
    import subprocess
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "schwab.py"), "positions"],
                           capture_output=True, text=True, timeout=45)
        eq = json.loads(r.stdout).get("balances", {}).get("liquidationValue")
        if eq:
            return min(default_cap, 0.33 * float(eq)), eq
    except Exception:
        pass
    return default_cap, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=100.0)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    cap, equity = live_cap(args.cap)
    max_price = cap / 2  # 2 whole shares must fit

    rows = fmp.screener([f"priceMoreThan=5", f"priceLowerThan={max_price:.2f}", "limit=150"])
    syms = [r["symbol"] for r in rows if r.get("symbol")]

    passed = []
    for s in syms:
        r = fmp.indicators(s)
        if r.get("error") or not r.get("genesis_trend_template_pass"):
            continue
        if r.get("rs_vs_spy") is None or r["rs_vs_spy"] <= 0:
            continue
        if (r.get("avgDollarVol20") or 0) < 5_000_000:
            continue
        passed.append(r)
    passed.sort(key=lambda x: x["rs_vs_spy"], reverse=True)
    passed = passed[: args.top + 5]  # small buffer before earnings guard trims

    out = []
    for r in passed:
        e = fmp.earnings(r["symbol"])
        earnings_blocked = bool(e.get("within_5_trading_days")) or bool(e.get("error"))
        shares = int(cap // r["price"]) if r["price"] else 0
        out.append({
            "symbol": r["symbol"],
            "price": r["price"],
            "rs_vs_spy": r["rs_vs_spy"],
            "ret63d_pct": r["ret63d"],
            "pct_from_hi": r["pct_from_hi"],
            "breakout20": bool(r.get("breakout20")),
            "atr_pct": round(r["atr20"] / r["price"] * 100, 1) if (r.get("atr20") and r["price"]) else None,
            "next_earnings": e.get("next_earnings"),
            "earnings_blocked": earnings_blocked,
            "shares_at_cap": shares,
            "est_cost": round(shares * r["price"], 2),
            "eligible": (not earnings_blocked) and shares >= 2,
        })
    out = out[: args.top]

    payload = {
        "as_of": dt.datetime.now().isoformat(timespec="seconds"),
        "cap_per_name": round(cap, 2),
        "equity_used": equity,
        "universe_scanned": len(syms),
        "note": ("advisory preview — the scan re-scores live with fresh quotes, regime, "
                 "order preview, and hard-scope judgment (e.g. biotech-binary DQs)"),
        "candidates": out,
    }
    os.makedirs(STATE, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, OUT)
    print(json.dumps({"written": OUT, "candidates": len(out),
                      "eligible": sum(1 for c in out if c["eligible"])}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Project HRHR — human-directed speculative basket. Review engine, NOT a trader.

THIS SCRIPT NEVER PLACES AN ORDER. It is the deterministic half of a strategy whose
buy/sell decisions are made by a human in discussion. It does three things:

  plan      size the pending stage's orders at LIVE quotes, check them against the
            $1,000 budget, and print the exact build-order commands for a human to
            review and approve. Reference prices are shown next to live ones so
            drift is obvious.
  review    read the broker, mark every holding to market, and fire REVIEW alerts:
              - a holding >= 25% below its cost basis      -> review the business case
              - a holding >= 100% above cost, or > 35% of book -> review valuation/concentration
              - the day after the 2026-09-16 Fed decision  -> stage-2 review is due
            Alerts are day-stamped so a persistent condition nags once per day, not
            once per cron tick. Every review also journals one line with positions as
            OBJECTS (symbol/shares/avg/price) so the strategy monitor can price it.
  status    one-screen summary.

WHY NO STOPS: 3-5y horizon, substantial loss pre-accepted, most positions are a single
share (a stop would close the entire position, not trim it), and tight stops sell
volatile names on temporary swings. A falling price triggers a REVIEW; only a damaged
business case triggers a sale — and a human makes that call.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
sys.path.insert(0, HERE)
import fmp  # noqa: E402

PLAN_FILE = os.path.join(STATE, "plan.json")
JOURNAL = os.path.join(STATE, "journal.jsonl")
ALERT_STAMP = os.path.join(STATE, "alert_state.json")
NTFY_TOPIC = "autotrader-jp-303f1edb"


# ---------------------------------------------------------------- helpers ----
def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _now():
    return dt.datetime.now().astimezone()


def quotes(symbols):
    out = {}
    for s in sorted(set(symbols)):
        try:
            r = fmp._get("quote-short", {"symbol": s},
                         cache_key=f"hrhr:{s}:{int(dt.datetime.now().timestamp() // 120)}")
            if isinstance(r, list) and r and r[0].get("price"):
                out[s] = float(r[0]["price"])
        except Exception:
            continue
    return out


def broker():
    """Positions + balances via the account-pinned schwab.py. Returns (data, error)."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "schwab.py"), "positions"],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, (r.stdout or r.stderr)[:200]
    if "error" in d:
        return None, d.get("detail", d["error"])
    return d, None


def _positions(d):
    out = []
    for p in d.get("positions", []) or []:
        sym = (p.get("instrument") or {}).get("symbol")
        qty = float(p.get("longQuantity") or 0)
        if sym and qty > 0:
            out.append({"symbol": sym, "shares": qty,
                        "avg": float(p.get("averagePrice") or 0),
                        "mv": float(p.get("marketValue") or 0)})
    return out


def _push(title, body, prio="default", tags="mag"):
    def ascii_(s):
        return (s.replace("—", "-").replace("–", "-").replace("’", "'")
                 .encode("ascii", "replace").decode("ascii"))
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
        headers={"Title": ascii_(title), "Priority": prio, "Tags": tags})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception:
        return False


def _journal(entry):
    entry["ts"] = _now().isoformat(timespec="seconds")
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ------------------------------------------------------------------- plan ----
def cmd_plan(stage=None):
    plan = _load(PLAN_FILE, {})
    stage = stage or ("stage1" if plan.get("stage1", {}).get("status") == "pending" else "stage2")
    st = plan.get(stage, {})
    orders = st.get("orders", [])
    live = quotes([o["symbol"] for o in orders])
    d, err = broker()
    cash = None
    if d:
        cash = float((d.get("balances") or {}).get("cashAvailableForTrading")
                     or (d.get("balances") or {}).get("cashBalance") or 0)

    rows, total_ref, total_live = [], 0.0, 0.0
    for o in orders:
        lp = live.get(o["symbol"])
        ref = o["ref_px"] * o["qty"]
        est = (lp or 0) * o["qty"]
        total_ref += ref
        total_live += est
        rows.append({"symbol": o["symbol"], "qty": o["qty"], "ref_px": o["ref_px"],
                     "live_px": lp, "drift_pct": round((lp / o["ref_px"] - 1) * 100, 2) if lp else None,
                     "est_cost": round(est, 2)})

    already = 0.0
    if d:
        already = sum(p["mv"] for p in _positions(d))
    budget = float(plan.get("budget_usd", 1000))
    out = {
        "as_of": _now().isoformat(timespec="seconds"),
        "stage": stage, "status": st.get("status"), "note": st.get("note"),
        "orders": rows,
        "total_at_reference": round(total_ref, 2),
        "total_at_live": round(total_live, 2),
        "budget": budget,
        "already_invested": round(already, 2),
        "cash_available": cash,
        "within_budget": (already + total_live) <= budget if live else None,
        "cash_covers": (cash is not None and cash >= total_live) if live else None,
        "broker_error": err,
        "how_to_place": [
            "Marketable LIMIT at or just above the live ask, regular hours only.",
            "For each row: ORDER=$(python3 scripts/schwab.py build-order --symbol SYM --side BUY "
            "--qty N --type LIMIT --price X); python3 scripts/schwab.py preview-order \"$ORDER\" "
            "(must be ACCEPTED); python3 scripts/schwab.py place-order \"$ORDER\".",
            "Confirm fills with schwab.py orders --status FILLED before marking the stage done.",
        ],
    }
    print(json.dumps(out, indent=1))


# ----------------------------------------------------------------- review ----
def cmd_review():
    plan = _load(PLAN_FILE, {})
    rules = plan.get("review_rules", {})
    d, err = broker()
    if err:
        _journal({"run_type": "review", "decision": "BROKER UNREACHABLE — no review",
                  "error": err[:200]})
        print(json.dumps({"error": err}))
        return
    pos = _positions(d)
    bal = d.get("balances") or {}
    nav = float(bal.get("liquidationValue") or 0)
    cash = float(bal.get("cashBalance") or 0)
    live = quotes([p["symbol"] for p in pos])

    stamps = _load(ALERT_STAMP, {})
    today = _now().strftime("%Y-%m-%d")
    alerts, rows = [], []
    for p in pos:
        lp = live.get(p["symbol"]) or (p["mv"] / p["shares"] if p["shares"] else 0)
        val = lp * p["shares"]
        pct = (lp / p["avg"] - 1) * 100 if p["avg"] else None
        wt = (val / nav * 100) if nav else None
        row = {"symbol": p["symbol"], "shares": p["shares"], "avg": round(p["avg"], 4),
               "price": round(lp, 4), "value": round(val, 2),
               "pct_vs_cost": round(pct, 2) if pct is not None else None,
               "weight_pct": round(wt, 1) if wt is not None else None}
        rows.append(row)

        def fire(key, title, body, prio="high", tags="warning"):
            k = f"{p['symbol']}:{key}"
            if stamps.get(k) != today:
                if _push(title, body, prio, tags):
                    stamps[k] = today
                alerts.append({"symbol": p["symbol"], "type": key})

        if pct is not None and pct <= -rules.get("drawdown_alert_pct", 25):
            fire("drawdown", f"HRHR REVIEW: {p['symbol']} {pct:+.1f}% vs cost",
                 f"{p['symbol']} is {pct:.1f}% below your {p['avg']:.2f} cost basis "
                 f"(now {lp:.2f}). This is a REVIEW trigger, not a sale: check the "
                 f"business, valuation and news. Watch-for: "
                 f"{plan.get('watch_for', {}).get(p['symbol'], 'n/a')}")
        if pct is not None and pct >= rules.get("double_alert_pct", 100):
            fire("double", f"HRHR REVIEW: {p['symbol']} has doubled ({pct:+.0f}%)",
                 f"{p['symbol']} is {pct:+.0f}% vs cost. Review valuation and whether to "
                 f"take profits.", "default", "chart_with_upwards_trend")
        if wt is not None and wt > rules.get("concentration_alert_pct", 35):
            fire("concentration", f"HRHR REVIEW: {p['symbol']} is {wt:.0f}% of the book",
                 f"{p['symbol']} exceeds the 35% concentration threshold. Review before "
                 f"deciding whether to trim.", "default", "scales")

    # Stage-2 reminder: the day after the Fed decision, once.
    s2 = plan.get("stage2", {})
    if s2.get("status") == "conditional" and today > s2.get("review_after", "9999"):
        if stamps.get("stage2_due") != "sent":
            if _push("HRHR: stage-2 purchase review is due",
                     "The 2026-09-16 Fed decision has passed. Review prices and the "
                     "investment cases for the conditional stage-2 buys (1 VST, 1 POWL, "
                     "1 IREN, ~$381 at reference). Nothing is placed automatically — "
                     "run `hrhr.py plan stage2` and decide.", "high", "calendar"):
                stamps["stage2_due"] = "sent"
            alerts.append({"type": "stage2_due"})

    _save(ALERT_STAMP, stamps)
    decision = ("ALERTS: " + ", ".join(f"{a.get('symbol','')}:{a['type']}" for a in alerts)
                if alerts else "review clean — no triggers")
    _journal({"run_type": "review", "nav": round(nav, 2), "cash": round(cash, 2),
              "positions": rows, "alerts": alerts, "decision": decision})
    print(json.dumps({"as_of": _now().isoformat(timespec="seconds"), "nav": nav,
                      "cash": cash, "positions": rows, "alerts": alerts,
                      "decision": decision}, indent=1))


def cmd_status():
    plan = _load(PLAN_FILE, {})
    d, err = broker()
    print(json.dumps({
        "stage1": plan.get("stage1", {}).get("status"),
        "stage2": plan.get("stage2", {}).get("status"),
        "stage2_review_after": plan.get("stage2", {}).get("review_after"),
        "broker": ("error: " + err) if err else {
            "nav": (d.get("balances") or {}).get("liquidationValue"),
            "cash": (d.get("balances") or {}).get("cashBalance"),
            "positions": [(p["symbol"], p["shares"]) for p in _positions(d)]},
        "rules": plan.get("review_rules"),
    }, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "plan":
        cmd_plan(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "review":
        cmd_review()
    elif cmd == "status":
        cmd_status()
    else:
        print(json.dumps({"error": f"unknown command {cmd}"}))
        sys.exit(2)

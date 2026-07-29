#!/usr/bin/env python3
"""
Genesis + Exodus — weekly SCORECARD: performance measured, not vibed.

Reads the append-only ledger + journal and produces the structured review the
system's founding principle demands ("judge the playbook across many trades,
never one"). Four sections:

  1. TRADES      — per-setup (genesis/exodus/turtle) win rate, expectancy, P/L
  2. DECISIONS   — scan decision histogram (NO_TRADE / WATCHLIST / BUY)
  3. GATE AUDIT  — watchlist counterfactual: how did the names we REFUSED
                   perform since? (systematically strong refusals = gates too
                   tight; the CZR/R:R deadlock would have shown up here)
  4. OPS         — scheduler reliability: expected vs actual runs per day
                   (7 scans + ~21 quick-checks per market day)

Writes state/scorecard.json and prints a human-readable report.
Usage: python3 scorecard.py [--days 7]   (default: all history)
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
sys.path.insert(0, HERE)
import fmp  # noqa: E402


def read_jsonl(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return rows


def entry_date(j):
    """Extract an ISO YYYY-MM-DD date from an entry, tolerating the several
    scan_id formats accumulated over the system's life:
      2026-07-17T1257ET / 2026-07-17-0954-ET  (ISO-dashed)
      20260708-0933-ET-quickcheck             (compact YYYYMMDD)
      scan-20260715-095809                     (prefixed compact)
      genesis-schwab-2026-07-17T1257ET         (prefixed ISO)
    Returns None if no date is recoverable.
    """
    for k in ("ts", "timestamp", "ts_et", "scan_id"):
        v = j.get(k)
        if not v:
            continue
        s = str(v)
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)          # ISO-dashed anywhere
        if not m:
            m = re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", s)  # compact YYYYMMDD
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                dt.date(int(y), int(mo), int(d))              # validate
                return f"{y}-{mo}-{d}"
            except ValueError:
                continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="restrict to last N days")
    args = ap.parse_args()
    cutoff = ((dt.date.today() - dt.timedelta(days=args.days)).isoformat()
              if args.days else "0000-00-00")

    ledger = [t for t in read_jsonl(os.path.join(STATE, "ledger.jsonl"))
              if (t.get("closed_at") or "9999")[:10] >= cutoff]
    journal = [j for j in read_jsonl(os.path.join(STATE, "journal.jsonl"))
               if (entry_date(j) or "9999") >= cutoff]

    # ---- 1. trades, per setup ----
    def stats(rows):
        wins = [t for t in rows if (t.get("realized_pl") or 0) > 0]
        losses = [t for t in rows if (t.get("realized_pl") or 0) <= 0]
        pl = sum(float(t.get("realized_pl") or 0) for t in rows)
        n = len(rows)
        return {
            "trades": n,
            "win_rate_pct": round(100 * len(wins) / n, 1) if n else None,
            "avg_win": round(sum(t["realized_pl"] for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(t["realized_pl"] for t in losses) / len(losses), 2) if losses else 0,
            "expectancy": round(pl / n, 2) if n else None,
            "total_pl": round(pl, 2),
            "stops_hit": sum(1 for t in rows if t.get("outcome") == "stop"),
        }
    setups = sorted({t.get("setup", "unknown") for t in ledger})
    trades = {"all": stats(ledger),
              "by_setup": {s: stats([t for t in ledger if t.get("setup", "unknown") == s])
                           for s in setups}}

    # ---- 2. decision histogram ----
    hist = {}
    for j in journal:
        d = str(j.get("decision", "")).upper()
        key = ("BUY" if d.startswith("BUY") and "REJECT" not in d and "BLOCKED" not in d
               else "BUY_BLOCKED" if d.startswith("BUY")
               else "WATCHLIST" if "WATCHLIST" in d
               else "NO_TRADE" if "NO TRADE" in d or "NO_TRADE" in d
               else "MONITOR/OTHER")
        hist[key] = hist.get(key, 0) + 1

    # ---- 3. gate audit: watchlist counterfactual ----
    refused = []
    for j in journal:
        tc = j.get("top_candidate")
        if not tc or not isinstance(tc, dict):
            continue
        d = str(j.get("decision", "")).upper()
        if "WATCHLIST" not in d and "NO_TRADE" not in d and "NO TRADE" not in d:
            continue
        sym, ref_px = tc.get("symbol"), tc.get("entry_ask") or tc.get("entry")
        if not sym or not ref_px:
            continue
        refused.append({"symbol": sym, "date": entry_date(j), "ref_price": ref_px,
                        "score": tc.get("score"), "reason": str(j.get("reason", ""))[:80]})
    # de-dup by symbol keeping earliest refusal, then price them now
    seen, uniq = set(), []
    for r in refused:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            uniq.append(r)
    if uniq:
        pc = fmp.pricechange([r["symbol"] for r in uniq])
        now_px = {q.get("symbol"): q.get("price") for q in pc.get("quotes", [])} if "quotes" in pc else {}
        for r in uniq:
            npx = now_px.get(r["symbol"])
            r["price_now"] = npx
            r["return_since_refusal_pct"] = (round((npx / r["ref_price"] - 1) * 100, 2)
                                             if (npx and r["ref_price"]) else None)
    rets = [r["return_since_refusal_pct"] for r in uniq if r.get("return_since_refusal_pct") is not None]
    gate_audit = {
        "refused_candidates": uniq,
        "avg_return_since_refusal_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "interpretation": ("refusals strongly positive on average across many samples -> gates may be "
                           "too tight; strongly negative -> gates earning their keep; "
                           "few samples -> no conclusion yet"),
    }

    # ---- 4. ops: scheduler reliability ----
    by_day = {}
    for j in journal:
        d = entry_date(j)
        if not d:
            continue
        rt = j.get("run_type", "scan")
        kind = "quick" if "quick" in str(rt) else "scan"
        by_day.setdefault(d, {"scan": 0, "quick": 0})
        by_day[d][kind] += 1
    ops_days = []
    for d in sorted(by_day):
        try:
            wd = dt.date.fromisoformat(d).weekday()
        except ValueError:
            continue
        if wd >= 5:
            continue
        c = by_day[d]
        ops_days.append({"date": d, "scans": c["scan"], "scans_expected": 7,
                         "quick_checks": c["quick"], "quick_expected": 21,
                         "reliability_pct": round(100 * (c["scan"] + c["quick"]) / 28, 0)})
    avg_rel = (round(sum(x["reliability_pct"] for x in ops_days) / len(ops_days), 0)
               if ops_days else None)

    card = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "window_days": args.days or "all",
        "trades": trades, "decisions": hist, "gate_audit": gate_audit,
        "ops": {"days": ops_days, "avg_scheduler_reliability_pct": avg_rel},
    }
    with open(os.path.join(STATE, "scorecard.json"), "w") as f:
        json.dump(card, f, indent=1)

    # ---- human-readable ----
    print(f"═══ SCORECARD ({card['window_days']} days) — {card['generated_at']} ═══")
    a = trades["all"]
    print(f"TRADES: {a['trades']} closed | win rate {a['win_rate_pct']}% | "
          f"expectancy ${a['expectancy']}/trade | total P/L ${a['total_pl']} | stops {a['stops_hit']}")
    for s, st in trades["by_setup"].items():
        print(f"  {s:8} n={st['trades']}  win%={st['win_rate_pct']}  exp=${st['expectancy']}  P/L=${st['total_pl']}")
    print(f"DECISIONS: {hist or 'no scans in window'}")
    if gate_audit["avg_return_since_refusal_pct"] is not None:
        print(f"GATE AUDIT: {len(uniq)} refused candidates, avg return since refusal "
              f"{gate_audit['avg_return_since_refusal_pct']}%")
        for r in uniq[:8]:
            print(f"  {r['symbol']:6} refused {r['date']} @{r['ref_price']} -> now {r['price_now']} "
                  f"({r['return_since_refusal_pct']}%)")
    else:
        print("GATE AUDIT: no refused-candidate samples yet")
    print(f"OPS: scheduler reliability avg {avg_rel}% "
          f"({len(ops_days)} market days observed; 100% = 7 scans + 21 quick-checks/day)")
    print(f"scorecard.json written")


if __name__ == "__main__":
    main()

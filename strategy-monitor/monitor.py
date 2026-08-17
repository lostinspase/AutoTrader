#!/usr/bin/env python3
"""
Strategy Monitor — meta layer that aggregates performance across deployed
trading strategies. Read-only: it parses each strategy's on-disk state
(journal.jsonl, nav_baseline.json, buys_today.json, scorecard.json,
control.json) and never talks to a broker.

Adapters return a normalized dict per strategy so the dashboard can render
any strategy the same way.
"""

import json
import os
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config", "strategies.json")


def _read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def _entry_ts(entry):
    """Best-effort timestamp string from a journal entry."""
    return entry.get("ts") or entry.get("timestamp") or ""


def _parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    # tolerate "-0400" style offsets
    if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":" and s[-4:].isdigit():
        s = s[:-2] + ":" + s[-2:]
    for fmt in (None, "%Y-%m-%d"):
        try:
            return dt.datetime.fromisoformat(s) if fmt is None else dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _norm_positions(raw):
    """Journal position rows appear in two shapes; normalize to one."""
    out = []
    for p in raw or []:
        sym = p.get("symbol") or p.get("sym")
        if not sym:
            continue
        shares = p.get("shares") or p.get("qty") or 0
        avg = p.get("avg") or p.get("avg_price") or 0
        price = p.get("price") or p.get("mark") or 0
        pl = round((price - avg) * shares, 2) if avg and price else None
        out.append({
            "symbol": sym,
            "shares": shares,
            "avg": avg,
            "price": price,
            "pct": p.get("pct"),
            "stop": p.get("stop"),
            "unrealized_pl": pl,
        })
    return out


def _classify_decision(text):
    t = (text or "").upper()
    if "NO TRADE" in t or "NO_TRADE" in t:
        return "NO_TRADE"
    if "BLOCKED" in t or "REJECTED" in t:
        return "BUY_BLOCKED"
    if t.startswith("BUY") or "FILLED" in t:
        return "BUY"
    if "NO_ACTION" in t or "NO_POSITIONS" in t:
        return "MONITOR"
    if "WATCHLIST" in t:
        return "WATCHLIST"
    return "MONITOR"



def _num(v):
    """Coerce journal values to float — broker APIs (Robinhood) return numbers as
    strings, and agents journal them verbatim. None/unparseable -> None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def genesis_exodus_skill_adapter(cfg):
    state = os.path.expanduser(cfg["state_dir"])
    journal = _read_jsonl(os.path.join(state, "journal.jsonl"))
    nav_series = _read_json(os.path.join(state, "nav_baseline.json"), {}) or {}
    buys = _read_json(os.path.join(state, "buys_today.json"), {}) or {}
    scorecard = _read_json(os.path.join(state, "scorecard.json"), {}) or {}
    control = _read_json(os.path.join(state, "control.json"), {}) or {}
    ledger = _read_jsonl(os.path.join(state, "ledger.jsonl"))

    # --- heartbeat / status -------------------------------------------------
    last = journal[-1] if journal else None
    last_ts = _parse_ts(_entry_ts(last)) if last else None
    age_min = None
    if last_ts:
        now = dt.datetime.now(last_ts.tzinfo) if last_ts.tzinfo else dt.datetime.now()
        age_min = round((now - last_ts).total_seconds() / 60)

    # --- latest snapshot with positions/NAV --------------------------------
    positions, nav, cash, regime = [], None, None, None
    for entry in reversed(journal):
        if nav is None:
            nav = _num(entry.get("nav")) or _num(entry.get("liquidationValue")) or _num(entry.get("portfolio_value"))
            cash = _num(entry.get("cash")) or _num(entry.get("cash_available")) or _num(entry.get("cashAvailableForTrading"))
        if not positions and isinstance(entry.get("positions"), list) and entry["positions"] and isinstance(entry["positions"][0], dict):
            positions = _norm_positions(entry["positions"])
        if regime is None:
            regime = entry.get("regime")
        if nav is not None and positions and regime is not None:
            break

    # --- equity curve, deposit-aware ---------------------------------------
    deposits = cfg.get("deposits", [])
    dep_by_date = {d["date"]: d["amount"] for d in deposits}
    total_deposits = sum(d["amount"] for d in deposits)
    # nav_baseline.json is written by Genesis's quick-check (28 runs/day). The
    # monthly/weekly strategies (Ark, ARK2, Babel) never create it, so their curve
    # would be empty and Daily P/L would read "—" forever. Fall back to the NAV each
    # run already journals: last entry of each day wins.
    daily_nav = dict(nav_series)
    for entry in journal:
        ts = _entry_ts(entry)
        v = _num(entry.get("nav"))
        if ts and v:
            day = str(ts)[:10]
            if len(day) == 10 and day not in nav_series:
                daily_nav[day] = v
    curve = [
        {"date": d, "nav": v, "deposit": dep_by_date.get(d, 0)}
        for d, v in sorted(daily_nav.items())
    ]
    if nav is None and curve:
        nav = curve[-1]["nav"]

    baseline = cfg.get("trading_baseline")
    perf = {"total_deposits": total_deposits or None}
    if nav is not None and total_deposits:
        perf["net_pl_vs_deposits"] = round(nav - total_deposits, 2)
    if nav is not None and baseline:
        # deposit-aware: capital added AFTER the baseline is not profit
        post_base_deps = sum(d["amount"] for d in deposits
                             if d["date"] > baseline["date"])
        invested = baseline["nav"] + post_base_deps
        perf["campaign_pl"] = round(nav - invested, 2)
        perf["campaign_pct"] = round((nav / invested - 1) * 100, 2) if invested else None
        perf["campaign_since"] = baseline["date"]
        perf["post_baseline_deposits"] = post_base_deps or None
    perf["unrealized_pl"] = (
        round(sum(p["unrealized_pl"] for p in positions if p["unrealized_pl"] is not None), 2)
        if positions else 0
    )

    # --- daily change, DEPOSIT-AWARE ---------------------------------------
    # A deposit raises NAV without being profit. Subtract any deposit landing on
    # the later day, or a $438 transfer reads as a +$438 gain — the same mistake
    # the campaign P/L calc had to fix.
    if len(curve) >= 2:
        prev, last = curve[-2], curve[-1]
        dep = last.get("deposit") or 0
        chg = last["nav"] - prev["nav"] - dep
        base = prev["nav"] + dep
        perf["daily_pl"] = round(chg, 2)
        perf["daily_pct"] = round(chg / base * 100, 2) if base else None
        perf["daily_from"] = prev["date"]
        perf["daily_to"] = last["date"]
        perf["daily_deposit_adj"] = dep or None
    else:
        perf["daily_pl"] = None
        perf["daily_pct"] = None

    # --- entries log (buys) -------------------------------------------------
    entries = []
    for date, rows in sorted(buys.items()):
        for r in rows:
            entries.append({
                "date": date,
                "symbol": r.get("symbol"),
                "shares": r.get("shares") or r.get("qty"),
                "entry": r.get("entry") or r.get("price"),
                "stop": r.get("stop"),
            })

    # --- decision mix + recent activity ------------------------------------
    decision_counts = {}
    recent = []
    for e in journal:
        kind = _classify_decision(str(e.get("decision", "")))
        decision_counts[kind] = decision_counts.get(kind, 0) + 1
    for e in journal[-12:]:
        recent.append({
            "ts": _entry_ts(e),
            "run_type": e.get("run_type") or e.get("event") or "?",
            "decision": str(e.get("decision", ""))[:220],
        })
    recent.reverse()

    # --- closed-trade attribution ------------------------------------------
    # The skill's ledger.jsonl (ops.py ledger-add) is the authoritative record
    # of realized P/L. Entries from buys_today.json enrich each ledger row with
    # entry price/date; a position that disappeared without a ledger row is
    # surfaced as exit_unrecorded rather than given an invented P/L.
    open_symbols = {p["symbol"] for p in positions}
    still_open = [e for e in entries if e["symbol"] in open_symbols]

    entry_by_symbol = {}
    for e in entries:  # keep the earliest entry per symbol (FIFO-ish match)
        entry_by_symbol.setdefault(e["symbol"], e)

    closed_trades = []
    ledgered = set()
    for rec in ledger:
        sym = rec.get("symbol")
        ledgered.add(sym)
        ent = entry_by_symbol.get(sym, {})
        hold_days = None
        t_in, t_out = _parse_ts(ent.get("date")), _parse_ts(rec.get("closed_at"))
        if t_in and t_out:
            hold_days = (t_out.replace(tzinfo=None) - t_in.replace(tzinfo=None)).days
        closed_trades.append({
            "symbol": sym,
            "outcome": rec.get("outcome"),
            "setup": rec.get("setup"),
            "realized_pl": rec.get("realized_pl"),
            "realized_pct": rec.get("realized_pct"),
            "entry": ent.get("entry"),
            "shares": ent.get("shares"),
            "entry_date": ent.get("date"),
            "closed_at": rec.get("closed_at"),
            "hold_days": hold_days,
        })
    unrecorded = [
        {"symbol": e["symbol"], "entry": e["entry"], "shares": e["shares"],
         "entry_date": e["date"], "exit_unrecorded": True}
        for e in entries
        if e["symbol"] not in open_symbols and e["symbol"] not in ledgered
    ]

    realized = [t for t in closed_trades if t.get("realized_pl") is not None]
    wins = [t for t in realized if t["realized_pl"] > 0]
    losses = [t for t in realized if t["realized_pl"] <= 0]
    trade_stats = {
        "trades": len(closed_trades),
        "realized_pl": round(sum(t["realized_pl"] for t in realized), 2) if realized else 0,
        "win_rate_pct": round(100.0 * len(wins) / len(realized), 1) if realized else None,
        "avg_win": round(sum(t["realized_pl"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["realized_pl"] for t in losses) / len(losses), 2) if losses else None,
        "stops_hit": sum(1 for t in closed_trades if t.get("outcome") == "stop"),
        "by_setup": {},
        "unrecorded_exits": len(unrecorded),
    }
    for t in realized:
        s = t.get("setup") or "unknown"
        agg = trade_stats["by_setup"].setdefault(s, {"trades": 0, "realized_pl": 0.0})
        agg["trades"] += 1
        agg["realized_pl"] = round(agg["realized_pl"] + t["realized_pl"], 2)
    perf["realized_pl"] = trade_stats["realized_pl"]

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "broker": cfg["broker"],
        "notes": cfg.get("notes", ""),
        "status": {
            "live": bool(control.get("live")),
            "halted": bool(control.get("halted")),
            "halt_reason": control.get("halt_reason"),
        },
        "heartbeat": {
            "last_ts": _entry_ts(last) if last else None,
            "age_min": age_min,
            "stale_min": cfg.get("stale_min", 120),
            "journal_entries": len(journal),
        },
        "nav": nav,
        "cash": cash,
        "regime": regime,
        "performance": perf,
        "equity_curve": curve,
        "positions": positions,
        "entries": still_open,
        "closed_trades": closed_trades,
        "unrecorded_exits": unrecorded,
        "trade_stats": trade_stats,
        "decision_counts": decision_counts,
        "ops": scorecard.get("ops"),
        "gate_audit": scorecard.get("gate_audit"),
        "recent": recent,
    }


ADAPTERS = {"genesis_exodus_skill": genesis_exodus_skill_adapter}


def snapshot():
    cfg = _read_json(CONFIG_PATH, {"strategies": []})
    out = []
    for s in cfg["strategies"]:
        adapter = ADAPTERS.get(s.get("adapter"))
        if not adapter:
            out.append({"id": s.get("id"), "name": s.get("name"), "error": "unknown adapter"})
            continue
        try:
            out.append(adapter(s))
        except Exception as e:  # a broken strategy must not take down the monitor
            out.append({"id": s.get("id"), "name": s.get("name"), "error": repr(e)})
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "strategies": out,
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))

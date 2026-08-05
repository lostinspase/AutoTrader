#!/usr/bin/env python3
"""
Genesis + Exodus — deterministic SAFETY CORE.

All hard gates live here as CODE, not as prose the model could rationalize around.
Reads/writes the sibling state/ directory. Every subcommand prints JSON to stdout.

Subcommands:
  preflight  --nav <portfolio_value> [--date YYYY-MM-DD]
  nav-set    <portfolio_value> [--date YYYY-MM-DD]
  nav-check  [--nav <portfolio_value>] [--date YYYY-MM-DD]
  halt       "<reason>"
  resume
  live       on|off
  ack-losses "<note>"
  ledger-add '<json>'
  buy-record '<json>' [--date YYYY-MM-DD]
  buys-today [--date YYYY-MM-DD]
  perf
  ledger-recent [N]
  status

Config knobs (deliberate, backtest before changing):
  DAILY_LOSS_HALT_PCT      = 5.0   # NAV down >= this % vs session-open -> no new buys
  CONSEC_LOSS_WINDOW       = 3     # look at last N closed trades
  CONSEC_LOSS_TRIGGER      = 2     # >= this many stops in the window -> halt until ack
  DAILY_BUY_CAP            = 3     # max new buys per day
"""

import json
import os
import sys
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")

CONTROL_FILE = os.path.join(STATE, "control.json")
NAV_FILE = os.path.join(STATE, "nav_baseline.json")
LEDGER_FILE = os.path.join(STATE, "ledger.jsonl")
BUYS_FILE = os.path.join(STATE, "buys_today.json")

# ---- tunable safety constants -------------------------------------------------
DAILY_LOSS_HALT_PCT = 5.0
CONSEC_LOSS_WINDOW = 3
CONSEC_LOSS_TRIGGER = 2
DAILY_BUY_CAP = 3
# ------------------------------------------------------------------------------


def _ensure_state():
    os.makedirs(STATE, exist_ok=True)


def _today(date_override=None):
    if date_override:
        return date_override
    return datetime.date.today().isoformat()


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path, obj):
    _ensure_state()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _control():
    """Durable control state. Defaults: not halted, LIVE armed (per user config)."""
    return _load_json(CONTROL_FILE, {
        "halted": False,
        "halt_reason": None,
        "live": True,            # user chose: fully armed
        "losses_acked_through": None,  # ISO timestamp of last user ack
    })


def _emit(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


# ---- ledger / consecutive-loss logic -----------------------------------------
def _read_ledger():
    rows = []
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # A corrupt ledger line is a safety event — surface it loudly
                    raise ValueError(f"corrupt ledger line: {line[:120]!r}")
    return rows


def _consecutive_loss_halt():
    """
    Returns (halted: bool, stops_in_window: int).
    Halted if >= CONSEC_LOSS_TRIGGER of the last CONSEC_LOSS_WINDOW closed trades
    hit a stop AND the user has not acknowledged since the most recent stop.
    """
    rows = _read_ledger()
    if not rows:
        return False, 0
    window = rows[-CONSEC_LOSS_WINDOW:]
    # A "stop" only counts toward the breaker if it LOST money — a ratcheted
    # trailing stop that exits above entry is a win by P/L regardless of the
    # exit mechanism, and must never trip the loss breaker (hardened 2026-07-30
    # after the first profitable stop-out raised the question).
    stops = [r for r in window
             if r.get("outcome") == "stop" and float(r.get("realized_pl") or 0) < 0]
    n_stops = len(stops)
    if n_stops < CONSEC_LOSS_TRIGGER:
        return False, n_stops

    # Tripped — but a user ack AFTER the most recent stop clears it.
    ctrl = _control()
    acked_through = ctrl.get("losses_acked_through")
    if acked_through:
        # Find timestamp of the most recent stop in the window.
        stop_times = [r.get("closed_at") or r.get("timestamp") for r in stops]
        stop_times = [t for t in stop_times if t]
        if stop_times and acked_through >= max(stop_times):
            return False, n_stops
    return True, n_stops


# ---- NAV baseline ------------------------------------------------------------
def _nav_baseline(date):
    data = _load_json(NAV_FILE, {})
    return data.get(date)


def cmd_nav_set(value, date):
    """First-write-wins for the day's session-open NAV."""
    data = _load_json(NAV_FILE, {})
    existing = data.get(date)
    if existing is not None:
        _emit({"date": date, "nav_baseline": existing, "action": "kept_existing",
               "note": "first-write-wins; baseline already seeded today"})
        return
    data[date] = float(value)
    _save_json(NAV_FILE, data)
    _emit({"date": date, "nav_baseline": float(value), "action": "seeded"})


def cmd_nav_check(value, date):
    base = _nav_baseline(date)
    if base is None:
        _emit({"date": date, "nav_baseline": None,
               "note": "no baseline seeded today; call nav-set first"})
        return
    out = {"date": date, "nav_baseline": base}
    if value is not None:
        dd = (float(value) - base) / base * 100.0
        out.update({"nav_now": float(value), "drawdown_pct": round(dd, 3),
                    "daily_loss_halt": dd <= -DAILY_LOSS_HALT_PCT,
                    "halt_threshold_pct": -DAILY_LOSS_HALT_PCT})
    _emit(out)


# ---- daily buy cap -----------------------------------------------------------
def _buys_today(date):
    data = _load_json(BUYS_FILE, {})
    return data.get(date, [])


def cmd_buy_record(payload, date):
    try:
        rec = json.loads(payload)
    except json.JSONDecodeError as e:
        _emit({"error": f"buy-record payload not valid JSON: {e}"})
        sys.exit(2)
    data = _load_json(BUYS_FILE, {})
    day = data.setdefault(date, [])
    rec.setdefault("recorded_at", datetime.datetime.now().isoformat(timespec="seconds"))
    day.append(rec)
    _save_json(BUYS_FILE, data)
    _emit({"date": date, "buys_today": len(day), "buy_cap": DAILY_BUY_CAP,
           "buy_cap_reached": len(day) >= DAILY_BUY_CAP, "recorded": rec})


def cmd_buys_today(date):
    day = _buys_today(date)
    _emit({"date": date, "buys_today": len(day), "buy_cap": DAILY_BUY_CAP,
           "buy_cap_reached": len(day) >= DAILY_BUY_CAP, "records": day})


# ---- preflight: the consolidated verdict -------------------------------------
def cmd_preflight(nav, date):
    ctrl = _control()
    base = _nav_baseline(date)

    daily_loss_halt = False
    drawdown_pct = None
    if base is not None and nav is not None:
        drawdown_pct = (float(nav) - base) / base * 100.0
        daily_loss_halt = drawdown_pct <= -DAILY_LOSS_HALT_PCT

    consec_halt, stops_in_window = _consecutive_loss_halt()
    day_buys = _buys_today(date)
    buy_cap_reached = len(day_buys) >= DAILY_BUY_CAP

    reasons = []
    if ctrl.get("halted"):
        reasons.append(f"kill-switch HALTED: {ctrl.get('halt_reason')}")
    if not ctrl.get("live"):
        reasons.append("live trading flag is OFF (ops.py live on to arm)")
    if daily_loss_halt:
        reasons.append(f"daily-loss halt: NAV {drawdown_pct:.2f}% vs baseline "
                       f"(threshold -{DAILY_LOSS_HALT_PCT}%)")
    if consec_halt:
        reasons.append(f"consecutive-loss halt: {stops_in_window} of last "
                       f"{CONSEC_LOSS_WINDOW} closed at a stop; user must ack-losses")
    if buy_cap_reached:
        reasons.append(f"daily buy cap reached: {len(day_buys)}/{DAILY_BUY_CAP}")
    if base is None:
        reasons.append("no NAV baseline seeded today (nav-set first); buys blocked until seeded")

    new_buys_allowed = (
        not ctrl.get("halted")
        and ctrl.get("live")
        and not daily_loss_halt
        and not consec_halt
        and not buy_cap_reached
        and base is not None
    )

    _emit({
        "date": date,
        "new_buys_allowed": new_buys_allowed,
        "block_reasons": reasons,
        "kill_switch_halted": bool(ctrl.get("halted")),
        "halt_reason": ctrl.get("halt_reason"),
        "live": bool(ctrl.get("live")),
        "nav_baseline": base,
        "nav_now": float(nav) if nav is not None else None,
        "drawdown_pct": round(drawdown_pct, 3) if drawdown_pct is not None else None,
        "daily_loss_halt": daily_loss_halt,
        "daily_loss_threshold_pct": -DAILY_LOSS_HALT_PCT,
        "consecutive_loss_halt": consec_halt,
        "mechanical_stops_in_last3": stops_in_window,
        "buys_today": len(day_buys),
        "buy_cap": DAILY_BUY_CAP,
        "buy_cap_reached": buy_cap_reached,
    })


# ---- kill switch + flags -----------------------------------------------------
def cmd_halt(reason):
    ctrl = _control()
    ctrl["halted"] = True
    ctrl["halt_reason"] = reason or "manual halt"
    ctrl["halted_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_json(CONTROL_FILE, ctrl)
    _emit({"halted": True, "halt_reason": ctrl["halt_reason"]})


def cmd_resume():
    ctrl = _control()
    ctrl["halted"] = False
    ctrl["halt_reason"] = None
    ctrl["resumed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_json(CONTROL_FILE, ctrl)
    _emit({"halted": False, "note": "resumed"})


def cmd_live(state):
    ctrl = _control()
    ctrl["live"] = (state == "on")
    _save_json(CONTROL_FILE, ctrl)
    _emit({"live": ctrl["live"]})


def cmd_ack_losses(note):
    """USER-ONLY. Clears a tripped consecutive-loss breaker."""
    ctrl = _control()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    ctrl["losses_acked_through"] = now
    ctrl["last_ack_note"] = note or ""
    _save_json(CONTROL_FILE, ctrl)
    _emit({"losses_acked_through": now, "note": note or "",
           "warning": "this clears the consecutive-loss halt; user action only"})


# ---- ledger ------------------------------------------------------------------
def cmd_ledger_add(payload):
    try:
        rec = json.loads(payload)
    except json.JSONDecodeError as e:
        _emit({"error": f"ledger-add payload not valid JSON: {e}"})
        sys.exit(2)
    if "symbol" not in rec or "outcome" not in rec:
        _emit({"error": "ledger record requires at least {symbol, outcome}"})
        sys.exit(2)
    if rec["outcome"] not in ("win", "loss", "stop"):
        _emit({"error": "outcome must be one of win|loss|stop"})
        sys.exit(2)
    rec.setdefault("closed_at", datetime.datetime.now().isoformat(timespec="seconds"))
    _ensure_state()
    # DUPLICATE GUARD (added 2026-07-24 after a double-recorded close): if an entry
    # with the same symbol + outcome already exists on the same calendar day, skip.
    day = str(rec["closed_at"])[:10]
    for prior in _read_ledger():
        if (prior.get("symbol") == rec.get("symbol")
                and prior.get("outcome") == rec.get("outcome")
                and str(prior.get("closed_at", ""))[:10] == day):
            _emit({"skipped_duplicate": True, "existing": prior,
                   "note": "same symbol+outcome already recorded today; not appended"})
            return
    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    halt, n = _consecutive_loss_halt()
    _emit({"appended": rec, "consecutive_loss_halt_now": halt,
           "mechanical_stops_in_last3": n})


def cmd_perf():
    rows = _read_ledger()
    if not rows:
        _emit({"trades": 0, "note": "ledger empty"})
        return
    wins = [r for r in rows if r.get("outcome") == "win"]
    losses = [r for r in rows if r.get("outcome") in ("loss", "stop")]
    pl = sum(float(r.get("realized_pl", 0) or 0) for r in rows)
    _emit({
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(rows), 1) if rows else None,
        "total_realized_pl": round(pl, 2),
    })


def cmd_ledger_recent(n):
    rows = _read_ledger()
    _emit({"recent": rows[-n:]})


def cmd_status():
    ctrl = _control()
    halt, n = _consecutive_loss_halt()
    _emit({
        "halted": bool(ctrl.get("halted")),
        "halt_reason": ctrl.get("halt_reason"),
        "live": bool(ctrl.get("live")),
        "consecutive_loss_halt": halt,
        "mechanical_stops_in_last3": n,
    })


def main():
    p = argparse.ArgumentParser(prog="ops.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("preflight")
    sp.add_argument("--nav", type=float, default=None)
    sp.add_argument("--date", default=None)

    sp = sub.add_parser("nav-set")
    sp.add_argument("value", type=float)
    sp.add_argument("--date", default=None)

    sp = sub.add_parser("nav-check")
    sp.add_argument("--nav", type=float, default=None)
    sp.add_argument("--date", default=None)

    sp = sub.add_parser("halt")
    sp.add_argument("reason", nargs="?", default="manual halt")

    sub.add_parser("resume")

    sp = sub.add_parser("live")
    sp.add_argument("state", choices=["on", "off"])

    sp = sub.add_parser("ack-losses")
    sp.add_argument("note", nargs="?", default="")

    sp = sub.add_parser("ledger-add")
    sp.add_argument("payload")

    sp = sub.add_parser("buy-record")
    sp.add_argument("payload")
    sp.add_argument("--date", default=None)

    sp = sub.add_parser("buys-today")
    sp.add_argument("--date", default=None)

    sub.add_parser("perf")

    sp = sub.add_parser("ledger-recent")
    sp.add_argument("n", nargs="?", type=int, default=5)

    sub.add_parser("status")

    args = p.parse_args()
    _ensure_state()

    if args.cmd == "preflight":
        cmd_preflight(args.nav, _today(args.date))
    elif args.cmd == "nav-set":
        cmd_nav_set(args.value, _today(args.date))
    elif args.cmd == "nav-check":
        cmd_nav_check(args.nav, _today(args.date))
    elif args.cmd == "halt":
        cmd_halt(args.reason)
    elif args.cmd == "resume":
        cmd_resume()
    elif args.cmd == "live":
        cmd_live(args.state)
    elif args.cmd == "ack-losses":
        cmd_ack_losses(args.note)
    elif args.cmd == "ledger-add":
        cmd_ledger_add(args.payload)
    elif args.cmd == "buy-record":
        cmd_buy_record(args.payload, _today(args.date))
    elif args.cmd == "buys-today":
        cmd_buys_today(_today(args.date))
    elif args.cmd == "perf":
        cmd_perf()
    elif args.cmd == "ledger-recent":
        cmd_ledger_recent(args.n)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Project Babel — deterministic signal engine (gated 3x leveraged rotation).

Mirrors backtests/babel_backtest.py EXACTLY (v2 = weekly ladder + daily breaker;
validated 1999-2026: 15.2% CAGR, -52.2% maxDD, $1 -> $42.13 vs QQQ $9.24):

  SELECTOR  blended 63/126-day momentum picks the leader between QQQ and SPY
  GOVERNOR  on the LEADER's own price (never the LETF):
              price > 200-DMA and 20d vol < 20% ann  -> 3x tier
              price > 200-DMA and vol 20-35%         -> 1x tier
              price < 200-DMA or  vol > 35%          -> cash (SGOV)
  CADENCE   weekly ladder (full decision, Fri close -> Mon), plus a DAILY
            emergency de-lever that can only move DOWN to cash, never re-lever.

The 1x tier is implemented as 1/3 TQQQ + 2/3 SGOV (deployment decision
2026-07-18) so every share stays under ~$101 and $1k granularity works.

Signals use DIVIDEND-ADJUSTED daily closes (FMP), matching the backtest.
The engine only COMPUTES a target — it never places orders. The scheduled task
translates the target into Schwab orders (account 20425301 ONLY).

CLI:
  target        full weekly ladder decision -> state/babel_target.json
  daily-check   emergency de-lever test only (never re-levers); exit-only
  history       show recorded weekly decisions
"""

import datetime as dt
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
sys.path.insert(0, HERE)
import fmp  # noqa: E402

# Underlying indices the signals are computed on (NEVER the leveraged ETF).
CANDIDATES = ["QQQ", "SPY"]
# leader -> 3x vehicle
LETF = {"QQQ": "TQQQ", "SPY": "UPRO"}
CASH = "SGOV"

VOL_LO, VOL_HI = 0.20, 0.35     # annualized 20d realized vol tier bounds
SMA_N = 200
VOL_N = 20
MOM_SHORT, MOM_LONG = 63, 126
# 1x tier = 1/3 of the 3x vehicle + 2/3 cash (equivalent exposure, cheap shares)
ONE_X_LETF_FRACTION = 1.0 / 3.0

TARGET_FILE = os.path.join(STATE, "babel_target.json")
HISTORY_FILE = os.path.join(STATE, "babel_history.jsonl")

MIN_BARS = SMA_N + 5


def daily_series(sym, days=420):
    """[(date, adjClose)] ascending, dividend-adjusted — matches the backtest."""
    d = fmp._get("historical-price-eod/full", {"symbol": sym, "limit": days},
                 cache_key=f"babel:{sym}")
    rows = d if isinstance(d, list) else []
    out = []
    for r in rows:
        c = r.get("adjClose") or r.get("close")
        if r.get("date") and c:
            out.append((r["date"], float(c)))
    out.sort()
    return out


def _indicators(series):
    """(price, sma200, vol20_ann, mom_blended, as_of_date) from an ascending series."""
    closes = [c for _, c in series]
    if len(closes) < MIN_BARS:
        return None
    price = closes[-1]
    sma = st.mean(closes[-SMA_N:])
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - VOL_N, len(closes))]
    vol = st.pstdev(rets) * (252 ** 0.5)
    r_s = closes[-1] / closes[-1 - MOM_SHORT] - 1
    r_l = closes[-1] / closes[-1 - MOM_LONG] - 1
    return {
        "price": round(price, 2),
        "sma200": round(sma, 2),
        "above_sma200": price > sma,
        "vol20_ann": round(vol, 4),
        "mom_63": round(r_s, 4),
        "mom_126": round(r_l, 4),
        "mom_blended": round((r_s + r_l) / 2, 4),
        "as_of": series[-1][0],
    }


def _ladder(ind):
    """The governor. Returns (tier, reason) for a leader's indicators."""
    if not ind["above_sma200"]:
        return 0, (f"price {ind['price']} below 200-DMA {ind['sma200']} "
                   f"({(ind['price'] / ind['sma200'] - 1) * 100:.1f}%) — CASH")
    if ind["vol20_ann"] > VOL_HI:
        return 0, (f"20d vol {ind['vol20_ann'] * 100:.1f}% > {VOL_HI * 100:.0f}% "
                   f"ceiling — CASH")
    if ind["vol20_ann"] < VOL_LO:
        return 3, (f"above 200-DMA and 20d vol {ind['vol20_ann'] * 100:.1f}% "
                   f"< {VOL_LO * 100:.0f}% — 3x")
    return 1, (f"above 200-DMA but 20d vol {ind['vol20_ann'] * 100:.1f}% in "
               f"{VOL_LO * 100:.0f}-{VOL_HI * 100:.0f}% band — 1x")


def _weights(leader, tier):
    """Target portfolio weights for a (leader, tier) state."""
    if tier == 0:
        return {CASH: 1.0}
    vehicle = LETF[leader]
    if tier == 3:
        return {vehicle: 1.0}
    return {vehicle: round(ONE_X_LETF_FRACTION, 4),
            CASH: round(1 - ONE_X_LETF_FRACTION, 4)}


def compute(daily_breaker_only=False, current_tier=None, current_leader=None):
    """Full ladder (weekly) or de-lever-only test (daily).

    daily_breaker_only=True mirrors the backtest's daily branch: it may only move
    DOWN to cash, and only when a levered position is currently held.
    """
    data, ind = {}, {}
    for s in CANDIDATES:
        data[s] = daily_series(s)
        got = _indicators(data[s])
        if got is None:
            return {"error": f"insufficient data for {s} "
                             f"({len(data[s])} bars, need {MIN_BARS}) — NO TRADE "
                             f"(data-fragility rule)"}
        ind[s] = got

    # staleness guard: all candidates must share the same latest bar date
    dates = {s: ind[s]["as_of"] for s in CANDIDATES}
    if len(set(dates.values())) != 1:
        return {"error": f"candidate data dates disagree {dates} — NO TRADE"}
    as_of_data = list(set(dates.values()))[0]

    leader = max(CANDIDATES, key=lambda s: ind[s]["mom_blended"])
    tier, reason = _ladder(ind[leader])

    out = {
        "as_of": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_date": as_of_data,
        "mode": "daily_breaker" if daily_breaker_only else "weekly_ladder",
        "selector": {"leader": leader,
                     "mom_blended": {s: ind[s]["mom_blended"] for s in CANDIDATES}},
        "governor": {"tier": tier, "reason": reason},
        "signals": ind,
    }

    if daily_breaker_only:
        # Emergency de-lever ONLY: never re-lever, never switch leader mid-week.
        held = current_tier if current_tier is not None else 0
        if held <= 0:
            out["decision"] = "NO ACTION — flat/cash, daily breaker only de-levers"
            out["de_lever"] = False
            return out
        # Re-run the gate on the CURRENTLY HELD leader, not the momentum leader —
        # mid-week we never switch horses, we only dismount.
        held_leader = current_leader if current_leader in ind else leader
        h_ind = ind[held_leader]
        breach = (not h_ind["above_sma200"]) or (h_ind["vol20_ann"] > VOL_HI)
        if not h_ind["above_sma200"]:
            h_reason = (f"{held_leader} price {h_ind['price']} below 200-DMA "
                        f"{h_ind['sma200']} ({(h_ind['price'] / h_ind['sma200'] - 1) * 100:.1f}%)")
        elif h_ind["vol20_ann"] > VOL_HI:
            h_reason = (f"{held_leader} 20d vol {h_ind['vol20_ann'] * 100:.1f}% "
                        f"> {VOL_HI * 100:.0f}% ceiling")
        else:
            h_reason = (f"{held_leader} above 200-DMA, 20d vol "
                        f"{h_ind['vol20_ann'] * 100:.1f}% under ceiling")
        out["checked_leader"] = held_leader
        out["de_lever"] = bool(breach)
        out["target_weights"] = {CASH: 1.0} if breach else None
        out["decision"] = (f"DE-LEVER TO CASH — {h_reason}" if breach
                           else f"NO ACTION — {h_reason}")
        return out

    out["target_weights"] = _weights(leader, tier)
    out["decision"] = (f"TARGET {'CASH' if tier == 0 else str(tier) + 'x ' + leader} — {reason}")
    return out


def _persist(out):
    if "error" in out:
        return
    os.makedirs(STATE, exist_ok=True)
    tmp = TARGET_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, TARGET_FILE)


def cmd_target():
    out = compute()
    _persist(out)
    print(json.dumps(out, indent=1))


def _held_from_broker():
    """FILL TRUTH: what the ACCOUNT actually holds, not what we intended to hold.

    babel_target.json records INTENT; if an order was skipped, rejected, or partially
    filled, intent and reality diverge and a breaker driven by intent would try to sell
    a position that does not exist. The broker is the authority. Returns
    (tier, leader, source) and falls back to the target file ONLY if the broker is
    unreachable — in which case the caller must treat the result as degraded.
    """
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "schwab.py"), "positions"],
            capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
        if "error" in data:
            raise RuntimeError(data.get("detail", data["error"]))
        letf_shares = {}
        for p in data.get("positions", []):
            sym = (p.get("instrument", {}) or {}).get("symbol", "")
            qty = float(p.get("longQuantity") or 0)
            if qty > 0:
                letf_shares[sym] = qty
        # Which leveraged vehicle (if any) is actually held?
        for leader, vehicle in LETF.items():
            if letf_shares.get(vehicle, 0) > 0:
                nav = float((data.get("balances") or {}).get("liquidationValue") or 0)
                # 3x tier holds ~100% in the LETF; 1x tier holds ~1/3. Classify by weight
                # so a de-lever sells whatever is actually there either way.
                return (3, leader, "broker") if nav <= 0 else (
                    (3 if letf_shares[vehicle] * _last_px(vehicle) / nav > 0.6 else 1),
                    leader, "broker")
        return 0, None, "broker"          # no leveraged position -> nothing to de-lever
    except Exception as e:                # broker unreachable / auth error / timeout
        held_tier, held_leader = 0, None
        try:
            with open(TARGET_FILE) as f:
                last = json.load(f)
            held_tier = last.get("governor", {}).get("tier", 0)
            held_leader = last.get("selector", {}).get("leader")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return held_tier, held_leader, f"target_file_fallback ({e})"


def _last_px(sym):
    """Latest close for a held LETF, used only to classify 3x vs 1x by weight."""
    s = daily_series(sym, days=10)
    return s[-1][1] if s else 0.0


def cmd_daily_check():
    """De-lever test against what the BROKER says we hold (fill truth)."""
    held_tier, held_leader, source = _held_from_broker()
    out = compute(daily_breaker_only=True, current_tier=held_tier,
                  current_leader=held_leader)
    out["held"] = {"tier": held_tier, "leader": held_leader, "source": source}
    if source.startswith("target_file_fallback"):
        out["degraded"] = ("could not read broker positions — held state inferred from "
                           "babel_target.json. Verify positions before ANY order.")
    print(json.dumps(out, indent=1))


def cmd_history():
    try:
        with open(HISTORY_FILE) as f:
            rows = [json.loads(x) for x in f if x.strip()]
        print(json.dumps(rows, indent=1))
    except FileNotFoundError:
        print(json.dumps({"history": [], "note": "no decisions recorded yet"}))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "target"
    if cmd == "target":
        cmd_target()
    elif cmd == "daily-check":
        cmd_daily_check()
    elif cmd == "history":
        cmd_history()
    else:
        print(json.dumps({"error": f"unknown command {cmd}"}))
        sys.exit(2)

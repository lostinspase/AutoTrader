#!/usr/bin/env python3
"""
Genesis + Exodus — backtest harness (FMP daily history).

Replays the own-the-leaders entry rules + the exact exit profile (10% stop, +10% first
target sell 40%, 25% trailing stop on the runner, ratchet-only) over ~5 years of FMP
daily bars, portfolio-level, day by day.

HONESTY / LIMITATIONS (read before trusting numbers):
  - SURVIVORSHIP BIAS: the universe is TODAY's screener output. Names that blew up and
    left the universe are invisible. Results are optimistic; treat them as an upper bound.
  - No earnings guard in v1 (historical earnings dates per name are an extra API sweep).
    Live system HAS the guard, so live should be slightly safer than the sim on this axis.
  - No pyramiding in v1 (live system allows up to 3 units; sim trades single units).
  - Signals on close(t), execution at open(t+1). Stops/targets fill intraday off low/high,
    gap-through fills at the worse (stop) / better (target) of open vs level.
  - Commissions $0 (Schwab equities), slippage not modeled beyond gap fills.

Usage:
  python3 backtest.py                          # both sizing modes, default params
  python3 backtest.py --mode account           # $300 start, $100/name, whole shares >=2
  python3 backtest.py --mode pct               # 12.5%/name, fractional — measures raw edge
  python3 backtest.py --stop 0.08 --target 0.12 --trail 0.30
  python3 backtest.py --grid                   # small sensitivity grid over stop/target/trail
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fmp  # noqa: E402  (reuse key + cache + _get)

UNIVERSE_LIMIT = 120
HISTORY_BARS = 1400          # ~5.5 years
MAX_POSITIONS = 10   # raised 8->10 on 2026-07-27 with the ~$1k account (backtest-checked)
MAX_BUYS_PER_DAY = 3
RISK_PCT = 0.02              # 2% of equity to stop


# ---- data ---------------------------------------------------------------------
def fetch_history(symbol):
    """Full daily bars incl. open (fmp._history drops open; we need it for fills)."""
    data = fmp._get("historical-price-eod/full", {"symbol": symbol, "limit": HISTORY_BARS},
                    cache_key=f"bt:{symbol}:{HISTORY_BARS}")
    if fmp._is_err(data):
        return None
    rows = data if isinstance(data, list) else data.get("historical", [])
    out = []
    for r in sorted(rows, key=lambda x: x.get("date", "")):
        try:
            out.append({"date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out if len(out) >= 300 else None


def load_universe():
    rows = fmp.screener([f"limit={UNIVERSE_LIMIT}"])
    syms = [r["symbol"] for r in rows if r.get("symbol")]
    if not syms:
        print("FATAL: screener returned no universe", file=sys.stderr)
        sys.exit(1)
    return syms


# ---- indicator precompute -------------------------------------------------------
def precompute(bars):
    """Per-bar trend-template pass + 63d return, computed only from data up to that bar."""
    closes = [b["close"] for b in bars]
    n = len(bars)
    sig = [None] * n
    cum = [0.0]
    for c in closes:
        cum.append(cum[-1] + c)

    def sma(i, w):  # mean of closes[i-w+1..i]
        if i + 1 < w:
            return None
        return (cum[i + 1] - cum[i + 1 - w]) / w

    for i in range(n):
        if i + 1 < 252:
            continue
        s50, s150, s200 = sma(i, 50), sma(i, 150), sma(i, 200)
        s200p = sma(i - 21, 200) if i - 21 + 1 >= 200 else None
        if not (s50 and s150 and s200 and s200p):
            continue
        c = closes[i]
        lo52 = min(b["low"] for b in bars[i - 251:i + 1])
        hi52 = max(b["high"] for b in bars[i - 251:i + 1])
        tt = (c > s50 > s150 > s200 and s200 > s200p
              and c >= lo52 * 1.30 and c >= hi52 * 0.75)
        ret63 = c / closes[i - 63] - 1 if i >= 63 else None
        sig[i] = {"tt": tt, "ret63": ret63}
    return sig


# ---- simulation -----------------------------------------------------------------
def run_backtest(histories, spy, mode, stop_pct, target_pct, trail_pct,
                 start_equity, dollar_cap, risk_pct=RISK_PCT, name_cap_pct=0.10,
                 min_shares=2, start_date=None, end_date=None, sigs=None, idx=None,
                 insider_signals=None, insider_mode="off", verbose=False):
    """
    Sizing knobs (account mode):
      dollar_cap   flat $ cap per name (None = no flat cap)
      name_cap_pct per-name cap as fraction of current equity
      risk_pct     equity fraction risked to the stop (>=1.0 disables risk-based sizing;
                   the stop itself then bounds loss at position% * stop%)
      min_shares   minimum whole shares for a new entry
    Window / reuse knobs (for the gauntlet):
      start_date/end_date  restrict SIMULATED days to [start_date, end_date] (signals still
                           see full prior history — no lookahead, no cold-start bias)
      sigs/idx             precomputed signal + date-index maps (expensive; compute once,
                           pass to every run)
    """
    dates = [b["date"] for b in spy]
    if idx is None:
        idx = {sym: {b["date"]: k for k, b in enumerate(bars)}
               for sym, bars in histories.items()}
    if sigs is None:
        sigs = {sym: precompute(bars) for sym, bars in histories.items()}
    lo = next((i for i, d in enumerate(dates) if start_date is None or d >= start_date), 0)
    hi = next((i for i, d in enumerate(dates) if end_date is not None and d > end_date), len(dates))

    cash = start_equity
    positions = {}   # sym -> {shares, entry, stop, hi_close, partial_done, entry_date}
    trades = []
    equity_curve = []
    pending_buys = []  # decided at close(t), executed open(t+1)

    for d_i in range(lo, hi):
        date = dates[d_i]
        # ---- 1) execute pending entries at today's open
        for sym in pending_buys:
            bars = histories[sym]
            k = idx[sym].get(date)
            if k is None or sym in positions:
                continue
            price = bars[k]["open"]
            equity = cash + sum(p["shares"] * histories[s][idx[s][date]]["close"]
                                for s, p in positions.items() if date in idx[s])
            if mode == "account":
                cap = name_cap_pct * equity
                if dollar_cap:
                    cap = min(dollar_cap, cap)
                sh = int(cap // price)
                if risk_pct < 1.0:
                    sh = min(sh, int((risk_pct * equity) // (price * stop_pct)))
                if sh < min_shares:
                    continue
            else:
                cap = 0.125 * equity
                sh = min(cap / price, (RISK_PCT * equity) / (price * stop_pct))
                if sh * price < 1:
                    continue
            if sh * price > cash:
                continue
            cash -= sh * price
            positions[sym] = {"shares": sh, "entry": price, "stop": price * (1 - stop_pct),
                              "hi_close": price, "partial_done": False, "entry_date": date,
                              "eq_at_entry": equity}
        pending_buys = []

        # ---- 2) manage open positions on today's bar
        for sym in list(positions):
            k = idx[sym].get(date)
            if k is None:
                continue
            b = histories[sym][k]
            p = positions[sym]
            # stop first (conservative: check before target on same bar)
            if b["low"] <= p["stop"]:
                fill = min(b["open"], p["stop"]) if b["open"] < p["stop"] else p["stop"]
                cash += p["shares"] * fill
                pl = (fill - p["entry"]) * p["shares"]
                trades.append({"symbol": sym, "entry": p["entry"], "exit": fill,
                               "shares": p["shares"], "pl": pl,
                               "kind": "trail_stop" if p["partial_done"] else "stop",
                               "eq_at_entry": p["eq_at_entry"],
                               "entry_date": p["entry_date"], "exit_date": date})
                del positions[sym]
                continue
            # first target: sell ~40%. Even when the position is too small to carve a
            # partial (e.g. 2 shares -> floor(0.8)=0), the target being hit still flips
            # the position into runner mode so the trailing stop activates — matching
            # the live rule of ratcheting the stop up once the target is reached.
            tgt = p["entry"] * (1 + target_pct)
            if not p["partial_done"] and b["high"] >= tgt:
                fill = max(b["open"], tgt)
                part = (int(p["shares"] * 0.4) if mode == "account" else p["shares"] * 0.4)
                if mode == "account" and part < 1:
                    part = 0
                if part and part < p["shares"]:
                    cash += part * fill
                    trades.append({"symbol": sym, "entry": p["entry"], "exit": fill,
                                   "shares": part, "pl": (fill - p["entry"]) * part,
                                   "kind": "partial_target", "eq_at_entry": p["eq_at_entry"],
                                   "entry_date": p["entry_date"], "exit_date": date})
                    p["shares"] -= part
                p["partial_done"] = True
            # trailing ratchet (never down): before the partial the stop stays at the
            # initial level; after the partial the runner trails trail_pct off the
            # highest close, ratcheting up only.
            p["hi_close"] = max(p["hi_close"], b["close"])
            if p["partial_done"]:
                p["stop"] = max(p["stop"], p["hi_close"] * (1 - trail_pct))

        # ---- 3) signals at close -> queue entries for tomorrow
        if len(positions) < MAX_POSITIONS:
            cands = []
            spy_ret63 = None
            if d_i >= 63:
                spy_ret63 = spy[d_i]["close"] / spy[d_i - 63]["close"] - 1
            for sym, bars in histories.items():
                if sym in positions:
                    continue
                k = idx[sym].get(date)
                if k is None:
                    continue
                s = sigs[sym][k]
                if not s or not s["tt"] or s["ret63"] is None or spy_ret63 is None:
                    continue
                price = bars[k]["close"]
                if mode == "account":
                    eq_now = equity_curve[-1][1] if equity_curve else start_equity
                    cap_now = name_cap_pct * eq_now
                    if dollar_cap:
                        cap_now = min(dollar_cap, cap_now)
                    if price * min_shares > cap_now:
                        continue  # min_shares whole shares must fit the per-name cap
                excess = s["ret63"] - spy_ret63
                if excess <= 0:
                    continue
                # insider cluster-buy overlay (advisory in live; testable here).
                # A cluster within the trailing 90d: 'boost' nudges ranking,
                # 'require' hard-filters. String compare works on ISO dates.
                if insider_mode != "off" and insider_signals is not None:
                    import datetime as _dt
                    lo90 = (_dt.date.fromisoformat(date) - _dt.timedelta(days=90)).isoformat()
                    has_cluster = any(lo90 <= cd <= date
                                      for cd in insider_signals.get(sym, ()))
                    if insider_mode == "require" and not has_cluster:
                        continue
                    if insider_mode == "boost" and has_cluster:
                        excess += 0.05
                cands.append((excess, sym))
            cands.sort(reverse=True)
            slots = min(MAX_POSITIONS - len(positions), MAX_BUYS_PER_DAY)
            pending_buys = [sym for _, sym in cands[:slots]]

        # ---- 4) mark equity
        mv = sum(p["shares"] * histories[s][idx[s][date]]["close"]
                 for s, p in positions.items() if date in idx[s])
        equity_curve.append((date, cash + mv))

    # liquidate remaining at last close for accounting
    last = dates[hi - 1]
    for sym, p in positions.items():
        if last in idx[sym]:
            fill = histories[sym][idx[sym][last]]["close"]
            trades.append({"symbol": sym, "entry": p["entry"], "exit": fill,
                           "shares": p["shares"], "pl": (fill - p["entry"]) * p["shares"],
                           "kind": "open_at_end", "eq_at_entry": p.get("eq_at_entry"),
                           "entry_date": p["entry_date"], "exit_date": last})

    return equity_curve, trades


# ---- metrics --------------------------------------------------------------------
def metrics(curve, trades, start_equity, spy):
    end_eq = curve[-1][1]
    years = len(curve) / 252.0
    total_ret = end_eq / start_equity - 1
    cagr = (end_eq / start_equity) ** (1 / years) - 1 if years > 0.5 else None
    peak, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    closed = [t for t in trades if t["kind"] != "open_at_end"]
    wins = [t for t in closed if t["pl"] > 0]
    losses = [t for t in closed if t["pl"] <= 0]
    spy_ret = spy[-1]["close"] / spy[max(0, len(spy) - len(curve))]["close"] - 1
    return {
        "years": round(years, 2),
        "end_equity": round(end_eq, 2),
        "total_return_pct": round(total_ret * 100, 1),
        "cagr_pct": round(cagr * 100, 1) if cagr is not None else None,
        "max_drawdown_pct": round(maxdd * 100, 1),
        "closed_trades": len(closed),
        "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else None,
        "avg_win": round(sum(t["pl"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pl"] for t in losses) / len(losses), 2) if losses else 0,
        "spy_buyhold_return_pct": round(spy_ret * 100, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["account", "pct", "both"], default="both")
    ap.add_argument("--stop", type=float, default=0.10)
    ap.add_argument("--target", type=float, default=0.10)
    ap.add_argument("--trail", type=float, default=0.25)
    ap.add_argument("--equity", type=float, default=300.0)
    ap.add_argument("--cap", type=float, default=100.0)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--account-grid", action="store_true",
                    help="sweep small-account sizing policies at --equity scale")
    ap.add_argument("--insider-signals", default=None,
                    help="path to insider_signals.json from sec.py export-signals")
    ap.add_argument("--insider-mode", choices=["off", "boost", "require"], default="off")
    args = ap.parse_args()

    print("Loading universe from screener...", file=sys.stderr)
    universe = load_universe()
    print(f"  {len(universe)} names. Fetching histories (cached daily)...", file=sys.stderr)
    spy = fetch_history("SPY")
    if not spy:
        print("FATAL: no SPY history", file=sys.stderr); sys.exit(1)
    histories = {}
    for i, sym in enumerate(universe):
        h = fetch_history(sym)
        if h:
            histories[sym] = h
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(universe)} fetched", file=sys.stderr)
    print(f"  usable histories: {len(histories)}", file=sys.stderr)

    insider_signals = None
    if args.insider_signals:
        with open(args.insider_signals) as f:
            insider_signals = json.load(f).get("signals", {})

    def one(mode, stop, target, trail, risk=0.02, ncap=0.10, dcap=None, minsh=2, label=None):
        dcap = args.cap if dcap is None and mode == "account" and label is None else dcap
        curve, trades = run_backtest(histories, spy, mode, stop, target, trail,
                                     args.equity if mode == "account" else 100000.0,
                                     dcap, risk_pct=risk, name_cap_pct=ncap,
                                     min_shares=minsh, insider_signals=insider_signals,
                                     insider_mode=args.insider_mode)
        m = metrics(curve, trades, args.equity if mode == "account" else 100000.0, spy)
        m.update({"mode": mode, "stop": stop, "target": target, "trail": trail})
        if label:
            m["policy"] = label
        return m

    results = []
    if args.account_grid:
        # Sizing-policy sweep at real account scale. Columns:
        # (label, risk_pct [>=1 disables risk sizing], flat $ cap, per-name % cap, min shares)
        POLICIES = [
            ("A. old rules: 2% risk, min($100,10%), 2sh",  0.02, 100, 0.10, 2),
            ("C. adopted: min($100,33%), 2sh",             1.00, 100, 0.33, 2),
            ("K. min($150,33%), 2sh",                      1.00, 150, 0.33, 2),
            ("L. min($200,33%), 2sh",                      1.00, 200, 0.33, 2),
            ("M. no flat cap, 33%/name, 2sh",              1.00, None, 0.33, 2),
            ("N. no flat cap, 25%/name, 2sh",              1.00, None, 0.25, 2),
            ("O. no flat cap, 20%/name, 2sh",              1.00, None, 0.20, 2),
            ("G. min($150,50%), 1sh",                      1.00, 150, 0.50, 1),
        ]
        for label, risk, dcap, ncap, minsh in POLICIES:
            results.append(one("account", args.stop, args.target, args.trail,
                               risk=risk, ncap=ncap, dcap=dcap, minsh=minsh, label=label))
    elif args.grid:
        for stop in (0.08, 0.10, 0.12):
            for target in (0.08, 0.10, 0.12):
                for trail in (0.20, 0.25, 0.30):
                    results.append(one("pct", stop, target, trail))
    else:
        modes = ["account", "pct"] if args.mode == "both" else [args.mode]
        for mode in modes:
            results.append(one(mode, args.stop, args.target, args.trail))

    print(json.dumps({
        "caveats": [
            "SURVIVORSHIP BIAS: universe is today's screener — results are an optimistic upper bound",
            "no earnings guard / no pyramiding in sim (live system has both rules)",
            "account mode = $%.0f start, $%.0f/name, whole shares >=2; pct mode = $100k, 12.5%%/name, fractional" % (args.equity, args.cap),
        ],
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()

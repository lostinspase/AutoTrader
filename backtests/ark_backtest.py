#!/usr/bin/env python3
"""
Project Ark backtest — monthly simulation of the spec in proposals/project-ark.md.

Engines:
  FLOODGATE  absolute momentum vs T-bills (BIL), 10% vol target, SPY+TLT crash override
  TREND      eligible = price > 10-month SMA AND 12-1 momentum > 0
  ROTATE     top 4 by blended 3/6/12-mo momentum, inverse-vol weights, 40% class cap

Data: FMP dividend-adjusted daily closes -> month-end series. Proxies for young
ETFs so the test reaches 2008: GLD (for GLDM), IEF (for VGIT), BIL (for SGOV).
Simplifications: monthly-only (no mid-month weekly check), 10 bps/side cost.
"""

import json
import os
import statistics as st
import urllib.request
import urllib.parse
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BASE = "https://financialmodelingprep.com/stable"
ENV = os.path.expanduser("~/.claude/skills/genesis-exodus-schwab/state/fmp.env")

UNIVERSE = {  # symbol -> asset class
    "SPLG": "us_equity", "IJR": "us_equity",
    "VEA": "intl_equity", "VWO": "intl_equity",
    "TLT": "treasuries", "IEF": "treasuries",
    "LQD": "credit", "GLD": "gold", "DBC": "commodities", "VNQ": "reits",
}
CASH = "BIL"
BENCH = "SPY"
TOP_N = 4
CLASS_CAP = 0.40
VOL_TARGET = 0.10
COST = 0.0010  # 10 bps per side on turnover


def _key():
    with open(ENV) as f:
        for line in f:
            if line.startswith("FMP_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise SystemExit("no FMP key")


def fetch_daily(sym):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"{sym}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = (f"{BASE}/historical-price-eod/dividend-adjusted?" +
           urllib.parse.urlencode({"symbol": sym, "from": "2004-01-01",
                                   "to": "2026-07-17", "apikey": _key()}))
    with urllib.request.urlopen(url, timeout=60) as r:
        rows = json.loads(r.read())
    out = sorted(((x["date"], x["adjClose"]) for x in rows), key=lambda t: t[0])
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def month_end_series(daily):
    """{'YYYY-MM': last adjClose of that month}"""
    out = {}
    for date, px in daily:
        out[date[:7]] = px  # rows are date-sorted; last write wins
    return out


def run():
    syms = list(UNIVERSE) + [CASH, BENCH]
    me = {}
    for s in syms:
        d = fetch_daily(s)
        me[s] = month_end_series(d)
        print(f"  {s}: {len(d)} days, {list(me[s])[0]} .. {list(me[s])[-1]}")

    months = sorted(set.intersection(*(set(me[s]) for s in syms)))
    # need 12 months of lookback for momentum
    idx = {m: i for i, m in enumerate(months)}

    def px(s, m):
        return me[s][m]

    def ret(s, m, k):  # k-month simple return ending at m
        i = idx[m]
        return px(s, months[i]) / px(s, months[i - k]) - 1 if i >= k else None

    def sma10(s, m):
        i = idx[m]
        if i < 9:
            return None
        return st.mean(px(s, months[j]) for j in range(i - 9, i + 1))

    def mom_12_1(s, m):
        i = idx[m]
        return px(s, months[i - 1]) / px(s, months[i - 12]) - 1 if i >= 12 else None

    def blended(s, m):
        rs = [ret(s, m, k) for k in (3, 6, 12)]
        return None if any(r is None for r in rs) else st.mean(rs)

    def inv_vol_w(chosen, m):
        i = idx[m]
        vols = {}
        for s in chosen:
            rets = [px(s, months[j]) / px(s, months[j - 1]) - 1
                    for j in range(i - 11, i + 1)]
            vols[s] = max(st.pstdev(rets), 1e-6)
        tot = sum(1 / v for v in vols.values())
        return {s: (1 / vols[s]) / tot for s in chosen}

    start = 13  # first month with full lookback
    equity, spy_eq = [1.0], [1.0]
    dates = [months[start]]
    prev_w = {}
    port_rets = []
    hold_log = []

    for i in range(start, len(months) - 1):
        m, nxt = months[i], months[i + 1]

        # FLOODGATE: crash override
        crash = (sma10(BENCH, m) is not None and px(BENCH, m) < sma10(BENCH, m)
                 and sma10("TLT", m) is not None and px("TLT", m) < sma10("TLT", m))

        weights = {}
        if not crash:
            cash_bl = blended(CASH, m) or 0.0
            elig = [s for s in UNIVERSE
                    if sma10(s, m) is not None and px(s, m) > sma10(s, m)
                    and (mom_12_1(s, m) or 0) > 0
                    and (blended(s, m) or -1) > cash_bl]
            chosen = sorted(elig, key=lambda s: -blended(s, m))[:TOP_N]
            if chosen:
                w = inv_vol_w(chosen, m)
                w = {s: v * len(chosen) / TOP_N for s, v in w.items()}  # unfilled slots -> cash
                # class cap
                by_class = {}
                for s, v in w.items():
                    by_class.setdefault(UNIVERSE[s], []).append(s)
                for cls, ss in by_class.items():
                    tot = sum(w[s] for s in ss)
                    if tot > CLASS_CAP:
                        for s in ss:
                            w[s] *= CLASS_CAP / tot
                weights = w

        # vol targeting on trailing 6 portfolio returns
        if len(port_rets) >= 6:
            vol = st.pstdev(port_rets[-6:]) * (12 ** 0.5)
            if vol > VOL_TARGET:
                weights = {s: v * VOL_TARGET / vol for s, v in weights.items()}

        cash_w = 1.0 - sum(weights.values())
        turnover = sum(abs(weights.get(s, 0) - prev_w.get(s, 0))
                       for s in set(weights) | set(prev_w)) + abs(
                       cash_w - (1.0 - sum(prev_w.values())))
        cost = turnover / 2 * COST * 2  # per-side on traded notional

        r = sum(v * (px(s, nxt) / px(s, m) - 1) for s, v in weights.items())
        r += cash_w * (px(CASH, nxt) / px(CASH, m) - 1)
        r -= cost
        port_rets.append(r)
        equity.append(equity[-1] * (1 + r))
        spy_eq.append(spy_eq[-1] * (px(BENCH, nxt) / px(BENCH, m)))
        dates.append(nxt)
        prev_w = dict(weights)
        hold_log.append({"month": m, "crash_override": crash,
                         "holdings": {s: round(v, 3) for s, v in weights.items()},
                         "cash": round(cash_w, 3)})

    def metrics(eq):
        n_years = (len(eq) - 1) / 12
        rets = [eq[i + 1] / eq[i] - 1 for i in range(len(eq) - 1)]
        cagr = eq[-1] ** (1 / n_years) - 1
        vol = st.pstdev(rets) * (12 ** 0.5)
        peak, mdd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        downside = [r for r in rets if r < 0]
        sharpe = (st.mean(rets) * 12 - 0.02) / vol if vol else 0
        return {"cagr_pct": round(cagr * 100, 2), "vol_pct": round(vol * 100, 2),
                "sharpe_2pct_rf": round(sharpe, 2), "max_dd_pct": round(mdd * 100, 2),
                "worst_month_pct": round(min(rets) * 100, 2),
                "months_down": sum(1 for r in rets if r < 0), "months": len(rets)}

    def yearly(eq, ds):
        out = {}
        by_year = {}
        for i in range(1, len(eq)):
            by_year.setdefault(ds[i][:4], []).append(eq[i] / eq[i - 1])
        for y, rs in by_year.items():
            prod = 1.0
            for r in rs:
                prod *= r
            out[y] = round((prod - 1) * 100, 1)
        return out

    result = {
        "period": f"{dates[0]} .. {dates[-1]}",
        "ark": metrics(equity),
        "spy_buy_hold": metrics(spy_eq),
        "ark_yearly_pct": yearly(equity, dates),
        "spy_yearly_pct": yearly(spy_eq, dates),
        "final_multiple_ark": round(equity[-1], 2),
        "final_multiple_spy": round(spy_eq[-1], 2),
        "equity_curve": [{"date": d, "ark": round(e, 4), "spy": round(s, 4)}
                          for d, e, s in zip(dates, equity, spy_eq)],
        "crash_override_months": [h["month"] for h in hold_log if h["crash_override"]],
        "notes": "Monthly sim; GLD/IEF/BIL proxy GLDM/VGIT/SGOV; 10bps/side; no weekly check.",
    }
    with open(os.path.join(HERE, "ark_backtest_results.json"), "w") as f:
        json.dump(result, f, indent=1)
    slim = {k: v for k, v in result.items() if k != "equity_curve"}
    print(json.dumps(slim, indent=1))


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""
Project Babel backtest — weekly leveraged rotation per proposals/project-babel.md.

GOVERNOR ladder on the underlying index (QQQ/SPY):
  above 200-DMA & 20d vol < 20% ann -> 3x ; above & vol 20-35% -> 1x ; else cash
SELECTOR: blended 63/126-day momentum picks QQQ vs SPY.
CADENCE: decide at last close of week, apply next session. 5 bps per switch.

3x ETFs are SIMULATED from index daily returns:
  r3 = 3*r - expense(0.95%/yr)/252 - 2*financing/252
  financing = BIL daily yield*252 where available (>=2007-06), else 4%/yr.
Simulator is validated against real TQQQ over their overlap (2011->).
Data: FMP dividend-adjusted daily closes from 1999.
"""

import json
import os
import statistics as st
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BASE = "https://financialmodelingprep.com/stable"
ENV = os.path.expanduser("~/.claude/skills/genesis-exodus-schwab/state/fmp.env")

EXPENSE = 0.0095
COST = 0.0005  # 5 bps per switch
VOL_LO, VOL_HI = 0.20, 0.35


def _key():
    with open(ENV) as f:
        for line in f:
            if line.startswith("FMP_API_KEY="):
                return line.strip().split("=", 1)[1]
    raise SystemExit("no FMP key")


def fetch_daily(sym, frm="1999-01-01"):
    """Chunked fetch (FMP caps ~5000 rows/request) so 1999+ history is complete."""
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"{sym}_full_{frm[:4]}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    windows = [(frm, "2012-12-31"), ("2013-01-01", "2026-07-17")]
    rows = {}
    for a, b in windows:
        url = (f"{BASE}/historical-price-eod/dividend-adjusted?" +
               urllib.parse.urlencode({"symbol": sym, "from": a, "to": b,
                                       "apikey": _key()}))
        with urllib.request.urlopen(url, timeout=90) as r:
            for x in json.loads(r.read()):
                rows[x["date"]] = x["adjClose"]
    out = sorted(rows.items())
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def run():
    qqq = fetch_daily("QQQ")
    spy = fetch_daily("SPY")
    bil = dict(fetch_daily("BIL", "2007-05-01"))
    tqqq_real = dict(fetch_daily("TQQQ", "2011-01-01"))

    dates = sorted(set(d for d, _ in qqq) & set(d for d, _ in spy))
    px = {"QQQ": dict(qqq), "SPY": dict(spy)}
    n = len(dates)

    def dret(sym, i):
        return px[sym][dates[i]] / px[sym][dates[i - 1]] - 1

    # financing: 2x cash rate; BIL daily change as the rate proxy, else 4%/yr
    bil_dates = sorted(bil)

    def fin_daily(i):
        d = dates[i]
        if d >= "2007-06-01":
            # nearest BIL daily return
            j = None
            if d in bil:
                idx = bil_dates.index(d) if d in bil else None
                if idx and idx > 0:
                    j = bil[d] / bil[bil_dates[idx - 1]] - 1
            return j if j is not None else 0.045 / 252
        return 0.04 / 252

    def sim3(sym, i):
        return 3 * dret(sym, i) - EXPENSE / 252 - 2 * fin_daily(i)

    # --- validation: simulated 3x QQQ vs real TQQQ over overlap -------------
    t_dates = sorted(tqqq_real)
    overlap = [d for d in dates if t_dates[0] <= d <= t_dates[-1] and d in tqqq_real]
    sim_eq, real_eq = 1.0, tqqq_real[overlap[-1]] / tqqq_real[overlap[0]]
    for i in range(1, n):
        if overlap[0] < dates[i] <= overlap[-1]:
            sim_eq *= 1 + sim3("QQQ", i)
    yrs = (len(overlap) - 1) / 252
    validation = {
        "overlap": f"{overlap[0]} .. {overlap[-1]}",
        "sim_3x_qqq_cagr_pct": round((sim_eq ** (1 / yrs) - 1) * 100, 2),
        "real_tqqq_cagr_pct": round((real_eq ** (1 / yrs) - 1) * 100, 2),
    }

    # --- indicators ----------------------------------------------------------
    def sma200(sym, i):
        if i < 199:
            return None
        return st.mean(px[sym][dates[j]] for j in range(i - 199, i + 1))

    def vol20(sym, i):
        if i < 20:
            return None
        rs = [dret(sym, j) for j in range(i - 19, i + 1)]
        return st.pstdev(rs) * (252 ** 0.5)

    def blended_mom(sym, i):
        if i < 126:
            return None
        r63 = px[sym][dates[i]] / px[sym][dates[i - 63]] - 1
        r126 = px[sym][dates[i]] / px[sym][dates[i - 126]] - 1
        return (r63 + r126) / 2

    def week_end(i):  # last trading day of its week
        if i == n - 1:
            return True
        import datetime as dt
        d0 = dt.date.fromisoformat(dates[i])
        d1 = dt.date.fromisoformat(dates[i + 1])
        return d1.isocalendar()[1] != d0.isocalendar()[1] or d1.year != d0.year

    # --- simulate ------------------------------------------------------------
    def simulate(daily_breaker):
        start = 200
        state = ("CASH", 0)  # (asset, leverage tier)
        equity = [1.0]
        edates = [dates[start]]
        switches = 0
        tier_days = {"3x": 0, "1x": 0, "cash": 0}
        pending = None

        for i in range(start, n - 1):
            if pending is not None:
                if pending != state:
                    switches += 1
                    equity[-1] *= 1 - COST
                state = pending
                pending = None

            asset, lev = state
            j = i + 1
            if lev == 3:
                r = sim3(asset, j)
            elif lev == 1:
                r = dret(asset, j)
            else:
                r = fin_daily(j)  # cash earns the bill rate
            equity.append(equity[-1] * (1 + r))
            edates.append(dates[j])
            tier_days["3x" if lev == 3 else "1x" if lev == 1 else "cash"] += 1

            # weekly: full ladder decision for next session
            if week_end(i):
                mq, ms = blended_mom("QQQ", i), blended_mom("SPY", i)
                lead = "QQQ" if (mq or -9) >= (ms or -9) else "SPY"
                p, s200, v = px[lead][dates[i]], sma200(lead, i), vol20(lead, i)
                if s200 is None or v is None or p < s200 or v > VOL_HI:
                    pending = ("CASH", 0)
                elif v < VOL_LO:
                    pending = (lead, 3)
                else:
                    pending = (lead, 1)
            # daily: emergency de-lever only (never re-lever mid-week)
            elif daily_breaker and state[1] > 0:
                sym = state[0]
                p, s200, v = px[sym][dates[i]], sma200(sym, i), vol20(sym, i)
                if s200 is not None and v is not None and (p < s200 or v > VOL_HI):
                    pending = ("CASH", 0)
        return equity, edates, switches, tier_days

    equity, edates, switches, tier_days = simulate(daily_breaker=False)
    equity2, edates2, switches2, tier_days2 = simulate(daily_breaker=True)

    start = 200
    q_eq, s_eq, t3_eq = [1.0], [1.0], [1.0]
    for i in range(start, n - 1):
        j = i + 1
        q_eq.append(q_eq[-1] * (1 + dret("QQQ", j)))
        s_eq.append(s_eq[-1] * (1 + dret("SPY", j)))
        t3_eq.append(t3_eq[-1] * (1 + sim3("QQQ", j)))

    def metrics(eq, ds):
        n_years = (len(eq) - 1) / 252
        rets = [eq[i + 1] / eq[i] - 1 for i in range(len(eq) - 1)]
        cagr = eq[-1] ** (1 / n_years) - 1
        vol = st.pstdev(rets) * (252 ** 0.5)
        peak, mdd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        return {"cagr_pct": round(cagr * 100, 2), "vol_pct": round(vol * 100, 2),
                "sharpe_2pct_rf": round((st.mean(rets) * 252 - 0.02) / vol, 2) if vol else 0,
                "max_dd_pct": round(mdd * 100, 2),
                "worst_day_pct": round(min(rets) * 100, 2),
                "final_multiple": round(eq[-1], 2)}

    def yearly(eq, ds):
        out, by = {}, {}
        for i in range(1, len(eq)):
            by.setdefault(ds[i][:4], []).append(eq[i] / eq[i - 1])
        for y, rs in sorted(by.items()):
            p = 1.0
            for r in rs:
                p *= r
            out[y] = round((p - 1) * 100, 1)
        return out

    # monthly curve for charting
    monthly = []
    seen = set()
    for i, d in enumerate(edates):
        m = d[:7]
        if m not in seen:
            seen.add(m)
            monthly.append({"date": m, "babel_v1": round(equity[i], 3),
                            "babel_v2": round(equity2[i], 3),
                            "qqq": round(q_eq[i], 3), "spy": round(s_eq[i], 3)})

    result = {
        "period": f"{edates[0]} .. {edates[-1]}",
        "validation_sim_vs_real_tqqq": validation,
        "babel_v1_weekly": metrics(equity, edates),
        "babel_v2_daily_breaker": metrics(equity2, edates2),
        "qqq_buy_hold": metrics(q_eq, edates),
        "spy_buy_hold": metrics(s_eq, edates),
        "sim_3x_qqq_buy_hold": metrics(t3_eq, edates),
        "babel_v1_yearly_pct": yearly(equity, edates),
        "babel_v2_yearly_pct": yearly(equity2, edates2),
        "qqq_yearly_pct": yearly(q_eq, edates),
        "switches": {"v1": switches, "v2": switches2},
        "tier_days": {"v1": tier_days, "v2": tier_days2},
        "monthly_curve": monthly,
        "notes": "Weekly ladder; v2 adds daily emergency de-lever (no mid-week re-lever); 3x simulated (0.95% ER + 2x cash financing); 5bps/switch; signals on underlying.",
    }
    with open(os.path.join(HERE, "babel_backtest_results.json"), "w") as f:
        json.dump(result, f, indent=1)
    slim = {k: v for k, v in result.items() if k != "monthly_curve"}
    print(json.dumps(slim, indent=1))


if __name__ == "__main__":
    run()

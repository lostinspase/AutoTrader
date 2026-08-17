#!/usr/bin/env python3
"""
Managed-futures / long-vol trend backtest — the diversifier test.

WHY THIS EXISTS: the book's holdings correlate 0.95-1.00 with SPY (Genesis, Ark's
equity sleeve, Babel). Only Ark's DBC leg (~5% of book) diversifies. This tests a
classic time-series-momentum sleeve across NON-EQUITY assets -- rates, gold,
commodities, dollar -- taken LONG OR SHORT. Short exposure is the point: it is
what makes the sleeve long-vol (profits from sustained moves in either direction)
and therefore a hedge to an equity-concentrated book, rather than more of the same.

RULES (classic TSMOM, deliberately plain -- no fitted parameters):
  SIGNAL    12-month total return per asset; long if > 0, short if < 0
            confirmed by price vs 200-day SMA (both must agree, else flat)
  SIZING    inverse-volatility weights, scaled to a portfolio vol target
  CADENCE   monthly rebalance on month-end closes
  CASH      unallocated capital earns the T-bill yield (SGOV proxy)

JUDGE IT ON PORTFOLIO EFFECT, NOT STANDALONE RETURN. A long-vol sleeve is
SUPPOSED to lose small and often and pay off rarely and hugely. Standalone CAGR
below equities is expected and is not disqualifying; what matters is correlation
to the existing book and behaviour in the months when equities fall.
"""

import datetime as dt
import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.expanduser("~/.claude/skills/genesis-exodus-schwab/scripts")
sys.path.insert(0, SKILL)
import fmp  # noqa: E402

# Non-equity trend universe (the diversifying assets) + SPY only as a benchmark
UNIVERSE = {
    "TLT": "rates_long", "IEF": "rates_mid",
    "GLD": "gold", "SLV": "silver",
    "DBC": "commodities", "DBA": "agriculture",
    "UUP": "dollar",
}
BENCH = "SPY"
CASH_YIELD = 0.04
VOL_TARGET = 0.10          # annualized portfolio vol target
MOM_MONTHS = 12
SMA_N = 200
COST_PER_SWITCH = 0.0010   # 10 bps when a position flips


def fetch(sym):
    """Chunked fetch — a single 20y request times out on this plan."""
    rows = {}
    for a, b in [("2006-01-01", "2012-12-31"), ("2013-01-01", "2019-12-31"),
                 ("2020-01-01", "2026-08-16")]:
        for _ in range(3):
            r = fmp._get("historical-price-eod/full",
                         {"symbol": sym, "from": a, "to": b},
                         cache_key=f"mf3:{sym}:{a}")
            if isinstance(r, list):
                for x in r:
                    c = x.get("adjClose") or x.get("close")
                    if x.get("date") and c:
                        rows[x["date"]] = float(c)
                break
            time.sleep(2)
    return rows


def month_ends(dates):
    by = {}
    for d in dates:
        by[d[:7]] = d          # dates ascending -> last wins
    return [by[m] for m in sorted(by)]


def run():
    data = {s: fetch(s) for s in list(UNIVERSE) + [BENCH]}
    missing = [s for s, v in data.items() if len(v) < 1000]
    for s in missing:
        print(f"  !! dropping {s}: only {len(data[s])} bars", file=sys.stderr)
        data.pop(s, None)
    syms = [s for s in UNIVERSE if s in data]

    common = sorted(set.intersection(*(set(data[s]) for s in syms + [BENCH])))
    mes = month_ends(common)
    idx = {d: i for i, d in enumerate(common)}
    if len(mes) < MOM_MONTHS + 6:
        return {"error": "insufficient history"}

    equity, curve, monthly_rets = 1.0, [], []
    bench_eq, bench_curve = 1.0, []
    peak, mdd = 1.0, 0.0
    prev_pos = {}
    exposure_log = []

    for k in range(MOM_MONTHS + 1, len(mes) - 1):
        d0, d1 = mes[k], mes[k + 1]
        i0 = idx[d0]

        # --- signals at d0 ---
        pos = {}
        for s in syms:
            p_now = data[s][d0]
            p_then = data[s][mes[k - MOM_MONTHS]]
            mom = p_now / p_then - 1
            window = [data[s][common[j]] for j in range(max(0, i0 - SMA_N + 1), i0 + 1)]
            sma = sum(window) / len(window)
            trend_up = p_now > sma
            if mom > 0 and trend_up:
                pos[s] = 1
            elif mom < 0 and not trend_up:
                pos[s] = -1          # SHORT — this is what makes it long-vol
            else:
                pos[s] = 0

        # --- inverse-vol sizing on trailing 12m daily returns ---
        vols = {}
        for s in syms:
            px = [data[s][common[j]] for j in range(max(1, i0 - 251), i0 + 1)]
            rets = [px[j] / px[j - 1] - 1 for j in range(1, len(px))]
            vols[s] = max(st.pstdev(rets) * (252 ** 0.5), 1e-4)
        active = [s for s in syms if pos[s] != 0]
        w = {}
        if active:
            inv = {s: 1 / vols[s] for s in active}
            tot = sum(inv.values())
            for s in active:
                w[s] = inv[s] / tot
            # scale the whole book to the vol target (crude: ignores cross-corr)
            port_vol = sum(w[s] * vols[s] for s in active)
            scalar = min(VOL_TARGET / port_vol, 1.5) if port_vol > 0 else 0
            w = {s: w[s] * scalar for s in active}

        # --- realize the month ---
        r_month = 0.0
        for s in active:
            leg = (data[s][d1] / data[s][d0] - 1) * pos[s]
            r_month += w[s] * leg
        invested = sum(abs(x) for x in w.values())
        r_month += max(0.0, 1 - invested) * (CASH_YIELD / 12)

        turnover = sum(abs(pos.get(s, 0) - prev_pos.get(s, 0)) for s in syms)
        r_month -= turnover * COST_PER_SWITCH
        prev_pos = pos

        equity *= 1 + r_month
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)
        monthly_rets.append(r_month)
        curve.append({"date": d1, "equity": round(equity, 4)})

        b = data[BENCH][d1] / data[BENCH][d0] - 1
        bench_eq *= 1 + b
        bench_curve.append(b)
        exposure_log.append({"date": d0, "long": sum(1 for s in active if pos[s] > 0),
                             "short": sum(1 for s in active if pos[s] < 0),
                             "gross": round(invested, 3)})

    yrs = len(monthly_rets) / 12
    cagr = (equity ** (1 / yrs) - 1) * 100
    vol = st.pstdev(monthly_rets) * (12 ** 0.5) * 100
    downs = [r for r in monthly_rets if r < 0]
    sortino = ((st.mean(monthly_rets) * 12) /
               (st.pstdev(downs) * (12 ** 0.5))) if downs else None

    # correlation to the benchmark — THE headline number for a diversifier
    n = min(len(monthly_rets), len(bench_curve))
    a, b_ = monthly_rets[-n:], bench_curve[-n:]
    ma, mb = st.mean(a), st.mean(b_)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b_))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b_)) ** 0.5
    corr = num / den if den else 0

    # crisis behaviour: what does it do when SPY has its worst months?
    pairs = sorted(zip(b_, a))[:int(n * 0.10)]      # worst decile of SPY months
    crisis_avg = st.mean([x for _, x in pairs]) * 100
    spy_crisis_avg = st.mean([x for x, _ in pairs]) * 100

    return {
        "period": f"{curve[0]['date']} .. {curve[-1]['date']}",
        "years": round(yrs, 1),
        "cagr_pct": round(cagr, 2),
        "vol_pct": round(vol, 2),
        "max_dd_pct": round(mdd * 100, 1),
        "sortino": round(sortino, 2) if sortino else None,
        "win_months_pct": round(sum(1 for r in monthly_rets if r > 0) / len(monthly_rets) * 100, 1),
        "correlation_to_SPY": round(corr, 3),
        "bench_cagr_pct": round((bench_eq ** (1 / yrs) - 1) * 100, 2),
        "worst_decile_SPY_months": {
            "spy_avg_pct": round(spy_crisis_avg, 2),
            "sleeve_avg_pct": round(crisis_avg, 2),
            "note": "positive sleeve here = genuine crisis hedge",
        },
        "_curve": curve,
        "_monthly": monthly_rets,
        "_bench_monthly": b_,
        "_exposure": exposure_log[-6:],
    }


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("_")}, indent=1))
    with open(os.path.join(HERE, "mf_backtest_results.json"), "w") as f:
        json.dump({k: v for k, v in out.items() if k not in ("_monthly", "_bench_monthly")},
                  f, indent=1)

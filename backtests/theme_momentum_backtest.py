#!/usr/bin/env python3
"""
Thematic cross-sectional momentum backtest — "pick winners in hot sectors".

THE HYPOTHESIS: within AI / semis / memory / data-center / energy / space, rank
names by recent momentum, hold the leaders, rotate monthly. High volatility is
treated as OPPORTUNITY (bigger moves to ride) rather than as risk.

WHY THIS IS THE RIGHT TEST: cross-sectional momentum is one of the most
documented anomalies in finance (Jegadeesh-Titman), so the premise is not
crankish. But it is also where survivorship bias does the most damage: the
universe below is chosen with 2026 hindsight -- these are the names that ALREADY
won. That bias INFLATES results, so a weak result here is damning, and even a
strong one must be discounted. This is stated up front because the number this
script produces is NOT achievable in live trading.

DESIGN:
  UNIVERSE  hand-listed thematic names (see bias caveat above)
  SIGNAL    blended 1/3/6-month total return, ranked cross-sectionally
  FILTER    optional absolute-momentum gate: only hold if the name is also
            above its 100-day SMA (avoids catching falling knives)
  SIZING    equal weight across TOP_N, or inverse-vol
  CADENCE   monthly, fractional shares assumed (Robinhood supports notional)
  CASH      SGOV proxy when the gate keeps us out
"""

import json
import os
import statistics as st
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.expanduser("~/.claude/skills/genesis-exodus-schwab/scripts")
sys.path.insert(0, SKILL)
import fmp  # noqa: E402

THEMES = {
    "ai_software": ["PLTR", "AI", "SNOW", "CRWD", "NOW"],
    "semis": ["NVDA", "AMD", "AVGO", "MU", "TSM", "ARM", "MRVL", "LRCX", "AMAT", "KLAC"],
    "memory": ["MU", "WDC", "STX"],
    "datacenter": ["VRT", "SMCI", "ANET", "DELL", "EQIX"],
    "energy_gen": ["VST", "CEG", "NRG", "TLN", "OKLO", "SMR"],
    "storage_batt": ["ENPH", "FSLR", "TSLA", "QS", "PLUG"],
    "space": ["RKLB", "LUNR", "ASTS", "PL", "RDW"],
}
BENCH = "QQQ"
CASH = "SGOV"

TOP_N = 5
MOM_WINDOWS = (21, 63, 126)     # ~1/3/6 months in trading days
SMA_FILTER = 100                # absolute-momentum gate; 0 disables
COST = 0.0010                   # 10 bps per side on turnover
REBAL_DAYS = 21                 # monthly


def fetch(sym, frm="2019-01-01", to="2026-08-16"):
    rows = {}
    for a, b in [(frm, "2022-12-31"), ("2023-01-01", to)]:
        for _ in range(3):
            r = fmp._get("historical-price-eod/full",
                         {"symbol": sym, "from": a, "to": b},
                         cache_key=f"tm:{sym}:{a}")
            if isinstance(r, list):
                for x in r:
                    c = x.get("adjClose") or x.get("close")
                    if x.get("date") and c:
                        rows[x["date"]] = float(c)
                break
            time.sleep(2)
    return rows


def run(top_n=TOP_N, use_sma=True, inv_vol=False, label="baseline"):
    syms = sorted({s for v in THEMES.values() for s in v})
    data = {s: fetch(s) for s in syms}
    data[BENCH] = fetch(BENCH)
    data[CASH] = fetch(CASH)

    # Keep only names with enough history; note who was dropped (bias evidence)
    usable = {s: d for s, d in data.items() if len(d) > 400}
    dropped = [s for s in syms if s not in usable]

    dates = sorted(set.intersection(*(set(usable[s]) for s in [BENCH, CASH] if s in usable)))
    start = max(MOM_WINDOWS) + 5
    if len(dates) < start + 60:
        return {"error": "insufficient history"}

    equity, bench_eq = 1.0, 1.0
    peak, mdd = 1.0, 0.0
    monthly, bench_monthly, holdlog = [], [], []
    prev = set()

    i = start
    while i < len(dates) - REBAL_DAYS - 1:
        d = dates[i]
        # score every name that has data at this date
        scores, vols = {}, {}
        for s in syms:
            hist = usable.get(s)
            if not hist or d not in hist:
                continue
            ds = [x for x in dates[:i + 1] if x in hist]
            if len(ds) < max(MOM_WINDOWS) + 2:
                continue
            px_now = hist[ds[-1]]
            rs = []
            for w in MOM_WINDOWS:
                if len(ds) > w:
                    rs.append(px_now / hist[ds[-1 - w]] - 1)
            if len(rs) < len(MOM_WINDOWS):
                continue
            if use_sma and SMA_FILTER:
                win = [hist[x] for x in ds[-SMA_FILTER:]]
                if px_now < sum(win) / len(win):
                    continue          # absolute-momentum gate
            scores[s] = st.mean(rs)
            dr = [hist[ds[j]] / hist[ds[j - 1]] - 1 for j in range(max(1, len(ds) - 63), len(ds))]
            vols[s] = max(st.pstdev(dr), 1e-4)

        chosen = sorted(scores, key=lambda s: -scores[s])[:top_n]
        if chosen:
            if inv_vol:
                inv = {s: 1 / vols[s] for s in chosen}
                tot = sum(inv.values())
                w = {s: inv[s] / tot for s in chosen}
            else:
                w = {s: 1.0 / len(chosen) for s in chosen}
        else:
            w = {}

        j = min(i + REBAL_DAYS, len(dates) - 1)
        d2 = dates[j]
        r = 0.0
        for s, wt in w.items():
            h = usable[s]
            if d in h and d2 in h:
                r += wt * (h[d2] / h[d] - 1)
        cash_w = 1.0 - sum(w.values())
        if CASH in usable and d in usable[CASH] and d2 in usable[CASH]:
            r += cash_w * (usable[CASH][d2] / usable[CASH][d] - 1)
        turn = len(set(chosen) ^ prev) / max(len(chosen) or 1, 1)
        r -= turn * COST
        prev = set(chosen)

        equity *= 1 + r
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)
        monthly.append(r)
        bq = usable[BENCH]
        br = (bq[d2] / bq[d] - 1) if (d in bq and d2 in bq) else 0.0
        bench_eq *= 1 + br
        bench_monthly.append(br)
        holdlog.append({"date": d, "held": chosen})
        i = j

    yrs = len(monthly) * REBAL_DAYS / 252
    if yrs <= 0 or not monthly:
        return {"error": "no periods"}

    def corr(a, b):
        n = min(len(a), len(b)); a, b = a[-n:], b[-n:]
        ma, mb = st.mean(a), st.mean(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        return num / den if den else 0

    bpeak, bmdd, be = 1.0, 0.0, 1.0
    for x in bench_monthly:
        be *= 1 + x
        bpeak = max(bpeak, be)
        bmdd = min(bmdd, be / bpeak - 1)

    return {
        "label": label,
        "period": f"{dates[start]} .. {dates[min(i, len(dates)-1)]}",
        "years": round(yrs, 1),
        "cagr_pct": round((equity ** (1 / yrs) - 1) * 100, 2),
        "vol_pct": round(st.pstdev(monthly) * ((252 / REBAL_DAYS) ** 0.5) * 100, 2),
        "max_dd_pct": round(mdd * 100, 1),
        "win_periods_pct": round(sum(1 for x in monthly if x > 0) / len(monthly) * 100, 1),
        "bench_cagr_pct": round((bench_eq ** (1 / yrs) - 1) * 100, 2),
        "bench_max_dd_pct": round(bmdd * 100, 1),
        "corr_to_QQQ": round(corr(monthly, bench_monthly), 3),
        "dropped_no_history": dropped,
        "survivorship_warning": ("universe hand-picked in 2026 — these names already "
                                 "won; live results would be materially worse"),
        "_monthly": monthly, "_bench": bench_monthly, "_holds": holdlog[-4:],
    }


if __name__ == "__main__":
    out = run(label="equal-weight top5, SMA gate")
    print(json.dumps({k: v for k, v in out.items() if not k.startswith("_")}, indent=1))
    print("\nrecent holdings:")
    for h in out.get("_holds", []):
        print(" ", h["date"], h["held"])

#!/usr/bin/env python3
"""
Genesis + Exodus — GAUNTLET: robustness battery for the strategy + sizing policy.

Runs three tests the single-pass backtest can't provide (concept credit: Forven's
"gauntlet" idea; implementation is independent and native to our harness):

  1. WALK-FORWARD  (pct mode — measures the raw edge, more trades = less noise)
     Split history into 3 rolling train/test folds. On each train window, grid-search
     stop/target/trail; apply the tuned params to the UNSEEN test window; compare vs
     our fixed live profile (10/10/25). A big train->test degradation = overfitting.
     PASS if the live profile is profitable in >=2 of 3 test windows.

  2. MONTE CARLO  (account mode, policy C @ --equity)
     Bootstrap-resample the sim's closed trades (return-on-position r_i, position
     fraction f_i) into 5000 alternate orderings. Yields CONFIDENCE BANDS on CAGR and
     trade-level max drawdown instead of one lucky/unlucky path.
     PASS if median CAGR > 0, P(final < start) < 25%, and 5th-pct DD > -50%.
     NOTE: trade-level DD understates intra-trade drawdown; treat bands as floor.

  3. PARAMETER JITTER  (account mode, policy C @ --equity)
     Re-run the full sim across the 3x3x3 neighborhood of (stop, target, trail) and
     across equity scales ($300/$450/$600/$900). A strategy that only works at ONE
     parameter point or ONE account size is curve-fit, not robust.
     PASS if every neighbor is profitable and CAGR coefficient-of-variation < 0.6.

Same standing caveat as backtest.py: the universe is TODAY's screener (survivorship
bias) — the gauntlet tests ROBUSTNESS of the edge, it cannot fix that bias.

Usage:  python3 gauntlet.py [--equity 600]
"""

import argparse
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as bt  # noqa: E402

LIVE = (0.10, 0.10, 0.25)                       # stop, target, trail — the live profile
GRID_STOPS = (0.08, 0.10, 0.12)
GRID_TGTS = (0.08, 0.10, 0.12)
GRID_TRAILS = (0.20, 0.25, 0.30)
MC_PATHS = 5000
POLICY_C = dict(dollar_cap=100, risk_pct=1.0, name_cap_pct=0.33, min_shares=2)


def window_metrics(curve, trades, start_equity):
    end_eq = curve[-1][1] if curve else start_equity
    years = max(len(curve) / 252.0, 1e-9)
    cagr = (end_eq / start_equity) ** (1 / years) - 1 if years > 0.1 else 0.0
    peak, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    closed = [t for t in trades if t["kind"] != "open_at_end"]
    wins = sum(1 for t in closed if t["pl"] > 0)
    return {"cagr_pct": round(cagr * 100, 1), "maxdd_pct": round(maxdd * 100, 1),
            "trades": len(closed),
            "win_pct": round(100 * wins / len(closed), 1) if closed else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=600.0)
    args = ap.parse_args()

    print("Loading universe + histories (cached)...", file=sys.stderr)
    universe = bt.load_universe()
    spy = bt.fetch_history("SPY")
    histories = {}
    for sym in universe:
        h = bt.fetch_history(sym)
        if h:
            histories[sym] = h
    print(f"  {len(histories)} usable histories. Precomputing signals once...", file=sys.stderr)
    sigs = {sym: bt.precompute(bars) for sym, bars in histories.items()}
    idx = {sym: {b["date"]: k for k, b in enumerate(bars)}
           for sym, bars in histories.items()}
    dates = [b["date"] for b in spy]
    N = len(dates)

    def sim(mode, stop, tgt, trail, sd=None, ed=None, equity=None, **sizing):
        eq0 = equity if equity is not None else (args.equity if mode == "account" else 100000.0)
        curve, trades = bt.run_backtest(
            histories, spy, mode, stop, tgt, trail, eq0,
            sizing.get("dollar_cap"), risk_pct=sizing.get("risk_pct", 0.02),
            name_cap_pct=sizing.get("name_cap_pct", 0.10),
            min_shares=sizing.get("min_shares", 2),
            start_date=sd, end_date=ed, sigs=sigs, idx=idx)
        return window_metrics(curve, trades, eq0), trades

    report = {"equity": args.equity, "live_profile": {"stop": LIVE[0], "target": LIVE[1], "trail": LIVE[2]},
              "caveat": "universe is today's screener (survivorship bias) — gauntlet tests robustness, not that bias"}

    # ---- 1) WALK-FORWARD --------------------------------------------------------
    print("Gauntlet 1/3: walk-forward (3 folds, 27-point grid per fold)...", file=sys.stderr)
    folds = [
        (dates[0], dates[int(N * .40) - 1], dates[int(N * .40)], dates[int(N * .60) - 1]),
        (dates[int(N * .20)], dates[int(N * .60) - 1], dates[int(N * .60)], dates[int(N * .80) - 1]),
        (dates[int(N * .40)], dates[int(N * .80) - 1], dates[int(N * .80)], dates[N - 1]),
    ]
    wf = []
    for f_i, (tr_s, tr_e, te_s, te_e) in enumerate(folds):
        best, best_params = None, None
        for stop in GRID_STOPS:
            for tgt in GRID_TGTS:
                for trail in GRID_TRAILS:
                    m, _ = sim("pct", stop, tgt, trail, sd=tr_s, ed=tr_e)
                    if best is None or m["cagr_pct"] > best["cagr_pct"]:
                        best, best_params = m, (stop, tgt, trail)
        tuned_test, _ = sim("pct", *best_params, sd=te_s, ed=te_e)
        live_test, _ = sim("pct", *LIVE, sd=te_s, ed=te_e)
        wf.append({
            "fold": f_i + 1, "train": [tr_s, tr_e], "test": [te_s, te_e],
            "tuned_params": {"stop": best_params[0], "target": best_params[1], "trail": best_params[2]},
            "tuned_train_cagr": best["cagr_pct"], "tuned_test_cagr": tuned_test["cagr_pct"],
            "live_test_cagr": live_test["cagr_pct"], "live_test_maxdd": live_test["maxdd_pct"],
            "live_test_trades": live_test["trades"],
        })
    live_profitable_folds = sum(1 for f in wf if f["live_test_cagr"] > 0)
    overfit_gap = round(statistics.mean(f["tuned_train_cagr"] - f["tuned_test_cagr"] for f in wf), 1)
    wf_pass = live_profitable_folds >= 2
    report["walk_forward"] = {"folds": wf, "live_profitable_folds": f"{live_profitable_folds}/3",
                              "mean_train_to_test_degradation_pts": overfit_gap, "PASS": wf_pass}

    # ---- 2) MONTE CARLO ---------------------------------------------------------
    print("Gauntlet 2/3: Monte Carlo (5000 bootstrap paths)...", file=sys.stderr)
    base_m, base_trades = sim("account", *LIVE, **POLICY_C)
    closed = [t for t in base_trades
              if t["kind"] != "open_at_end" and t.get("eq_at_entry")]
    years = 0.0
    # actual span of the base run for CAGR annualization
    curve_days = N  # full window
    years = curve_days / 252.0
    if len(closed) < 8:
        report["monte_carlo"] = {"PASS": False, "note": f"only {len(closed)} closed trades — too few to resample"}
        mc_pass = False
    else:
        rf = [(t["pl"] / (t["entry"] * t["shares"]),
               (t["entry"] * t["shares"]) / t["eq_at_entry"]) for t in closed]
        rng = random.Random(42)
        finals, dds = [], []
        for _ in range(MC_PATHS):
            eq, peak, dd = args.equity, args.equity, 0.0
            for _ in range(len(rf)):
                r, f = rf[rng.randrange(len(rf))]
                eq *= (1 + r * f)
                peak = max(peak, eq)
                dd = min(dd, eq / peak - 1)
            finals.append(eq)
            dds.append(dd)
        finals.sort()
        dds.sort()

        def pct(arr, p):
            return arr[min(len(arr) - 1, int(p / 100 * len(arr)))]
        cagr = lambda e: ((e / args.equity) ** (1 / years) - 1) * 100
        p_loss = sum(1 for e in finals if e < args.equity) / len(finals)
        mc = {
            "base_run": base_m, "resampled_trades": len(rf), "paths": MC_PATHS,
            "final_equity": {"p5": round(pct(finals, 5), 0), "p50": round(pct(finals, 50), 0),
                             "p95": round(pct(finals, 95), 0)},
            "cagr_pct": {"p5": round(cagr(pct(finals, 5)), 1), "p50": round(cagr(pct(finals, 50)), 1),
                         "p95": round(cagr(pct(finals, 95)), 1)},
            "trade_level_maxdd_pct": {"p5_worst": round(pct(dds, 5) * 100, 1),
                                      "p50": round(pct(dds, 50) * 100, 1)},
            "prob_ending_below_start_pct": round(p_loss * 100, 1),
            "note": "trade-level DD understates intra-trade drawdown — treat as optimistic floor",
        }
        mc_pass = (cagr(pct(finals, 50)) > 0 and p_loss < 0.25 and pct(dds, 5) > -0.50)
        mc["PASS"] = mc_pass
        report["monte_carlo"] = mc

    # ---- 3) PARAMETER JITTER ------------------------------------------------------
    print("Gauntlet 3/3: parameter jitter (27 neighbors + 4 equity scales)...", file=sys.stderr)
    neigh = []
    for stop in GRID_STOPS:
        for tgt in GRID_TGTS:
            for trail in GRID_TRAILS:
                m, _ = sim("account", stop, tgt, trail, **POLICY_C)
                neigh.append({"stop": stop, "target": tgt, "trail": trail, **m})
    cagrs = [n["cagr_pct"] for n in neigh]
    mean_c, stdev_c = statistics.mean(cagrs), statistics.pstdev(cagrs)
    cv = round(stdev_c / abs(mean_c), 2) if mean_c else None
    worst = min(neigh, key=lambda n: n["cagr_pct"])
    scales = []
    for eq in (300, 450, 600, 900):
        m, _ = sim("account", *LIVE, equity=eq, **POLICY_C)
        scales.append({"equity": eq, **m})
    jit_pass = all(c > 0 for c in cagrs) and (cv is not None and cv < 0.6) \
        and all(s["cagr_pct"] > 0 for s in scales)
    report["parameter_jitter"] = {
        "neighborhood_mean_cagr_pct": round(mean_c, 1),
        "neighborhood_stdev_pts": round(stdev_c, 1),
        "coefficient_of_variation": cv,
        "worst_neighbor": worst,
        "profitable_neighbors": f"{sum(1 for c in cagrs if c > 0)}/{len(cagrs)}",
        "equity_scales": scales,
        "PASS": jit_pass,
    }

    # ---- verdict -----------------------------------------------------------------
    passes = [report["walk_forward"]["PASS"], mc_pass, report["parameter_jitter"]["PASS"]]
    report["VERDICT"] = "PASS" if all(passes) else ("WARN" if sum(passes) >= 2 else "FAIL")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

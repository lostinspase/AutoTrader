#!/usr/bin/env python3
"""
Ark universe-change gauntlet — robustness battery for adding SMH + XLE.

The Genesis gauntlet tests stop/target/trail parameters and does not apply to a
UNIVERSE change, so this is the Ark-native equivalent. One backtest showing
+1.69 CAGR is not sufficient evidence to modify a live engine trading real money.

FOUR TESTS:
  1. WALK-FORWARD    split history into 3 folds; the addition must help (or at
                     least not hurt) in the majority of UNSEEN windows, not just
                     in aggregate where one era can carry everything.
  2. PARAMETER JITTER re-run across the cap/top_n neighbourhood. An edge that
                     exists at exactly one setting is curve-fit.
  3. DROP-ONE        remove each added ETF in turn. Tells us whether the gain is
                     broad or rests entirely on one symbol.
  4. START-DATE      vary the start year. A result that depends on beginning in
     SENSITIVITY     a specific year is an artifact of that entry point.

PASS BAR (set BEFORE running, so the result cannot be rationalised afterwards):
  - walk-forward: addition better in >= 2 of 3 test folds
  - jitter:       positive delta in >= 3 of 4 cap/top_n settings
  - drop-one:     no single symbol accounts for ALL of the gain
  - start-date:   positive delta in >= 3 of 4 start years
  - drawdown:     maxDD must not worsen by more than 2 percentage points

STANDING CAVEAT: SMH and XLE were chosen in 2026 knowing semis and energy led
this cycle. The gauntlet tests ROBUSTNESS; it cannot remove selection bias.
"""

import contextlib
import importlib.util
import io
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

BASE = {"SPLG": "us_equity", "IJR": "us_equity",
        "VEA": "intl_equity", "VWO": "intl_equity",
        "TLT": "treasuries", "IEF": "treasuries",
        "LQD": "credit", "GLD": "gold", "DBC": "commodities", "VNQ": "reits"}
ADDED = {"SMH": "semis", "XLE": "energy"}
BOTH = {**BASE, **ADDED}


def trial(universe, cap=0.40, n=4):
    spec = importlib.util.spec_from_file_location("ark", os.path.join(HERE, "ark_backtest.py"))
    ark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ark)
    ark.UNIVERSE = dict(universe)
    ark.CLASS_CAP = cap
    ark.TOP_N = n
    with contextlib.redirect_stdout(io.StringIO()):
        ark.run()
    with open(os.path.join(HERE, "ark_backtest_results.json")) as f:
        return json.load(f)


def curve_rets(r):
    ec = r["equity_curve"]
    return ([ec[i]["ark"] / ec[i - 1]["ark"] - 1 for i in range(1, len(ec))],
            [ec[i]["spy"] / ec[i - 1]["spy"] - 1 for i in range(1, len(ec))],
            [ec[i]["date"] for i in range(1, len(ec))])


def cagr_from(rets):
    eq = 1.0
    for x in rets:
        eq *= 1 + x
    yrs = len(rets) / 12
    return (eq ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0


def maxdd(rets):
    eq = peak = 1.0
    dd = 0.0
    for x in rets:
        eq *= 1 + x
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    return dd * 100


def main():
    report = {}
    print("Ark universe gauntlet: adding SMH + XLE\n", file=sys.stderr)

    cur, both = trial(BASE), trial(BOTH)
    c_r, _, c_d = curve_rets(cur)
    b_r, _, _ = curve_rets(both)

    # ---- 1. WALK-FORWARD -----------------------------------------------------
    print("1/4 walk-forward (3 folds)...", file=sys.stderr)
    n = min(len(c_r), len(b_r))
    fold = n // 3
    folds = []
    for k in range(3):
        a, b = k * fold, (k + 1) * fold if k < 2 else n
        cc, bb = cagr_from(c_r[a:b]), cagr_from(b_r[a:b])
        folds.append({"fold": k + 1, "window": f"{c_d[a]} .. {c_d[b-1]}",
                      "current_cagr": round(cc, 2), "with_adds_cagr": round(bb, 2),
                      "delta": round(bb - cc, 2), "better": bb > cc})
    wf_pass = sum(f["better"] for f in folds) >= 2
    report["walk_forward"] = {"folds": folds,
                              "better_in": f"{sum(f['better'] for f in folds)}/3",
                              "PASS": wf_pass}

    # ---- 2. PARAMETER JITTER -------------------------------------------------
    print("2/4 parameter jitter (cap x top_n)...", file=sys.stderr)
    jit = []
    for cap, tn in [(0.40, 4), (0.30, 4), (0.30, 5), (0.25, 5)]:
        c = trial(BASE, cap, tn)["ark"]
        b = trial(BOTH, cap, tn)["ark"]
        jit.append({"config": f"cap{int(cap*100)}_top{tn}",
                    "current_cagr": c["cagr_pct"], "with_adds_cagr": b["cagr_pct"],
                    "delta": round(b["cagr_pct"] - c["cagr_pct"], 2),
                    "dd_current": c["max_dd_pct"], "dd_with_adds": b["max_dd_pct"],
                    "better": b["cagr_pct"] > c["cagr_pct"]})
    jit_pass = sum(j["better"] for j in jit) >= 3
    report["parameter_jitter"] = {"configs": jit,
                                  "better_in": f"{sum(j['better'] for j in jit)}/4",
                                  "PASS": jit_pass}

    # ---- 3. DROP-ONE ---------------------------------------------------------
    print("3/4 drop-one...", file=sys.stderr)
    base_c = cur["ark"]["cagr_pct"]
    both_c = both["ark"]["cagr_pct"]
    drops = {}
    for sym in ADDED:
        uni = {**BASE, **{k: v for k, v in ADDED.items() if k != sym}}
        drops[f"without_{sym}"] = trial(uni)["ark"]["cagr_pct"]
    # gain must not rest entirely on one symbol
    solo_gains = {k: round(v - base_c, 2) for k, v in drops.items()}
    total_gain = both_c - base_c
    concentrated = any(abs(g - total_gain) < 0.05 and total_gain > 0
                       for g in solo_gains.values())
    d1_pass = (not concentrated) and all(v >= base_c - 0.5 for v in drops.values())
    report["drop_one"] = {"base_cagr": base_c, "both_cagr": both_c,
                          "each_alone": drops, "gain_vs_base": solo_gains,
                          "gain_concentrated_in_one_symbol": concentrated,
                          "PASS": d1_pass}

    # ---- 4. START-DATE SENSITIVITY ------------------------------------------
    print("4/4 start-date sensitivity...", file=sys.stderr)
    starts = []
    for yr in ("2010", "2013", "2016", "2019"):
        i = next((k for k, d in enumerate(c_d) if d >= yr), None)
        if i is None or n - i < 36:
            continue
        cc, bb = cagr_from(c_r[i:n]), cagr_from(b_r[i:n])
        starts.append({"from": yr, "current_cagr": round(cc, 2),
                       "with_adds_cagr": round(bb, 2), "delta": round(bb - cc, 2),
                       "better": bb > cc})
    sd_pass = sum(s["better"] for s in starts) >= max(1, len(starts) - 1)
    report["start_date"] = {"windows": starts,
                            "better_in": f"{sum(s['better'] for s in starts)}/{len(starts)}",
                            "PASS": sd_pass}

    # ---- drawdown guard ------------------------------------------------------
    dd_delta = both["ark"]["max_dd_pct"] - cur["ark"]["max_dd_pct"]
    dd_pass = dd_delta > -2.0
    report["drawdown_guard"] = {"current": cur["ark"]["max_dd_pct"],
                                "with_adds": both["ark"]["max_dd_pct"],
                                "delta_pts": round(dd_delta, 2),
                                "limit_pts": -2.0, "PASS": dd_pass}

    allp = all([wf_pass, jit_pass, d1_pass, sd_pass, dd_pass])
    report["VERDICT"] = {
        "PASS": allp,
        "summary": ("ADOPT — addition is robust across folds, settings, symbols and "
                    "start dates" if allp else
                    "REJECT — the gain does not survive the robustness battery"),
        "caveat": ("SMH/XLE selected in 2026 with knowledge of which sectors led; "
                   "expect a smaller live edge than backtested."),
    }
    print(json.dumps(report, indent=1))
    with open(os.path.join(HERE, "ark_universe_gauntlet_results.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()

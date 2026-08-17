#!/usr/bin/env python3
"""
ARK2 gauntlet — robustness battery for a PROPOSED 4th strategy (thematic sleeve).

ARK2 = a separate Ark-engine sleeve trading a concentrated thematic universe
(SMH, XLE + defensive fallbacks) alongside the existing 10-asset Ark. The pitch:
sleeve correlation ~0.055, so 50/50 gives Sharpe 1.12 vs 0.80 for folding SMH/XLE
into one engine.

WHY A HARSHER BAR THAN THE FOLD: a 4-asset universe with 2 slots is far easier to
curve-fit than a 12-asset one, the constituents were chosen in ~1 minute with 2026
hindsight, and this asks for $1,000 of NEW capital rather than reusing a live
engine. So beyond the fold's five gates this adds:
  6. UNIVERSE PERTURBATION  swap/drop constituents. If the result only works with
                            exactly these 4 tickers, it is a curve fit.
  7. SLEEVE-CORRELATION     the 0.055 correlation IS the entire thesis. If it is
     STABILITY              unstable across sub-periods, the Sharpe gain is an
                            artifact of one era.
  8. PAIR-VS-DEPOSIT        compare like-for-like on EQUAL capital, so the answer
                            is not just "more money deployed earns more".

PASS BAR (fixed BEFORE running):
  - walk-forward:  50/50 blend beats Ark(10) alone in >= 2 of 3 folds
  - jitter:        positive in >= 3 of 4 cap/top_n settings
  - universe perturbation: >= 4 of 6 variants keep Sharpe > Ark(10)'s
  - correlation stability: sleeve corr < 0.50 in ALL 3 folds
  - drawdown:      50/50 blend maxDD not worse than Ark(10) alone
  - equal-capital: 50/50 blend Sharpe > Ark(12)-folded Sharpe
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
FOLDED = {**BASE, "SMH": "semis", "XLE": "energy"}
ARK2 = {"SMH": "semis", "XLE": "energy", "TLT": "treasuries", "GLD": "gold"}


def trial(universe, cap=0.40, n=4):
    spec = importlib.util.spec_from_file_location("ark", os.path.join(HERE, "ark_backtest.py"))
    a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a)
    a.UNIVERSE = dict(universe)
    a.CLASS_CAP = cap
    a.TOP_N = n
    with contextlib.redirect_stdout(io.StringIO()):
        a.run()
    with open(os.path.join(HERE, "ark_backtest_results.json")) as f:
        return json.load(f)


def rets(r):
    ec = r["equity_curve"]
    return ([ec[i]["ark"] / ec[i - 1]["ark"] - 1 for i in range(1, len(ec))],
            [ec[i]["date"] for i in range(1, len(ec))])


def stats(rr):
    eq = peak = 1.0
    dd = 0.0
    for x in rr:
        eq *= 1 + x
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    yrs = len(rr) / 12
    vol = st.pstdev(rr) * (12 ** 0.5)
    cagr = (eq ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    sharpe = (st.mean(rr) * 12 - 0.02) / vol if vol else 0
    return {"cagr": round(cagr, 2), "dd": round(dd * 100, 1), "sharpe": round(sharpe, 2)}


def corr(a, b):
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 0


def blend(a, b, w=0.5):
    n = min(len(a), len(b))
    return [w * x + (1 - w) * y for x, y in zip(a[-n:], b[-n:])]


def main():
    rep = {}
    print("ARK2 gauntlet\n", file=sys.stderr)

    base_r, base_d = rets(trial(BASE))
    fold_r, _ = rets(trial(FOLDED))
    a2_r, _ = rets(trial(ARK2, cap=0.60, n=2))
    n = min(len(base_r), len(a2_r))
    base_r, a2_r, base_d = base_r[-n:], a2_r[-n:], base_d[-n:]
    fold_r = fold_r[-n:]
    bl = blend(base_r, a2_r)

    s_base, s_fold, s_a2, s_bl = stats(base_r), stats(fold_r), stats(a2_r), stats(bl)
    rep["headline"] = {"ark10": s_base, "ark12_folded": s_fold,
                       "ark2_standalone": s_a2, "blend_50_50": s_bl,
                       "sleeve_correlation": round(corr(base_r, a2_r), 3)}

    # ---- 1. WALK-FORWARD -----------------------------------------------------
    print("1/6 walk-forward...", file=sys.stderr)
    f = n // 3
    folds = []
    for k in range(3):
        a, b = k * f, (k + 1) * f if k < 2 else n
        sb, sn = stats(base_r[a:b]), stats(blend(base_r[a:b], a2_r[a:b]))
        folds.append({"fold": k + 1, "window": f"{base_d[a]}..{base_d[b-1]}",
                      "ark10_sharpe": sb["sharpe"], "blend_sharpe": sn["sharpe"],
                      "better": sn["sharpe"] > sb["sharpe"]})
    wf = sum(x["better"] for x in folds) >= 2
    rep["walk_forward"] = {"folds": folds, "better_in": f"{sum(x['better'] for x in folds)}/3",
                           "PASS": wf}

    # ---- 2. CORRELATION STABILITY (the whole thesis) -------------------------
    print("2/6 correlation stability...", file=sys.stderr)
    cs = []
    for k in range(3):
        a, b = k * f, (k + 1) * f if k < 2 else n
        cs.append({"fold": k + 1, "corr": round(corr(base_r[a:b], a2_r[a:b]), 3)})
    corr_pass = all(abs(x["corr"]) < 0.50 for x in cs)
    rep["correlation_stability"] = {"folds": cs, "limit": 0.50, "PASS": corr_pass}

    # ---- 3. PARAMETER JITTER -------------------------------------------------
    print("3/6 parameter jitter...", file=sys.stderr)
    jit = []
    for cap, tn in [(0.60, 2), (0.50, 2), (0.60, 3), (0.40, 2)]:
        r2, _ = rets(trial(ARK2, cap, tn))
        s = stats(blend(base_r, r2[-n:]))
        jit.append({"config": f"cap{int(cap*100)}_top{tn}", "blend_sharpe": s["sharpe"],
                    "blend_cagr": s["cagr"], "better": s["sharpe"] > s_base["sharpe"]})
    jit_pass = sum(x["better"] for x in jit) >= 3
    rep["parameter_jitter"] = {"configs": jit,
                               "better_in": f"{sum(x['better'] for x in jit)}/4", "PASS": jit_pass}

    # ---- 4. UNIVERSE PERTURBATION (curve-fit detector) ----------------------
    print("4/6 universe perturbation...", file=sys.stderr)
    variants = {
        "as_designed": ARK2,
        "drop_GLD": {"SMH": "semis", "XLE": "energy", "TLT": "treasuries"},
        "drop_XLE": {"SMH": "semis", "TLT": "treasuries", "GLD": "gold"},
        "drop_SMH": {"XLE": "energy", "TLT": "treasuries", "GLD": "gold"},
        "swap_SMH_for_XLK": {"XLK": "tech", "XLE": "energy", "TLT": "treasuries", "GLD": "gold"},
        "add_IEF": {**ARK2, "IEF": "treasuries"},
    }
    pert = []
    for name, uni in variants.items():
        try:
            r2, _ = rets(trial(uni, cap=0.60, n=2))
            s = stats(blend(base_r, r2[-n:]))
            pert.append({"variant": name, "blend_sharpe": s["sharpe"],
                         "blend_cagr": s["cagr"], "beats_ark10": s["sharpe"] > s_base["sharpe"]})
        except Exception as e:
            pert.append({"variant": name, "error": str(e)[:80], "beats_ark10": False})
    pert_pass = sum(x.get("beats_ark10") for x in pert) >= 4
    rep["universe_perturbation"] = {"variants": pert,
                                    "beats_in": f"{sum(x.get('beats_ark10') for x in pert)}/6",
                                    "PASS": pert_pass}

    # ---- 5. DRAWDOWN GUARD ---------------------------------------------------
    dd_pass = s_bl["dd"] >= s_base["dd"] - 0.01
    rep["drawdown_guard"] = {"ark10_dd": s_base["dd"], "blend_dd": s_bl["dd"],
                             "PASS": dd_pass}

    # ---- 6. EQUAL-CAPITAL FAIRNESS ------------------------------------------
    # Is the split better per-dollar, or only because more money is deployed?
    fair_pass = s_bl["sharpe"] > s_fold["sharpe"]
    rep["equal_capital"] = {
        "note": "compares risk-adjusted return PER DOLLAR, removing the deposit effect",
        "ark12_folded_sharpe": s_fold["sharpe"], "blend_sharpe": s_bl["sharpe"],
        "PASS": fair_pass}

    gates = [wf, corr_pass, jit_pass, pert_pass, dd_pass, fair_pass]
    rep["VERDICT"] = {
        "gates_passed": f"{sum(gates)}/6",
        "PASS": all(gates),
        "summary": ("BUILD ARK2 — the split survives perturbation and the low sleeve "
                    "correlation is stable" if all(gates) else
                    "DO NOT BUILD — keep SMH/XLE folded into the existing engine"),
        "caveat": ("constituents chosen in 2026 with sector hindsight; a 4-asset/2-slot "
                   "universe is inherently more fragile than the 12-asset fold."),
    }
    print(json.dumps(rep, indent=1))
    with open(os.path.join(HERE, "ark2_gauntlet_results.json"), "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()

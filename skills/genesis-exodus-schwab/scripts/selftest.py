#!/usr/bin/env python3
"""
Genesis+Exodus self-test / regression suite.

A screener bug once survived for weeks because NOTHING asserted "the discovery
universe must contain JPM, XOM, LLY." This is that assertion — plus sanity checks on
the data layer, the advisory sensors, and the deterministic safety core.

Run before relying on a scan (cheap once FMP histories are daily-cached):
    python3 scripts/selftest.py

Exits 0 if all checks pass, 1 otherwise. Network-dependent checks degrade to a
SKIP (not a FAIL) when FMP is unreachable, so an outage doesn't masquerade as a
universe regression — but the universe invariant itself is a hard FAIL if FMP is up
and the NYSE names are missing.
"""
import json, os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fmp  # noqa: E402

results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        # An exception is NEVER a benign outage: fmp._get returns _error/_http_error
        # dicts on network failure, and every network-dependent test returns None
        # (SKIP) itself on unreachable data. An exception here means broken code or
        # state (e.g. ops.py preflight crashed, corrupt cache JSON) — exactly what
        # this suite exists to catch. Hard FAIL, nonzero exit.
        # (Note: fmp._key() raises SystemExit, a BaseException, which escapes this
        # handler and aborts the suite nonzero if the API key vanishes — loud, OK.)
        ok, detail = False, f"EXCEPTION: {e}"
    tag = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    results.append((tag, name, detail))
    print(f"[{tag}] {name} — {detail}")


# ---- universe invariants (the regression that would have caught the NYSE bug) ----
def t_universe_has_nyse():
    rows = fmp.screener(["limit=120"])
    if not isinstance(rows, list) or not rows:
        return None, "screener unreachable — SKIP (not treated as a regression)"
    syms = {r.get("symbol") for r in rows}
    exch = {r.get("exchange") for r in rows}
    must = {"JPM", "XOM", "LLY"}  # canonical NYSE S&P leaders
    missing = must - syms
    if missing:
        return False, f"NYSE leaders MISSING from default screener: {missing} (NASDAQ-only regression?)"
    if "NYSE" not in exch:
        return False, f"no NYSE rows at all; exchanges seen={exch}"
    return True, f"{len(syms)} names span exchanges={exch & {'NYSE','NASDAQ'}}"


def t_universe_multisector():
    rows = fmp.screener(["limit=60"])
    if not isinstance(rows, list) or not rows:
        return None, "screener unreachable — SKIP"
    secs = {r.get("sector") for r in rows if r.get("sector")}
    return (len(secs) >= 4), f"{len(secs)} sectors in top 60: {sorted(secs)}"


# ---- data-layer sanity ----
def t_regime_shape():
    r = fmp.regime()
    need = {"SPY", "QQQ", "IWM", "vix", "computed_class"}
    if not isinstance(r, dict) or not need <= set(r):
        return None, f"regime unreachable/odd — SKIP ({str(r)[:80]})"
    if all(r[s].get("price") is None for s in ("SPY", "QQQ", "IWM")) and r.get("vix") is None:
        return None, "regime data unreachable (all index quotes + VIX None) — SKIP"
    return (r["computed_class"] in ("normal", "cautious", "defensive", "crash")), \
        f"class={r['computed_class']} vix={r.get('vix')}"


def t_indicators_fields():
    r = fmp.indicators("AAPL")
    if r.get("error"):
        return None, f"indicators unreachable — SKIP ({r.get('error')})"
    need = {"genesis_trend_template_pass", "ret63d", "atr20", "fiftytwo_week_complete", "history_days"}
    miss = need - set(r)
    if miss:
        return False, f"missing fields: {miss}"
    return True, f"AAPL 52wk_complete={r['fiftytwo_week_complete']} hist_days={r['history_days']}"


def t_52wk_guard():
    # The guard must null out 52wk levels when history is short.
    src = open(os.path.join(HERE, "fmp.py")).read()
    ok = "fiftytwo_complete = len(h) >= 252" in src and "if fiftytwo_complete else None" in src
    return ok, "indicators() requires >=252 bars for hi52/lo52" if ok else "52wk guard not found in source"


# ---- advisory sensors ----
def t_rs_blend():
    r = fmp.rs("NVDA")
    if r.get("error"):
        return None, "rs unreachable — SKIP"
    return ("rs_excess_vs_spy" in r), f"NVDA rs_excess={r.get('rs_excess_vs_spy')} leader={r.get('is_leader')}"


def t_breadth():
    r = fmp.breadth()
    if r.get("breadth_pct_50dma") is None:
        return None, "breadth unreachable — SKIP"
    return True, f"{r['breadth_pct_50dma']}% above 50dma -> {r['exposure_hint']}"


def t_correlation():
    r = fmp.correlation(["NVDA", "GOOGL", "JPM"])
    if r.get("error"):
        return None, f"correlation unreachable — SKIP ({r['error']})"
    return ("avg_corr_to_others" in r), f"window={r.get('window_days')}d cluster={r.get('highly_correlated_cluster')}"


# ---- safety core (deterministic, no network) ----
def t_preflight_fields():
    out = subprocess.run([sys.executable, os.path.join(HERE, "ops.py"), "preflight", "--nav", "10000", "--date", "1970-01-01"],
                         capture_output=True, text=True, timeout=30)
    d = json.loads(out.stdout)
    need = {"new_buys_allowed", "buys_today", "buy_cap_reached", "mechanical_stops_in_last3"}
    miss = need - set(d)
    return (not miss), (f"missing: {miss}" if miss else f"new_buys_allowed={d['new_buys_allowed']} buys_today={d['buys_today']} (pinned --date 1970-01-01 fixture, not today's gate)")


for name, fn in [
    ("universe: default screener contains NYSE leaders (JPM/XOM/LLY)", t_universe_has_nyse),
    ("universe: spans >=4 sectors", t_universe_multisector),
    ("data: regime shape + class", t_regime_shape),
    ("data: indicators field set", t_indicators_fields),
    ("data: 52-week-window guard present", t_52wk_guard),
    ("sensor: blended RS vs SPY", t_rs_blend),
    ("sensor: sector breadth", t_breadth),
    ("sensor: correlation matrix", t_correlation),
    ("safety: preflight advisory fields", t_preflight_fields),
]:
    check(name, fn)

n_fail = sum(1 for t, *_ in results if t == "FAIL")
n_skip = sum(1 for t, *_ in results if t == "SKIP")
n_pass = sum(1 for t, *_ in results if t == "PASS")
print(f"\n{n_pass} passed, {n_fail} failed, {n_skip} skipped")
sys.exit(1 if n_fail else 0)

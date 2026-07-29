#!/usr/bin/env python3
"""
Genesis + Exodus — SEC filings sensor layer (3spread API via py3spread).

ADVISORY ONLY: these sensors inform candidate scoring and rotation flags; they never
decide a trade (SKILL.md §7). Two signals with actual evidence behind them:

  1. INSIDER CLUSTER BUYING (Form 4, open-market code P): >=2 DISTINCT insiders buying
     within a trailing window. A cluster is the documented signal — one insider buying
     is noise. Also flags heavy selling-into-strength on names we hold.
  2. FRESH 13D (activist stake): timely (filed within days), dated, public catalyst —
     used by the Exodus rebound engine to distinguish "quality pullback with a catalyst"
     from a falling knife. 13G (passive) is tracked but weighted lower.

Key: state/sec.env -> THREESPREAD_API_KEY  (free at 3spread.com/auth/signup)
Data coverage: early 2021 onward. Missing key / API error -> {"error": ...} and the
affected name simply gets no sensor bonus (never a blocker for monitoring).

CLI:
  insider SYM [--days 90]        cluster-buy metrics + buy/sell ratio for one name
  insider-multi SYM... [--days 90]
  activist SYM [--days 180]      recent 13D/13G filings for one name
  export-signals --start YYYY-MM-DD [--end YYYY-MM-DD] SYM...
                                 historical cluster-buy dates -> state/insider_signals.json
                                 (input for backtest.py --insider-signals)
  raw SYM                        dump one raw transactions page (field calibration)
"""

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
ENV_FILE = os.path.join(STATE, "sec.env")
SIGNALS_FILE = os.path.join(STATE, "insider_signals.json")

CLUSTER_WINDOW_DAYS = 30      # window in which >=2 distinct buyers form a cluster
CLUSTER_MIN_OWNERS = 2


def _key():
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("THREESPREAD_API_KEY="):
                    v = line.split("=", 1)[1].strip()
                    if v and not v.startswith("<"):
                        return v
    except FileNotFoundError:
        pass
    return None


def _client():
    key = _key()
    if not key:
        print(json.dumps({"error": "no THREESPREAD_API_KEY in state/sec.env "
                                   "(sign up free at 3spread.com/auth/signup)"}))
        sys.exit(3)
    try:
        from py3spread import Client
    except ImportError:
        print(json.dumps({"error": "py3spread not installed: "
                                   "python3 -m pip install --user --break-system-packages py3spread"}))
        sys.exit(3)
    return Client(api_key=key)


def _owner_id(txn):
    """Owner identity. Calibrated 2026-07 against live API: filer_cik is a LIST."""
    fc = txn.get("filer_cik")
    if isinstance(fc, list) and fc:
        return str(fc[0])
    if fc:
        return str(fc)
    for k in ("filer_name", "rpt_owner_cik", "reporting_owner_cik", "owner_name"):
        if txn.get(k):
            return str(txn[k])
    return None


def _txn_value(txn):
    v = txn.get("transaction_total_value") or txn.get("transaction_value")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    try:
        sh = float(txn.get("transaction_shares") or 0)
        px = float(txn.get("transaction_price_per_share") or 0)
        return sh * px
    except (TypeError, ValueError):
        return 0.0


def _txn_date(txn):
    return (txn.get("transaction_date") or txn.get("date") or "")[:10]


def _fetch_txns(client, symbol, start, end, code):
    """Open-market transactions for a symbol, one code ('P' buy / 'S' sell).
    The API needs BOTH ends of the window and caps spans at 730 days — chunk."""
    out = []
    try:
        s = dt.date.fromisoformat(start)
        e = dt.date.fromisoformat(end)
        while s <= e:
            w_end = min(s + dt.timedelta(days=700), e)
            for t in client.insiders.iter_transactions(
                    issuer_ticker=symbol, transaction_code=code,
                    transaction_start=s.isoformat(), transaction_end=w_end.isoformat()):
                out.append(t)
                if len(out) >= 5000:
                    return out
            s = w_end + dt.timedelta(days=1)
    except Exception as e:  # API/auth/network — sensor degrades, never crashes a scan
        return {"error": f"{type(e).__name__}: {e}"}
    return out


def _cluster_dates(buys):
    """Dates on which a >=CLUSTER_MIN_OWNERS distinct-buyer cluster exists in the
    trailing CLUSTER_WINDOW_DAYS. Returns sorted unique YYYY-MM-DD strings."""
    events = sorted((_txn_date(t), _owner_id(t)) for t in buys
                    if _txn_date(t) and _owner_id(t))
    dates = sorted({d for d, _ in events})
    clusters = []
    for d in dates:
        lo = (dt.date.fromisoformat(d) - dt.timedelta(days=CLUSTER_WINDOW_DAYS)).isoformat()
        owners = {o for (td, o) in events if lo <= td <= d}
        if len(owners) >= CLUSTER_MIN_OWNERS:
            clusters.append(d)
    return clusters


def cmd_insider(symbol, days):
    c = _client()
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    end = dt.date.today().isoformat()
    buys = _fetch_txns(c, symbol, start, end, "P")
    sells = _fetch_txns(c, symbol, start, end, "S")
    if isinstance(buys, dict) or isinstance(sells, dict):
        err = buys if isinstance(buys, dict) else sells
        print(json.dumps({"symbol": symbol, **err}))
        return
    buy_owners = {_owner_id(t) for t in buys if _owner_id(t)}
    sell_owners = {_owner_id(t) for t in sells if _owner_id(t)}
    buy_val = sum(_txn_value(t) for t in buys)
    sell_val = sum(_txn_value(t) for t in sells)
    ratio = None
    try:
        r = c.insiders.buy_sell_ratio(ticker=symbol, window_days=days)
        ratio = r
    except Exception:
        pass
    clusters = _cluster_dates(buys)
    print(json.dumps({
        "symbol": symbol, "window_days": days,
        "open_market_buys": len(buys), "distinct_buyers": len(buy_owners),
        "open_market_sells": len(sells), "distinct_sellers": len(sell_owners),
        "buy_value": round(buy_val, 0), "sell_value": round(sell_val, 0),
        "cluster_buy": bool(clusters), "latest_cluster_date": clusters[-1] if clusters else None,
        "heavy_selling": sell_val > max(3 * buy_val, 250_000) and len(sell_owners) >= 2,
        "buy_sell_ratio_api": ratio,
    }, indent=2))


def cmd_insider_multi(symbols, days):
    for s in symbols:
        cmd_insider(s, days)


def cmd_activist(symbol, days):
    c = _client()
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try:
        page = c.beneficial_ownership.list(ticker=symbol, accepted_start=start, limit=50)
    except Exception as e:
        print(json.dumps({"symbol": symbol, "error": f"{type(e).__name__}: {e}"}))
        return
    rows = page.get("data") or page.get("results") or (page if isinstance(page, list) else [])
    filings = []
    for r in rows:
        st = (r.get("schedule_type") or r.get("form_type") or "").upper()
        filings.append({
            "schedule_type": st,
            "accepted": r.get("accepted_time") or r.get("accepted") or r.get("filed_at"),
            "event_date": r.get("event_date"),
            "amendment_no": r.get("amendment_no"),
            "source_url": r.get("source_url"),
        })
    fresh_13d = [f for f in filings if "13D" in f["schedule_type"] and not f.get("amendment_no")]
    print(json.dumps({
        "symbol": symbol, "window_days": days, "filings": filings,
        "fresh_13d": bool(fresh_13d),
        "note": "fresh 13D = activist crossed 5% recently — Exodus catalyst (advisory)",
    }, indent=2))


def cmd_export_signals(symbols, start, end):
    c = _client()
    end = end or dt.date.today().isoformat()
    signals, errors = {}, {}
    for i, sym in enumerate(symbols):
        buys = _fetch_txns(c, sym, start, end, "P")
        if isinstance(buys, dict):
            errors[sym] = buys["error"]
            continue
        signals[sym] = _cluster_dates(buys)
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(symbols)}", file=sys.stderr)
    os.makedirs(STATE, exist_ok=True)
    with open(SIGNALS_FILE, "w") as f:
        json.dump({"start": start, "end": end, "cluster_window_days": CLUSTER_WINDOW_DAYS,
                   "min_owners": CLUSTER_MIN_OWNERS, "signals": signals}, f, indent=1)
    n_with = sum(1 for v in signals.values() if v)
    print(json.dumps({"written": SIGNALS_FILE, "symbols": len(signals),
                      "symbols_with_clusters": n_with,
                      "total_cluster_dates": sum(len(v) for v in signals.values()),
                      "errors": errors}))


def cmd_raw(symbol):
    c = _client()
    start = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    try:
        page = c.insiders.transactions(issuer_ticker=symbol, transaction_code="P",
                                       transaction_start=start, limit=3)
        print(json.dumps(page, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))


def main():
    ap = argparse.ArgumentParser(prog="sec.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("insider"); sp.add_argument("symbol"); sp.add_argument("--days", type=int, default=90)
    sp = sub.add_parser("insider-multi"); sp.add_argument("symbols", nargs="+"); sp.add_argument("--days", type=int, default=90)
    sp = sub.add_parser("activist"); sp.add_argument("symbol"); sp.add_argument("--days", type=int, default=180)
    sp = sub.add_parser("export-signals"); sp.add_argument("symbols", nargs="+")
    sp.add_argument("--start", required=True); sp.add_argument("--end", default=None)
    sp = sub.add_parser("raw"); sp.add_argument("symbol")
    a = ap.parse_args()
    if a.cmd == "insider":
        cmd_insider(a.symbol.upper(), a.days)
    elif a.cmd == "insider-multi":
        cmd_insider_multi([s.upper() for s in a.symbols], a.days)
    elif a.cmd == "activist":
        cmd_activist(a.symbol.upper(), a.days)
    elif a.cmd == "export-signals":
        cmd_export_signals([s.upper() for s in a.symbols], a.start, a.end)
    elif a.cmd == "raw":
        cmd_raw(a.symbol.upper())


if __name__ == "__main__":
    main()

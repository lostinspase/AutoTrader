#!/usr/bin/env python3
"""
Genesis + Exodus — FMP data layer.

Reads the API key from sibling state/fmp.env. All technical levels are COMPUTED
from FMP history — never fabricated. On network failure, functions return an
{"error": ...} dict (or for screener/movers, an empty list) so callers can gate
the affected name to WATCHLIST/NO TRADE rather than crash.

Honesty rule: FMP error on a candidate -> that name is WATCHLIST/NO TRADE only.

CLI:
  regime
  screener [marketCapMoreThan=... priceMoreThan=... volumeMoreThan=... exchange=... sector=... limit=...]
  movers
  indicators SYM
  earnings SYM
  earnings-multi SYM...
  news SYM...
  rs SYM
  correlation SYM...
  breadth
  rotation SYM...
  pricechange SYM...
  scores SYM
  float SYM
  insider SYM
  grades SYM
  sectors
"""

import json
import os
import sys
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
ENV_FILE = os.path.join(STATE, "fmp.env")
CACHE_DIR = os.path.join(STATE, "cache")

BASE = "https://financialmodelingprep.com/stable"
CACHE_TTL_SECONDS = 60 * 60 * 20  # ~daily cache; histories rarely change intraday


# ---- key + http --------------------------------------------------------------
def _key():
    """Read FMP_API_KEY. Missing/placeholder key is a hard, loud failure."""
    val = None
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FMP_API_KEY="):
                    val = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass
    if not val or val.startswith("<"):
        sys.stderr.write(
            "FATAL: no FMP_API_KEY in state/fmp.env (still a <PLACEHOLDER>?). "
            "Add your paid key before running.\n")
        raise SystemExit(3)
    return val


def _cache_path(name):
    # Hash long/structured keys so the filename stays well under the OS limit.
    # Keep a readable prefix (up to first ':') for eyeballing the cache dir.
    prefix = name.split(":", 1)[0][:40]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    safe_prefix = urllib.parse.quote(prefix, safe="")
    return os.path.join(CACHE_DIR, f"{safe_prefix}.{digest}.json")


def _cache_get(name):
    p = _cache_path(name)
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return None
    if (time.time() - st.st_mtime) > CACHE_TTL_SECONDS:
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def _cache_put(name, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(_cache_path(name), "w") as f:
            json.dump(obj, f)
    except OSError:
        pass


def _get(path, params=None, cache_key=None):
    """
    GET BASE/path?params&apikey=... Returns parsed JSON, or an error dict:
      {"_error": "..."} (network/parse) or {"_http_error": code} (4xx/5xx).
    Never raises on network failure (callers gate on the error shape).
    """
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    params = dict(params or {})
    params["apikey"] = _key()
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "genesis-exodus/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"_error": f"network: {e}"}
    except json.JSONDecodeError as e:
        return {"_error": f"bad json: {e}"}
    if cache_key:
        _cache_put(cache_key, data)
    return data


def _is_err(x):
    return isinstance(x, dict) and ("_error" in x or "_http_error" in x)


# ---- history helper ----------------------------------------------------------
def _history(symbol, days=400):
    """Daily closes oldest->newest as list of {date, close, high, low, volume}."""
    data = _get("historical-price-eod/full",
                {"symbol": symbol, "limit": days},
                cache_key=f"hist:{symbol}:{days}")
    if _is_err(data):
        return data
    rows = data if isinstance(data, list) else data.get("historical", [])
    if not rows:
        return {"_error": "no history"}
    # FMP returns newest-first; normalize to oldest-first.
    rows = sorted(rows, key=lambda r: r.get("date", ""))
    out = []
    for r in rows:
        try:
            out.append({
                "date": r.get("date"),
                "close": float(r.get("close")),
                "high": float(r.get("high")),
                "low": float(r.get("low")),
                "volume": float(r.get("volume") or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def _sma(closes, n):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _atr(hist, n):
    if len(hist) < n + 1:
        return None
    trs = []
    for i in range(1, len(hist)):
        h, l, pc = hist[i]["high"], hist[i]["low"], hist[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


# ---- regime ------------------------------------------------------------------
def _index_snapshot(sym):
    h = _history(sym, 260)
    if _is_err(h) or not isinstance(h, list) or len(h) < 50:
        return {"price": None, "sma50": None, "sma200": None}
    closes = [r["close"] for r in h]
    return {
        "price": round(closes[-1], 2),
        "sma50": round(_sma(closes, 50), 2) if _sma(closes, 50) else None,
        "sma200": round(_sma(closes, 200), 2) if _sma(closes, 200) else None,
    }


def _vix():
    data = _get("quote", {"symbol": "^VIX"}, cache_key="vix")
    if _is_err(data) or not data:
        return None
    try:
        return float((data[0] if isinstance(data, list) else data).get("price"))
    except (TypeError, ValueError, IndexError, AttributeError):
        return None


def regime():
    spy = _index_snapshot("SPY")
    qqq = _index_snapshot("QQQ")
    iwm = _index_snapshot("IWM")
    vix = _vix()

    def trend(snap):
        if snap["price"] is None or snap["sma50"] is None or snap["sma200"] is None:
            return None
        return (snap["price"] > snap["sma50"]) + (snap["price"] > snap["sma200"])

    scores = [trend(spy), trend(qqq), trend(iwm)]
    known = [s for s in scores if s is not None]
    if not known:
        computed = "cautious"  # data unreachable -> treat as cautious (safe-ish default)
    else:
        avg = sum(known) / len(known)  # 0..2
        if vix is not None and vix >= 35:
            computed = "crash"
        elif avg >= 1.7:
            computed = "normal"
        elif avg >= 1.0:
            computed = "cautious"
        elif avg >= 0.4:
            computed = "defensive"
        else:
            computed = "crash"

    return {
        "SPY": spy, "QQQ": qqq, "IWM": iwm, "vix": vix,
        "computed_class": computed,
    }


# ---- screener ----------------------------------------------------------------
_ETF_FUND_HINTS = ("ETF", "Fund", "Trust", "Index")


def screener(args):
    """Quality liquid US universe, no ETFs/funds. args like ['limit=120','priceMoreThan=5']."""
    params = {
        "marketCapMoreThan": 2_000_000_000,
        "priceMoreThan": 5,
        "volumeMoreThan": 500_000,
        "country": "US",
        "isEtf": "false",
        "isFund": "false",
        "isActivelyTrading": "true",
        "limit": 100,
    }
    for a in args or []:
        if "=" in a:
            k, v = a.split("=", 1)
            params[k] = v
    data = _get("company-screener", params,
                cache_key="screener:" + json.dumps(params, sort_keys=True))
    if _is_err(data) or not isinstance(data, list):
        return []
    out = []
    for r in data:
        name = (r.get("companyName") or "")
        if any(h in name for h in _ETF_FUND_HINTS):
            continue
        if r.get("isEtf") or r.get("isFund"):
            continue
        out.append({
            "symbol": r.get("symbol"),
            "companyName": name,
            "exchange": r.get("exchangeShortName") or r.get("exchange"),
            "sector": r.get("sector"),
            "price": r.get("price"),
            "marketCap": r.get("marketCap"),
            "volume": r.get("volume"),
        })
    return out


# ---- movers ------------------------------------------------------------------
def movers():
    out = {}
    for kind, path in (("gainers", "biggest-gainers"),
                       ("losers", "biggest-losers"),
                       ("actives", "most-actives")):
        data = _get(path, {}, cache_key=f"movers:{kind}")
        if _is_err(data) or not isinstance(data, list):
            out[kind] = []
            continue
        rows = []
        for r in data:
            try:
                price = float(r.get("price"))
            except (TypeError, ValueError):
                continue
            if price < 5:  # no penny stocks
                continue
            rows.append({
                "symbol": r.get("symbol"),
                "name": r.get("name") or r.get("companyName"),
                "price": price,
                "changesPercentage": r.get("changesPercentage"),
            })
        out[kind] = rows
    return out


# ---- indicators --------------------------------------------------------------
def indicators(symbol):
    h = _history(symbol, 400)
    if _is_err(h):
        return {"symbol": symbol, "error": h.get("_error") or h.get("_http_error")}
    if not isinstance(h, list) or len(h) < 30:
        return {"symbol": symbol, "error": "insufficient history"}

    closes = [r["close"] for r in h]
    price = closes[-1]
    sma50 = _sma(closes, 50)
    sma150 = _sma(closes, 150)
    sma200 = _sma(closes, 200)
    sma200_prev = _sma(closes[:-21], 200) if len(closes) >= 221 else None
    sma200_rising = (sma200 is not None and sma200_prev is not None
                     and sma200 > sma200_prev)

    # 52-week levels require a full year of bars, else they are meaningless.
    fiftytwo_complete = len(h) >= 252
    last252 = h[-252:] if fiftytwo_complete else h
    hi52 = max(r["high"] for r in last252) if fiftytwo_complete else None
    lo52 = min(r["low"] for r in last252) if fiftytwo_complete else None
    pct_from_hi = round((price - hi52) / hi52 * 100, 2) if fiftytwo_complete else None
    pct_from_lo = round((price - lo52) / lo52 * 100, 2) if fiftytwo_complete else None

    # breakout helpers
    def breakout(n):
        if len(h) < n + 1:
            return None
        prior_high = max(r["high"] for r in h[-(n + 1):-1])
        return price > prior_high
    breakout20 = breakout(20)
    breakout55 = breakout(55)

    atr20 = _atr(h, 20)
    atr14 = _atr(h, 14)

    ret63d = (round((price / closes[-64] - 1) * 100, 2)
              if len(closes) >= 64 else None)

    # relative strength vs SPY over ~63d
    spy_h = _history("SPY", 120)
    rs_vs_spy = None
    if isinstance(spy_h, list) and len(spy_h) >= 64 and len(closes) >= 64:
        spy_closes = [r["close"] for r in spy_h]
        sym_ret = price / closes[-64] - 1
        spy_ret = spy_closes[-1] / spy_closes[-64] - 1
        rs_vs_spy = round((sym_ret - spy_ret) * 100, 2)

    # avg dollar volume over 20d
    vols = [r["volume"] for r in h[-20:]]
    avg_dollar_vol20 = round(sum(vols) / len(vols) * price, 0) if vols else None

    # Minervini-style trend template
    tt = (
        price is not None and sma50 and sma150 and sma200
        and price > sma50 > sma150 > sma200
        and sma200_rising
        and fiftytwo_complete
        and pct_from_lo is not None and pct_from_lo >= 30
        and pct_from_hi is not None and pct_from_hi >= -25
    )

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "sma50": round(sma50, 2) if sma50 else None,
        "sma150": round(sma150, 2) if sma150 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "sma200_rising": sma200_rising,
        "hi52": round(hi52, 2) if hi52 else None,
        "lo52": round(lo52, 2) if lo52 else None,
        "pct_from_hi": pct_from_hi,
        "pct_from_lo": pct_from_lo,
        "breakout20": breakout20,
        "breakout55": breakout55,
        "atr20": round(atr20, 3) if atr20 else None,
        "atr14": round(atr14, 3) if atr14 else None,
        "ret63d": ret63d,
        "rs_vs_spy": rs_vs_spy,
        "genesis_trend_template_pass": bool(tt),
        "avgDollarVol20": avg_dollar_vol20,
        "fiftytwo_week_complete": fiftytwo_complete,
        "history_days": len(h),
    }


# ---- earnings ----------------------------------------------------------------
def earnings(symbol):
    # NOTE: FMP's 'earnings-calendar' IGNORES the symbol param (returns the whole
    # market calendar) — discovered live 2026-07-06 when six unrelated names all
    # "reported today". Use the per-symbol 'earnings' endpoint, and as defense in
    # depth drop any row whose symbol doesn't match; if none match, ERROR (which
    # gates the name to WATCHLIST) rather than fabricate a pass.
    data = _get("earnings", {"symbol": symbol, "limit": 8},
                cache_key=f"earnings2:{symbol}")
    if _is_err(data):
        return {"symbol": symbol, "error": data.get("_error") or data.get("_http_error")}
    rows = [r for r in (data if isinstance(data, list) else [])
            if (r.get("symbol") or "").upper() == symbol.upper()]
    if not rows:
        return {"symbol": symbol, "error": "no symbol-matched earnings rows"}
    today = time.strftime("%Y-%m-%d")
    upcoming = None
    for r in rows:
        d = r.get("date")
        if d and d >= today:
            if upcoming is None or d < upcoming:
                upcoming = d
    within_5d = False
    if upcoming:
        # crude calendar-day proxy for "~5 trading days"
        import datetime as _dt
        try:
            delta = (_dt.date.fromisoformat(upcoming) - _dt.date.fromisoformat(today)).days
            within_5d = 0 <= delta <= 7
        except ValueError:
            pass
    return {"symbol": symbol, "next_earnings": upcoming, "within_5_trading_days": within_5d}


def earnings_multi(symbols):
    return {s: earnings(s) for s in symbols}


# ---- advisory sensors --------------------------------------------------------
def news(symbols):
    data = _get("news/stock", {"symbols": ",".join(symbols), "limit": 20},
                cache_key="news:" + ",".join(symbols))
    if _is_err(data):
        return {"error": data.get("_error") or data.get("_http_error")}
    items = []
    for r in (data if isinstance(data, list) else []):
        items.append({"symbol": r.get("symbol"), "title": r.get("title"),
                      "publishedDate": r.get("publishedDate"), "site": r.get("site")})
    return {"count": len(items), "items": items[:15]}


def rs(symbol):
    """Blended relative strength: excess return vs SPY over 21/63/126d windows."""
    h = _history(symbol, 200)
    spy = _history("SPY", 200)
    if _is_err(h) or _is_err(spy):
        return {"symbol": symbol, "error": "history unreachable"}
    if not isinstance(h, list) or len(h) < 64:
        return {"symbol": symbol, "error": "insufficient history"}
    sc = [r["close"] for r in h]
    pc = [r["close"] for r in spy]
    excess = {}
    for w in (21, 63, 126):
        if len(sc) > w and len(pc) > w:
            excess[w] = (sc[-1] / sc[-1 - w] - 1) - (pc[-1] / pc[-1 - w] - 1)
    if not excess:
        return {"symbol": symbol, "error": "insufficient overlap"}
    blended = sum(excess.values()) / len(excess) * 100
    return {
        "symbol": symbol,
        "rs_excess_vs_spy": round(blended, 2),
        "windows_pct": {k: round(v * 100, 2) for k, v in excess.items()},
        "is_leader": blended > 0,
    }


def correlation(symbols):
    """Avg pairwise correlation of daily returns over a shared window."""
    if len(symbols) < 2:
        return {"error": "need >=2 symbols"}
    series = {}
    for s in symbols:
        h = _history(s, 90)
        if _is_err(h) or not isinstance(h, list) or len(h) < 40:
            return {"error": f"history unreachable for {s}"}
        closes = [r["close"] for r in h]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        series[s] = rets
    window = min(len(v) for v in series.values())
    series = {k: v[-window:] for k, v in series.items()}

    def corr(a, b):
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        va = sum((x - ma) ** 2 for x in a) ** 0.5
        vb = sum((x - mb) ** 2 for x in b) ** 0.5
        if va == 0 or vb == 0:
            return 0.0
        return cov / (va * vb)

    syms = list(series.keys())
    pairs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            pairs.append(corr(series[syms[i]], series[syms[j]]))
    avg = sum(pairs) / len(pairs) if pairs else 0.0
    return {
        "symbols": syms,
        "window_days": window,
        "avg_corr_to_others": round(avg, 3),
        "highly_correlated_cluster": avg >= 0.7,
    }


def breadth():
    """% of sector ETFs trading above their 50-DMA -> exposure hint."""
    sectors = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
    above = 0
    counted = 0
    for s in sectors:
        h = _history(s, 80)
        if _is_err(h) or not isinstance(h, list) or len(h) < 50:
            continue
        closes = [r["close"] for r in h]
        sma50 = _sma(closes, 50)
        if sma50 is None:
            continue
        counted += 1
        if closes[-1] > sma50:
            above += 1
    if counted == 0:
        return {"breadth_pct_50dma": None, "exposure_hint": None}
    pct = round(100.0 * above / counted, 1)
    if pct >= 70:
        hint = "risk-on"
    elif pct >= 40:
        hint = "neutral"
    else:
        hint = "risk-off"
    return {"breadth_pct_50dma": pct, "sectors_counted": counted, "exposure_hint": hint}


def rotation(symbols):
    """Leaderboard by blended RS + rotation-out flag (RS turning negative short-term)."""
    rows = []
    for s in symbols:
        r = rs(s)
        if r.get("error"):
            rows.append({"symbol": s, "error": r["error"]})
            continue
        short = r.get("windows_pct", {}).get(21)
        rows.append({
            "symbol": s,
            "rs_excess_vs_spy": r["rs_excess_vs_spy"],
            "rs_21d_pct": short,
            "rotation_candidate": (short is not None and short < 0),
        })
    ranked = sorted([r for r in rows if "rs_excess_vs_spy" in r],
                    key=lambda x: x["rs_excess_vs_spy"], reverse=True)
    return {"leaderboard": ranked,
            "rotation_candidates": [r["symbol"] for r in rows if r.get("rotation_candidate")],
            "errors": [r for r in rows if r.get("error")]}


def pricechange(symbols):
    data = _get("quote", {"symbol": ",".join(symbols)})
    if _is_err(data):
        return {"error": data.get("_error") or data.get("_http_error")}
    out = []
    for r in (data if isinstance(data, list) else [data]):
        out.append({"symbol": r.get("symbol"), "price": r.get("price"),
                    "changePercentage": r.get("changePercentage") or r.get("changesPercentage")})
    return {"quotes": out}


def _passthru(path, symbol, key):
    data = _get(path, {"symbol": symbol}, cache_key=f"{key}:{symbol}")
    if _is_err(data):
        return {"symbol": symbol, "error": data.get("_error") or data.get("_http_error")}
    return {"symbol": symbol, "data": data}


def scores(symbol):
    return _passthru("financial-scores", symbol, "scores")


def float_shares(symbol):
    return _passthru("shares-float", symbol, "float")


def insider(symbol):
    return _passthru("insider-trading/search", symbol, "insider")


def grades(symbol):
    return _passthru("grades", symbol, "grades")


def sectors():
    data = _get("sector-performance-snapshot", {}, cache_key="sectors")
    if _is_err(data):
        return {"error": data.get("_error") or data.get("_http_error")}
    return {"sectors": data}


# ---- CLI ---------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: fmp.py <command> [args]"}))
        sys.exit(2)
    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "regime":
        out = regime()
    elif cmd == "screener":
        out = screener(rest)
    elif cmd == "movers":
        out = movers()
    elif cmd == "indicators":
        out = indicators(rest[0])
    elif cmd == "earnings":
        out = earnings(rest[0])
    elif cmd == "earnings-multi":
        out = earnings_multi(rest)
    elif cmd == "news":
        out = news(rest)
    elif cmd == "rs":
        out = rs(rest[0])
    elif cmd == "correlation":
        out = correlation(rest)
    elif cmd == "breadth":
        out = breadth()
    elif cmd == "rotation":
        out = rotation(rest)
    elif cmd == "pricechange":
        out = pricechange(rest)
    elif cmd == "scores":
        out = scores(rest[0])
    elif cmd == "float":
        out = float_shares(rest[0])
    elif cmd == "insider":
        out = insider(rest[0])
    elif cmd == "grades":
        out = grades(rest[0])
    elif cmd == "sectors":
        out = sectors()
    else:
        out = {"error": f"unknown command: {cmd}"}
        print(json.dumps(out))
        sys.exit(2)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

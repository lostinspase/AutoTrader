#!/usr/bin/env python3
"""
Genesis + Exodus — live dashboard server.

Serves http://127.0.0.1:8090 with:
  /       the dashboard page (auto-refreshes via JS every 45s, shows data age)
  /data   fresh JSON snapshot: broker balances/positions/orders + safety core +
          token status + journal/ledger tails. Server-side cache: 20s (protects
          Schwab rate limits when multiple tabs are open).

Honesty rules carried over from report.py:
  - every number comes from the broker or the append-only journal
  - if the broker is unreachable the page shows a loud STALE banner instead of
    silently displaying old numbers
Run:  python3 dashboard_server.py          (foreground)
A LaunchAgent (com.genesis.dashboard) keeps it running across reboots.
"""

import json
import os
import subprocess
import sys
import threading
import time
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
PORT = 8090
BIND = os.environ.get("AUTOTRADER_BIND", "127.0.0.1")
CACHE_TTL = 20  # seconds
NTFY_TOPIC = "autotrader-jp-303f1edb"  # scheduler-stall push alerts (ntfy.sh; subscribe in the ntfy app)

sys.path.insert(0, HERE)
import fmp  # noqa: E402  (profiles/news; daily-cached where marked)

_cache = {"ts": 0.0, "data": None}
_lock = threading.Lock()
_regen_running = threading.Lock()
_stale_notified = False


def sh(args, timeout=45):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       timeout=timeout, cwd=HERE)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:200]}


import re
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_SCANID_RE = re.compile(r"(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})-?ET", re.IGNORECASE)


def parse_entry_dt(entry):
    """Best-effort AWARE datetime for heterogeneous journal rows.
    Handles: ISO with offset, ISO with 'Z', naive ISO (assumed local — legacy),
    and scan_ids like '2026-07-09-1554-ET' (parsed as America/New_York)."""
    for k in ("ts", "timestamp", "ts_et"):
        v = entry.get(k)
        if not v:
            continue
        s = str(v).replace("Z", "+00:00")
        try:
            d = dt.datetime.fromisoformat(s)
        except (ValueError, TypeError):
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        return d
    m = _SCANID_RE.search(str(entry.get("scan_id", "")))
    if m:
        try:
            return dt.datetime.fromisoformat(m.group(1)).replace(
                hour=int(m.group(2)), minute=int(m.group(3)), tzinfo=_ET)
        except ValueError:
            pass
    return None


def friendly_ts(entry):
    d = parse_entry_dt(entry)
    if d is None:
        return str(entry.get("scan_id", "—"))
    local = d.astimezone()
    return local.strftime("%a %b %d · %I:%M %p %Z").replace(" 0", " ")


def read_jsonl(path, last_n):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return rows[-last_n:]


def snapshot():
    """Fresh full-state snapshot (called at most every CACHE_TTL seconds)."""
    token = sh(["schwab.py", "token-status"])
    status = sh(["ops.py", "status"])
    perf = sh(["ops.py", "perf"])
    pos = sh(["schwab.py", "positions"])
    orders = sh(["schwab.py", "orders"])
    broker_ok = "error" not in pos

    balances = pos.get("balances", {}) if broker_ok else {}
    positions = []
    for p in (pos.get("positions", []) if broker_ok else []):
        qty = p.get("longQuantity") or p.get("quantity") or 0
        avg = p.get("averagePrice") or 0
        mv = p.get("marketValue") or 0
        last = round(mv / qty, 4) if qty else None
        positions.append({
            "symbol": p.get("instrument", {}).get("symbol", "?"),
            "qty": qty, "avg": round(avg, 2), "last": last,
            "pl_pct": round((last / avg - 1) * 100, 2) if (last and avg) else None,
            "value": round(mv, 2),
        })

    open_orders = []
    for o in (orders if isinstance(orders, list) else []):
        legs = o.get("orderLegCollection", [{}])
        open_orders.append({
            "id": o.get("orderId"),
            "symbol": legs[0].get("instrument", {}).get("symbol") if legs else "?",
            "side": legs[0].get("instruction") if legs else "?",
            "qty": o.get("quantity"),
            "type": o.get("orderType"),
            "price": o.get("price") or o.get("stopPrice"),
            "status": o.get("status"),
        })

    baseline = None
    try:
        with open(os.path.join(STATE, "nav_baseline.json")) as f:
            baseline = json.load(f).get(dt.date.today().isoformat())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    nav = balances.get("liquidationValue")
    day_pct = (round((nav - baseline) / baseline * 100, 2)
               if (nav is not None and baseline) else None)

    journal = read_jsonl(os.path.join(STATE, "journal.jsonl"), 12)
    ledger = read_jsonl(os.path.join(STATE, "ledger.jsonl"), 10)

    # candidates snapshot (advisory preview) — regenerate in the background when
    # older than 30 min; serve whatever exists now (never block a page load on FMP)
    cand_path = os.path.join(STATE, "candidates.json")
    candidates = {}
    try:
        with open(cand_path) as f:
            candidates = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    try:
        age = time.time() - os.path.getmtime(cand_path) if os.path.exists(cand_path) else 1e9
        if age > 1800 and not _regen_running.locked():
            def _regen():
                with _regen_running:
                    subprocess.run([sys.executable, os.path.join(HERE, "candidates.py")],
                                   capture_output=True, timeout=600)
            threading.Thread(target=_regen, daemon=True).start()
    except OSError:
        pass

    # --- missed-run watchdog (independent of the app scheduler: this server runs
    # under launchd). During ET market hours the quick-check should journal every
    # 15 min; >25 min of silence = the scheduler is stalled. Alerts via macOS
    # notification once per stale episode.
    sched_health = {"checked": False}
    try:
        now_et = dt.datetime.now(_ET)
        market_hours = (now_et.weekday() < 5
                        and (now_et.hour, now_et.minute) >= (9, 45)
                        and now_et.hour < 16)
        newest = None
        for j in reversed(journal):
            newest = parse_entry_dt(j)
            if newest:
                break
        age_min = ((dt.datetime.now(dt.timezone.utc) - newest.astimezone(dt.timezone.utc))
                   .total_seconds() / 60) if newest else None
        stale = bool(market_hours and (age_min is None or age_min > 25))
        sched_health = {"checked": True, "market_hours": market_hours,
                        "last_run_age_min": round(age_min) if age_min is not None else None,
                        "stale": stale}
        global _stale_notified
        # latch FIRST — a notification failure must never cause a re-notify storm.
        # _stale_notified holds the epoch of the last alert; re-notify at most every
        # 2h while an episode persists; reset when the scheduler recovers.
        now_ts = time.time()
        already = isinstance(_stale_notified, float) and (now_ts - _stale_notified) < 7200
        if stale and not already:
            _stale_notified = now_ts
            try:
                subprocess.run(["curl", "-s", "-m", "10",
                                "-H", "Title: AutoTrader scheduler stalled",
                                "-H", "Priority: high",
                                "-d", f"No scheduled run journaled in {round(age_min or 0)} min during market hours.",
                                f"https://ntfy.sh/{NTFY_TOPIC}"], capture_output=True, timeout=15)
            except Exception:
                pass
            try:
                _osa = subprocess.run(["osascript", "-e",
                            'display notification "No scheduled run journaled in '
                            + str(round(age_min or 0)) + ' min during market hours — check Routines" '
                            'with title "⚠️ Genesis scheduler stalled"'],
                           capture_output=True, timeout=10)
            except Exception:
                pass  # osascript absent on Linux — ntfy already sent, latch already set
        elif not stale:
            _stale_notified = False
    except Exception:
        pass

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "scheduler_health": sched_health,
        "broker_ok": broker_ok,
        "broker_error": None if broker_ok else str(pos.get("error"))[:200],
        "armed": (not status.get("halted")) and bool(status.get("live")),
        "halted": status.get("halted"), "halt_reason": status.get("halt_reason"),
        "token_ok": bool(token.get("authenticated")) and not token.get("reauth_required"),
        "token_days": token.get("refresh_days_remaining"),
        "reauth_by": token.get("reauth_by"),
        "nav": nav, "cash": balances.get("cashAvailableForTrading"),
        "baseline": baseline, "day_pct": day_pct,
        "positions": positions, "open_orders": open_orders,
        "trades": perf.get("trades", 0), "win_rate": perf.get("win_rate_pct"),
        "wins": perf.get("wins", 0), "losses": perf.get("losses", 0),
        "realized_pl": perf.get("total_realized_pl", 0),
        "journal": [
            {"t": friendly_ts(j),
             "type": j.get("run_type", "scan"),
             "decision": str(j.get("decision", j.get("summary", "—")))[:140]}
            for j in sorted(journal,
                            key=lambda x: parse_entry_dt(x)
                            or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
                            reverse=True)],
        "ledger": [
            {"t": (t.get("closed_at") or "")[:10], "symbol": t.get("symbol"),
             "outcome": t.get("outcome"), "pl": t.get("realized_pl"),
             "setup": t.get("setup", "")}
            for t in reversed(ledger)],
        "candidates_as_of": candidates.get("as_of"),
        "candidates_cap": candidates.get("cap_per_name"),
        "candidates": candidates.get("candidates", []),
        "symbol_info": _symbol_info(
            {p["symbol"] for p in positions}
            | {c.get("symbol") for c in candidates.get("candidates", []) if c.get("symbol")}),
        "news": _news([p["symbol"] for p in positions],
                      [c["symbol"] for c in candidates.get("candidates", [])
                       if c.get("eligible")][:3]),
    }


def _symbol_info(symbols):
    """Company name/sector/industry/site per symbol (FMP profile, daily-cached)."""
    out = {}
    for s in sorted(x for x in symbols if x):
        p = fmp._get("profile", {"symbol": s}, cache_key=f"profile:{s}")
        if fmp._is_err(p):
            continue
        r = p[0] if isinstance(p, list) and p else (p if isinstance(p, dict) else {})
        out[s] = {"name": r.get("companyName"), "sector": r.get("sector"),
                  "industry": r.get("industry"), "website": r.get("website")}
    return out


def _news(held, top_candidates):
    """Recent headlines for held names (always) + top eligible candidates."""
    syms = list(dict.fromkeys(held + top_candidates))
    if not syms:
        return []
    n = fmp._get("news/stock", {"symbols": ",".join(syms), "limit": 15})
    if fmp._is_err(n) or not isinstance(n, list):
        return []
    return [{"symbol": a.get("symbol"), "title": a.get("title"),
             "site": a.get("site"), "date": str(a.get("publishedDate"))[:10],
             "url": a.get("url"), "held": a.get("symbol") in held}
            for a in n[:12]]


def _refresher():
    """Background loop: recompute the snapshot continuously so HTTP requests are
    ALWAYS served instantly from cache — the browser never waits on broker calls.
    30s cadence during market-ish hours (weekdays 6:00–13:30 PT), 5min otherwise."""
    while True:
        try:
            data = snapshot()
            data["snapshot_age_note"] = "served from background refresher"
            with _lock:
                _cache["data"] = data
                _cache["ts"] = time.time()
        except Exception as e:
            with _lock:
                if _cache["data"] is None:
                    _cache["data"] = {"warming": False, "broker_ok": False,
                                      "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                                      "broker_error": f"snapshot failed: {e}"}
                else:  # keep last good data; mark it stale
                    _cache["data"]["broker_ok"] = False
                    _cache["data"]["broker_error"] = f"refresh failing: {e}"
        now_et = dt.datetime.now(_ET)  # market hours are Eastern, regardless of machine TZ
        market_ish = now_et.weekday() < 5 and 9 <= now_et.hour < 17
        time.sleep(30 if market_ish else 300)


def get_data():
    """Instant, non-blocking: return latest snapshot, or a 'warming' stub on cold start."""
    with _lock:
        if _cache["data"] is None:
            return {"warming": True,
                    "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "broker_ok": False, "positions": [], "open_orders": [],
                    "journal": [], "ledger": [], "candidates": [], "news": [],
                    "symbol_info": {}}
        return _cache["data"]


PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Genesis + Exodus — Live</title><style>
body{font-family:-apple-system,Helvetica,sans-serif;margin:24px;background:#fafafa;color:#222;max-width:1100px}
h1{font-size:20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;margin-bottom:8px}
td,th{border:1px solid #e0e0e0;padding:6px 10px;text-align:left}
th{background:#f0f0f0} h2{font-size:14px;margin:22px 0 6px;color:#444}
.chip{padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600}
.ok{background:#e8f5e9;color:#2e7d32}.bad{background:#ffebee;color:#c62828}.warn{background:#fff8e1;color:#b26a00}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px 16px;min-width:110px}
.card .v{font-size:19px;font-weight:700}.card .l{font-size:11px;color:#777}
#banner{display:none;background:#ffebee;color:#c62828;padding:10px;border-radius:6px;margin:10px 0;font-weight:600}
#age{font-size:12px;color:#666;font-weight:400}
.pos{color:#2e7d32}.neg{color:#c62828}
footer{margin-top:24px;font-size:11px;color:#999}
</style></head><body>
<h1>Genesis + Exodus <span id="armed" class="chip">…</span>
 <span id="token" class="chip">…</span> <span id="age">connecting…</span></h1>
<div id="banner"></div>
<div class="cards">
 <div class="card"><div class="v" id="nav">—</div><div class="l">portfolio value</div></div>
 <div class="card"><div class="v" id="cash">—</div><div class="l">cash available</div></div>
 <div class="card"><div class="v" id="day">—</div><div class="l" id="dayl">today vs baseline</div></div>
 <div class="card"><div class="v" id="trades">—</div><div class="l">closed trades</div></div>
 <div class="card"><div class="v" id="record">—</div><div class="l">wins – losses</div></div>
 <div class="card"><div class="v" id="win">—</div><div class="l">win rate</div></div>
 <div class="card"><div class="v" id="pl">—</div><div class="l">realized P/L</div></div>
</div>
<h2>Open positions</h2>
<table id="positions"><tr><th>symbol</th><th>qty</th><th>avg cost</th><th>last</th><th>P/L %</th><th>value</th></tr></table>
<h2>Open orders (resting at broker)</h2>
<table id="orders"><tr><th>symbol</th><th>side</th><th>qty</th><th>type</th><th>price/stop</th><th>status</th></tr></table>
<h2>Buy candidates — next-scan preview <span id="cand_meta" style="font-weight:400;font-size:11px;color:#888"></span></h2>
<div style="font-size:11px;color:#888;margin-bottom:4px">Advisory: same rules as the scan (trend template + RS + earnings guard + sizing fit),
but the scan re-scores live and applies hard-scope judgment (e.g. biotech-binary DQs). The top eligible name is the likely pick — not a promise.</div>
<table id="candidates"><tr><th>symbol</th><th>price</th><th>RS vs SPY</th><th>63d %</th><th>from hi</th><th>ATR%</th><th>earnings</th><th>shares@cap</th><th>eligible</th></tr></table>
<h2>Latest news — holdings & top candidates</h2>
<table id="news"><tr><th>date</th><th>symbol</th><th>headline</th><th>source</th></tr></table>
<h2>Recent closed trades</h2>
<table id="ledger"><tr><th>date</th><th>symbol</th><th>outcome</th><th>P/L</th><th>setup</th></tr></table>
<h2>Recent scans (journal)</h2>
<table id="journal"><tr><th>time</th><th>type</th><th>decision</th></tr></table>
<footer>Live server on 127.0.0.1:8090 — every number fetched fresh from the broker/journal (20s server cache,
45s page refresh). Kill switch: ops.py halt "reason".</footer>
<script>
const REFRESH_S = 45;
let lastFetch = null, countdown = REFRESH_S;
function fmt$(x){ return x==null ? '—' : '$'+Number(x).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
function row(cells, cls){ return '<tr>'+cells.map((c,i)=>`<td class="${cls&&cls[i]||''}">${c==null?'—':c}</td>`).join('')+'</tr>'; }
let SYMINFO = {};
function symcell(sym){
  const i = SYMINFO[sym] || {};
  const tip = i.name ? `${i.name} — ${i.sector||''}${i.industry?' · '+i.industry:''}` : sym;
  return `<a href="https://finance.yahoo.com/quote/${sym}" target="_blank" title="${tip}" style="font-weight:600">${sym}</a>`
       + ` <a href="https://www.tradingview.com/chart/?symbol=${sym}" target="_blank" title="chart" style="font-size:10px;text-decoration:none">📈</a>`
       + (i.name ? `<div style="font-size:10px;color:#888">${i.name}${i.sector?' · '+i.sector:''}</div>` : '');
}
async function refresh(){
  try{
    const r = await fetch('/data', {cache:'no-store'});
    const d = await r.json();
    lastFetch = new Date();
    SYMINFO = d.symbol_info || {};
    document.getElementById('armed').textContent = d.armed ? 'ARMED · LIVE' : ('HALTED'+(d.halt_reason?' — '+d.halt_reason:''));
    document.getElementById('armed').className = 'chip '+(d.armed?'ok':'bad');
    document.getElementById('token').textContent = 'token '+(d.token_ok ? (d.token_days+'d') : 'EXPIRED');
    document.getElementById('token').className = 'chip '+(d.token_ok ? (d.token_days>2.5?'ok':'warn') : 'bad');
    const b = document.getElementById('banner');
    if(d.warming){ b.style.display='block'; b.style.background='#fff8e1'; b.style.color='#b26a00';
      b.textContent='⏳ Server just started — first data snapshot arrives in ~15–30 seconds (auto-refreshes, no need to reload).'; }
    else if(!d.broker_ok){ b.style.display='block'; b.style.background='#ffebee'; b.style.color='#c62828';
      b.textContent='⚠️ BROKER UNREACHABLE — numbers may be stale: '+(d.broker_error||''); }
    else if(d.scheduler_health && d.scheduler_health.stale){ b.style.display='block'; b.style.background='#fff3e0'; b.style.color='#b26a00';
      b.textContent='⚠️ SCHEDULER STALLED — no run journaled in '+d.scheduler_health.last_run_age_min+' min during market hours. Positions are protected by resting stops, but profit-taking/ratchets are paused. Check Routines.'; }
    else b.style.display='none';
    if(d.warming){ countdown = 10; return; }  // poll again soon while warming
    document.getElementById('nav').textContent = fmt$(d.nav);
    document.getElementById('cash').textContent = fmt$(d.cash);
    document.getElementById('day').textContent = d.day_pct==null?'—':(d.day_pct>=0?'+':'')+d.day_pct+'%';
    document.getElementById('day').className = 'v '+((d.day_pct||0)>=0?'pos':'neg');
    document.getElementById('dayl').textContent = 'today vs baseline '+fmt$(d.baseline);
    document.getElementById('trades').textContent = d.trades;
    const w = d.wins||0, l = d.losses||0;
    const rec = document.getElementById('record');
    rec.textContent = `${w}W – ${l}L`;
    rec.className = 'v ' + (w>l ? 'pos' : (l>w ? 'neg' : ''));
    document.getElementById('win').textContent = d.win_rate==null?'—':d.win_rate+'%';
    document.getElementById('pl').textContent = fmt$(d.realized_pl);
    const P = document.getElementById('positions');
    P.innerHTML = '<tr><th>symbol</th><th>qty</th><th>avg cost</th><th>last</th><th>P/L %</th><th>value</th></tr>' +
      (d.positions.length ? d.positions.map(p=>row([symcell(p.symbol),p.qty,fmt$(p.avg),fmt$(p.last),(p.pl_pct>=0?'+':'')+p.pl_pct+'%',fmt$(p.value)],[,,,, p.pl_pct>=0?'pos':'neg'])).join('') : '<tr><td colspan=6 style="color:#888">no open positions</td></tr>');
    const O = document.getElementById('orders');
    O.innerHTML = '<tr><th>symbol</th><th>side</th><th>qty</th><th>type</th><th>price/stop</th><th>status</th></tr>' +
      (d.open_orders.length ? d.open_orders.map(o=>row([o.symbol,o.side,o.qty,o.type,o.price,o.status])).join('') : '<tr><td colspan=6 style="color:#888">no open orders</td></tr>');
    const C = document.getElementById('candidates');
    document.getElementById('cand_meta').textContent =
      d.candidates_as_of ? `as of ${d.candidates_as_of.replace('T',' ')} · cap ${fmt$(d.candidates_cap)}/name (auto-refreshes ~30min)` : '';
    C.innerHTML = '<tr><th>symbol</th><th>price</th><th>RS vs SPY</th><th>63d %</th><th>from hi</th><th>ATR%</th><th>earnings</th><th>shares@cap</th><th>eligible</th></tr>' +
      (d.candidates && d.candidates.length ? d.candidates.map(c=>row(
        [symcell(c.symbol), fmt$(c.price), c.rs_vs_spy, c.ret63d_pct+'%', c.pct_from_hi+'%', c.atr_pct+'%',
         c.next_earnings + (c.earnings_blocked?' ⛔':''), c.shares_at_cap, c.eligible?'✓':'✗'],
        [,,,,,,,, c.eligible?'pos':'neg'])).join('')
       : '<tr><td colspan=9 style="color:#888">no snapshot yet — generating…</td></tr>');
    const N = document.getElementById('news');
    N.innerHTML = '<tr><th>date</th><th>symbol</th><th>headline</th><th>source</th></tr>' +
      (d.news && d.news.length ? d.news.map(a=>row(
        [a.date, symcell(a.symbol)+(a.held?' <span class="chip ok" style="font-size:9px">HELD</span>':''),
         `<a href="${a.url}" target="_blank">${a.title}</a>`, a.site])).join('')
       : '<tr><td colspan=4 style="color:#888">no recent headlines</td></tr>');
    const L = document.getElementById('ledger');
    L.innerHTML = '<tr><th>date</th><th>symbol</th><th>outcome</th><th>P/L</th><th>setup</th></tr>' +
      (d.ledger.length ? d.ledger.map(t=>row([t.t,t.symbol,t.outcome,fmt$(t.pl),t.setup],[,,, (t.pl||0)>=0?'pos':'neg'])).join('') : '<tr><td colspan=5 style="color:#888">no closed trades yet</td></tr>');
    const J = document.getElementById('journal');
    J.innerHTML = '<tr><th>time</th><th>type</th><th>decision</th></tr>' +
      (d.journal.length ? d.journal.map(j=>row([j.t,j.type,j.decision])).join('') : '<tr><td colspan=3 style="color:#888">no journal entries yet</td></tr>');
  }catch(e){
    const b = document.getElementById('banner');
    b.style.display='block'; b.textContent='⚠️ DASHBOARD SERVER UNREACHABLE — is dashboard_server.py running? ('+e+')';
  }
  countdown = REFRESH_S;
}
setInterval(()=>{
  countdown--;
  const age = lastFetch ? Math.round((new Date()-lastFetch)/1000) : null;
  document.getElementById('age').textContent =
    (age==null ? 'no data yet' : `updated ${age}s ago`) + ` · next refresh in ${Math.max(countdown,0)}s`;
  if(countdown<=0) refresh();
}, 1000);
refresh();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/data"):
            body = json.dumps(get_data()).encode()
            ctype = "application/json"
        elif self.path == "/" or self.path.startswith("/index"):
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    threading.Thread(target=_refresher, daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"Genesis dashboard: http://{BIND}:{PORT} (background refresher on)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

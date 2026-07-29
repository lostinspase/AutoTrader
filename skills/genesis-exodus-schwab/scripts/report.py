#!/usr/bin/env python3
"""
Genesis + Exodus — dashboard generator.

Reads live Schwab balances/positions/orders + local state (journal, ledger, control,
NAV baseline, token status) and writes a single self-contained HTML dashboard to
state/dashboard.html, plus a compact terminal summary to stdout.

Usage:
  python3 report.py            # generate + print summary
  python3 report.py --open     # generate + open in browser (macOS)

Honest by construction: every number on the page comes from the broker or the
append-only journal — nothing is estimated. If Schwab is unreachable (stale token,
network), the page says so instead of showing stale numbers as fresh.
"""

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
OUT = os.path.join(STATE, "dashboard.html")


def sh(args):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout or r.stderr)[:200]}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z")

    token = sh(["schwab.py", "token-status"])
    status = sh(["ops.py", "status"])
    perf = sh(["ops.py", "perf"])
    pos = sh(["schwab.py", "positions"])
    broker_ok = "error" not in pos

    balances = pos.get("balances", {}) if broker_ok else {}
    positions = pos.get("positions", []) if broker_ok else []
    nav = balances.get("liquidationValue")
    cash = balances.get("cashAvailableForTrading")

    baseline = None
    try:
        with open(os.path.join(STATE, "nav_baseline.json")) as f:
            baseline = json.load(f).get(dt.date.today().isoformat())
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    dd = (round((nav - baseline) / baseline * 100, 2)
          if (nav is not None and baseline) else None)

    journal = read_jsonl(os.path.join(STATE, "journal.jsonl"), 15)
    ledger = read_jsonl(os.path.join(STATE, "ledger.jsonl"), 10)

    # ---- terminal summary ----
    armed = (not status.get("halted")) and status.get("live")
    print(f"ARMED: {armed}   halted: {status.get('halted')} ({status.get('halt_reason') or '—'})")
    print(f"token: {'OK' if token.get('authenticated') else 'EXPIRED'} "
          f"({token.get('refresh_days_remaining')}d left, reauth by {token.get('reauth_by')})")
    if broker_ok:
        print(f"NAV: ${nav}   cash: ${cash}   baseline: ${baseline}   day: {dd}%")
        print(f"positions: {len(positions)}   closed trades: {perf.get('trades', 0)}")
    else:
        print(f"BROKER UNREACHABLE: {pos.get('error')}")

    # ---- HTML ----
    def esc(x):
        return html.escape(str(x))

    pos_rows = ""
    for p in positions:
        inst = p.get("instrument", {})
        sym = inst.get("symbol", "?")
        qty = p.get("longQuantity") or p.get("quantity") or 0
        avg = p.get("averagePrice") or 0
        mv = p.get("marketValue") or 0
        last = round(mv / qty, 2) if qty else None
        plpc = round((last / avg - 1) * 100, 2) if (last and avg) else None
        color = "#2e7d32" if (plpc or 0) >= 0 else "#c62828"
        pos_rows += (f"<tr><td>{esc(sym)}</td><td>{esc(qty)}</td><td>${esc(round(avg,2))}</td>"
                     f"<td>${esc(last)}</td><td style='color:{color}'>{esc(plpc)}%</td>"
                     f"<td>${esc(round(mv,2))}</td></tr>")
    if not pos_rows:
        pos_rows = "<tr><td colspan=6 style='color:#888'>no open positions</td></tr>"

    led_rows = ""
    for t in reversed(ledger):
        pl = t.get("realized_pl", 0)
        color = "#2e7d32" if (pl or 0) >= 0 else "#c62828"
        led_rows += (f"<tr><td>{esc(t.get('closed_at','')[:10])}</td><td>{esc(t.get('symbol'))}</td>"
                     f"<td>{esc(t.get('outcome'))}</td><td style='color:{color}'>${esc(pl)}</td>"
                     f"<td>{esc(t.get('setup',''))}</td></tr>")
    if not led_rows:
        led_rows = "<tr><td colspan=5 style='color:#888'>no closed trades yet</td></tr>"

    jr_rows = ""
    for j in reversed(journal):
        jr_rows += (f"<tr><td>{esc(j.get('timestamp', j.get('scan_id',''))[:16])}</td>"
                    f"<td>{esc(j.get('run_type','scan'))}</td>"
                    f"<td>{esc(j.get('decision', j.get('summary','—')))[:120]}</td></tr>")
    if not jr_rows:
        jr_rows = "<tr><td colspan=3 style='color:#888'>no journal entries yet</td></tr>"

    armed_chip = ("<span class='chip ok'>ARMED · LIVE</span>" if armed else
                  f"<span class='chip halt'>HALTED — {esc(status.get('halt_reason') or '')}</span>")
    token_days = token.get("refresh_days_remaining")
    token_cls = "ok" if (token.get("authenticated") and (token_days or 0) > 2.5) else "warn"
    broker_chip = ("" if broker_ok else
                   f"<div class='banner'>⚠️ BROKER UNREACHABLE — numbers below may be stale: {esc(pos.get('error'))}</div>")

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>Genesis + Exodus — Dashboard</title><style>
body{{font-family:-apple-system,Helvetica,sans-serif;margin:24px;background:#fafafa;color:#222}}
h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px;color:#444}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
td,th{{border:1px solid #e0e0e0;padding:6px 10px;text-align:left}}
th{{background:#f0f0f0}}
.chip{{padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600}}
.chip.ok{{background:#e8f5e9;color:#2e7d32}} .chip.halt{{background:#ffebee;color:#c62828}}
.chip.warn{{background:#fff8e1;color:#b26a00}}
.cards{{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0}}
.card{{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 18px;min-width:120px}}
.card .v{{font-size:20px;font-weight:700}} .card .l{{font-size:11px;color:#777}}
.banner{{background:#ffebee;color:#c62828;padding:10px;border-radius:6px;margin:10px 0;font-weight:600}}
footer{{margin-top:26px;font-size:11px;color:#999}}
</style></head><body>
<h1>Genesis + Exodus — Schwab &nbsp;{armed_chip}
 &nbsp;<span class='chip {token_cls}'>token: {esc(token_days)}d left</span></h1>
<div style='font-size:12px;color:#777'>generated {esc(now)} · auto-refreshes every 5 min (regenerate with report.py)</div>
{broker_chip}
<div class="cards">
<div class="card"><div class="v">${esc(nav)}</div><div class="l">portfolio value</div></div>
<div class="card"><div class="v">${esc(cash)}</div><div class="l">cash available</div></div>
<div class="card"><div class="v">{esc(dd)}%</div><div class="l">today vs baseline (${esc(baseline)})</div></div>
<div class="card"><div class="v">{esc(perf.get('trades',0))}</div><div class="l">closed trades</div></div>
<div class="card"><div class="v">{esc(perf.get('win_rate_pct','—'))}%</div><div class="l">win rate</div></div>
<div class="card"><div class="v">${esc(perf.get('total_realized_pl','0'))}</div><div class="l">realized P/L</div></div>
</div>
<h2>Open positions</h2>
<table><tr><th>symbol</th><th>qty</th><th>avg cost</th><th>last</th><th>P/L %</th><th>value</th></tr>{pos_rows}</table>
<h2>Recent closed trades (ledger)</h2>
<table><tr><th>date</th><th>symbol</th><th>outcome</th><th>realized P/L</th><th>setup</th></tr>{led_rows}</table>
<h2>Recent scans (journal, last 15)</h2>
<table><tr><th>time</th><th>type</th><th>decision</th></tr>{jr_rows}</table>
<footer>Every number sourced from the broker or the append-only journal. Full SCAN REPORTs live in the
Scheduled sidebar (genesis-schwab-scan run history). Kill switch: ops.py halt "reason".</footer>
</body></html>"""

    with open(OUT, "w") as f:
        f.write(page)
    print(f"\ndashboard written: {OUT}")
    if args.open and sys.platform == "darwin":
        subprocess.Popen(["open", OUT])


if __name__ == "__main__":
    main()

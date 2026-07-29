# Strategy Monitor

Meta layer that tracks every deployed trading strategy in one browser dashboard.
Read-only: it parses each strategy's on-disk state and never talks to a broker,
so it can't interfere with live trading.

## Run

A LaunchAgent (`~/Library/LaunchAgents/com.strategy-monitor.plist`) keeps the
server running across crashes and reboots — http://127.0.0.1:8899. Logs go to
`/tmp/strategy_monitor.log` / `.err`.

```bash
launchctl kickstart -k gui/$UID/com.strategy-monitor   # restart (e.g. after code changes)
launchctl bootout gui/$UID/com.strategy-monitor        # stop for good
python3 strategy-monitor/server.py                     # or run by hand in the foreground
```

## Layout

- `config/strategies.json` — the registry. One entry per deployed strategy:
  adapter name, path to its state dir, known deposits, and the campaign
  baseline (date + NAV used for the headline P/L%).
- `monitor.py` — adapters that normalize each strategy's state files
  (journal.jsonl, nav_baseline.json, buys_today.json, scorecard.json,
  control.json) into one common schema. `python3 monitor.py` dumps the
  snapshot as JSON.
- `server.py` — stdlib HTTP server: `/` dashboard, `/api/summary` JSON.
- `static/index.html` — single-file dashboard (vanilla JS, no dependencies).

## Strategy Library tab

Inventories every strategy section from Kakushadze & Serur, *151 Trading
Strategies* (SSRN 3247865), ranked descending by fit to the current market
regime. `gen_library.py` holds the inventory and the scores — edit the scores
and re-run it (`python3 gen_library.py`) when the regime changes, then restart
the server. Each name deep-links into the locally served copy of the paper
(`static/paper.pdf`, served at `/paper.pdf#page=N`).

## Adding a strategy

Add an entry to `config/strategies.json`. If it keeps state in the same
journal/nav format as the Genesis+Exodus skills, reuse the
`genesis_exodus_skill` adapter; otherwise add an adapter function to
`monitor.py` and register it in `ADAPTERS`.

## Metrics shown

- **Campaign P/L** — NAV vs the configured baseline (first fully-funded flat
  day), the honest measure of the current trading campaign.
- **Net vs deposits** — NAV minus lifetime deposits (includes pre-campaign
  history).
- **Unrealized P/L** — sum over open positions from the latest journal snapshot.
- **Realized P/L** — from the skill's `ledger.jsonl` (the authoritative
  closed-trade record written by `ops.py ledger-add`), enriched with entry
  price/date from `buys_today.json` to show hold time. Win rate, avg win/loss,
  stops hit, and per-setup (genesis/exodus/turtle) attribution appear once
  trades close. A position that leaves the account with no ledger row is
  flagged "unrecorded exit" rather than given an invented P/L.
- Deposit-aware equity curve, open positions with stops, decision mix,
  scheduler reliability, heartbeat with stale warning (>2h without journal
  activity).

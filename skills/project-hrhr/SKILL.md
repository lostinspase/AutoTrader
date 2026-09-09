---
name: project-hrhr
description: >-
  Project HRHR — human-directed speculative basket of individual stocks on a dedicated
  Schwab account (strategy #5). UNLIKE every other strategy, this one has NO autonomous
  buy/sell engine: buys and sells are decided in discussion with the user and placed
  in-session on an explicit go. The cron only REVIEWS (mark to market, drawdown /
  concentration / doubling alerts, stage-2 reminder). No automatic stops by design.
---

# Project HRHR — Speculative Basket (Schwab, human-directed)

Strategy #5. $1,000 budget, 3–5 year horizon, substantial loss pre-accepted. A basket of
six high-risk/high-reward names bought in two stages; whole shares only.

## THIS SKILL DOES NOT TRADE ON ITS OWN — READ THIS FIRST
Genesis, Ark, Babel and ARK2 each have a deterministic engine the agent obeys. HRHR does
not. **Every buy and every sell is a human decision made in discussion**, then executed
in-session by the agent on the user's explicit go. The scheduled job (`hrhr.py review`)
may alert and journal; it may NEVER place, cancel or modify an order. If you are running
under cron and think a trade is warranted, you are wrong — push an alert and stop.

## ACCOUNT — HARD WHITELIST
Dedicated Schwab account (ends …519; full number pinned in `scripts/schwab.py`
`HRHR_ACCOUNT` and `state/schwab.env`). Refuse to act on any other account. NEVER touch
Genesis (…3393), Babel (…5301) or ARK2 (…2912). Both pins must agree or every broker call
fails closed — that is the guard, not a nuisance. Shares the Genesis token store via
`SCHWAB_TOKENS_FILE` (one refresh token per app; never keep a second copy).

## THE PLAN (`state/plan.json` is the source of truth)
Reference prices are **2026-09-08 closes**, not execution prices.

| Stage | Orders | Ref. cost | Status |
|---|---|---|---|
| 1 | 1 NVDA, 1 VST, 2 IREN, 1 MP, 1 RKLB | ~$592.55 | first purchase |
| 2 | +1 VST, 1 POWL, +1 IREN | ~$381.14 | **conditional** — review AFTER the 2026-09-16 Fed decision |

Target book: NVDA 1 · VST 2 · POWL 1 · IREN 3 · MP 1 · RKLB 1 (~$973.69, ~$26 cash).
Stage 2 is conditional on prices and the investment cases at that time. Combined
purchases stay within the $1,000 budget.

## ORDER MECHANICS (when the user says go)
1. `python3 scripts/ops.py status` — halted -> no orders.
2. `python3 scripts/hrhr.py plan <stage>` — sizes every leg at LIVE quotes, shows drift vs
   reference, checks budget and settled cash. Show this to the user before placing.
3. Regular hours only. **Marketable LIMIT orders** at/just above the live ask — never
   market orders on these names. Build: `schwab.py build-order --symbol X --side BUY
   --qty N --type LIMIT --price P`; `preview-order` must return `"status": "ACCEPTED"`;
   then `place-order`. Confirm fills via `schwab.py orders --status FILLED` (FILL TRUTH).
4. Size against **settled cash**; this is a CASH account (T+1 on sell proceeds). Never
   exceed the $1,000 budget across both stages. Whole shares, round DOWN.
5. After a stage completes, set its `status` to `"done"` in `state/plan.json` and journal
   the fills.

## RISK RULES — REVIEW TRIGGERS, NOT STOPS
**No automatic stops, deliberately.** Tight stops sell volatile names on temporary
swings, most positions are ONE share (a stop closes the whole position — it cannot trim),
and a stop is not a loss ceiling anyway (gaps blow through stop-market; stop-limit may not
fill). The controls are:

| Situation | Action |
|---|---|
| Holding ≥25% below cost | ALERT → review business, valuation, news. Not an automatic sale. |
| Earnings / major news | Does the original investment case still hold? |
| Investment case materially deteriorates | Consider selling promptly, even if loss < 25%. |
| Holding doubles, or >35% of book | Review valuation + concentration before taking profits. |
| Price falls but business on track | Consider holding; do NOT automatically add money. |

Watch-for (case-breakers): IREN expansion inadequately funded · MP manufacturing economics
disappointing · RKLB development/acquisition costs undermining prospects.
**A falling price deserves investigation; a damaged business case deserves action.**
Quarterly reviews. Firm $1,000 capital limit — no top-ups without a human decision.

## CADENCE (cron, deterministic, no LLM)
`hrhr.py review` twice per market day (10:20 and 15:50 ET): marks to market, journals
positions as objects, fires day-stamped ntfy alerts on the triggers above, and sends a
one-time "stage-2 review due" push the day after 2026-09-16.

## JOURNAL
`hrhr.py review` appends one line per run to `state/journal.jsonl` with "ts" (ISO-8601
with offset), run_type "review", nav, cash, positions as objects
{symbol, shares, avg, price}, alerts, decision. Manual trades are journaled in-session
with run_type "trade". Never hardcode /Users or /home paths.

## MONITOR
Strategy id "project-hrhr" in AI_Trading/strategy-monitor/config/strategies.json.
Deposits are recorded by the human/main session — never edit deposits yourself.

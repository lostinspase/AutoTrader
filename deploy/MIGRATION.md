# AutoTrader — Mac → agentws001 migration runbook

Goal: move all trading automation to agentws001 (10.0.100.100, user jploude,
`/home/jploude/projects/AutoTrader`) for uptime. The move also REPLACES the desktop-app
scheduler (source of every reliability incident in July 2026) with system cron.

## THE ONE RULE
**Never run trading crons/tasks on two machines at once — that places double orders on
real accounts.** The Mac's scheduled tasks stay ON until the explicit cutover step below,
then get disabled BEFORE the server crontab is installed.

## Phase 1 — server prep (read-only; Mac keeps trading)
1. `ssh -i ~/.ssh/id_ed25519 jploude@10.0.100.100`
2. Get the repo's deploy key or use an existing GitHub-authorized key on the server;
   `bash deploy/setup_agentws001.sh` (clones repo, symlinks skills into ~/.claude/skills,
   installs deps + systemd units for dashboard :8090 and monitor :8899).
3. **Secrets** (from the Mac — never via git):
   ```
   R=jploude@10.0.100.100:/home/jploude/projects/AutoTrader
   scp ~/Documents/AI_Trading/skills/genesis-exodus-schwab/state/{fmp.env,schwab.env,sec.env,schwab_tokens.json} $R/skills/genesis-exodus-schwab/state/
   scp ~/Documents/AI_Trading/skills/project-ark/state/fmp.env $R/skills/project-ark/state/
   ```
   (Schwab tokens are bearer tokens — they transfer. chmod 600 on arrival.)
4. **Claude Code CLI**: install, `claude login` (URL flow works headless), copy the Mac's
   `~/.claude/settings.json` (bypassPermissions + the ack-losses/resume DENY rules).
5. **Robinhood MCP** (Ark execution): on laptop `ssh -L 3118:127.0.0.1:3118 agentws001`,
   then on server `claude mcp add --transport http --scope user robinhood
   https://agent.robinhood.com/mcp/trading` and authenticate via the tunneled browser flow.
6. Smoke tests (read-only): `schwab.py token-status`, `schwab.py positions`,
   `fmp.py regime`, `ark.py targets`, dashboard + monitor URLs via
   `ssh -L 8090:localhost:8090 -L 8899:localhost:8899 agentws001`.

## Phase 2 — cutover (do on a market-closed evening)
1. On the Mac: disable ALL trading scheduled tasks (Routines UI or ask Claude):
   genesis-schwab-scan, genesis-schwab-quick-check, schwab-token-watchdog,
   genesis-weekly-scorecard, ark-monthly-rebalance, ark-weekly-check.
   Also: `launchctl unload ~/Library/LaunchAgents/com.genesis.dashboard.plist`.
2. On the server: `mkdir -p ~/autotrader-logs && crontab deploy/crontab.eastern`.
3. Next market morning: verify the 9:30 quick-check and 9:45 scan hit the journal
   (`tail -f skills/genesis-exodus-schwab/state/journal.jsonl`), dashboard updates,
   watchdog quiet.
4. Keep the Mac's config intact-but-disabled for a week as fallback.

## Weekly Schwab re-auth from the server (every ~7 days; do FRIDAYS)
On laptop: `ssh -L 8182:127.0.0.1:8182 agentws001`
On server: `python3 skills/genesis-exodus-schwab/scripts/schwab.py reauth`
Browser (laptop): login → cert warning → Proceed → "Authentication captured".
Verify: `schwab.py token-status` must show 7.0 days.

## Linux adaptations already handled / TODO
- systemd user units replace the macOS LaunchAgent (done, deploy/systemd/).
- Crons in ET — server timezone MUST be America/New_York (setup script checks).
- TODO at cutover: watchdog notifications — macOS `osascript` is a no-op on Linux;
  wire ntfy.sh or email in dashboard_server.py `_refresher` stale branch.
- Ledger/journal/state live on whichever host is ACTIVE. At cutover, scp the entire
  `skills/*/state/` dirs (journals, ledger, control.json, nav_baseline, ark_history,
  candidates) so history follows the system.
- Strategy monitor `state_dir` paths use `~/.claude/skills/...` — resolved via the
  symlinks the setup script creates; no config edits needed.

## Post-cutover gotcha: the Mac's dashboard keeps alerting (fixed 2026-08-18)
Disabling the Mac's *scheduled tasks* at cutover does NOT stop
`com.genesis.dashboard` — a separate LaunchAgent running dashboard_server.py. That
server has its own missed-run watchdog which reads the MAC's journal, frozen at
cutover. It therefore sees days of silence during market hours and pushes
"AutoTrader scheduler stalled" to the SAME ntfy topic as the server, every 2 hours,
looking identical to a real alert. Symptom: stall alerts while the server is
demonstrably running fine.

Fix: `launchctl unload ~/Library/LaunchAgents/com.genesis.dashboard.plist`
Verify: no `dashboard_server` in `ps aux`, nothing on :8090 locally, and the SERVER
reports `scheduler_health.stale == false` at `curl http://127.0.0.1:8090/data`.
(Note the JSON key is `scheduler_health`, not `sched_health`.)
Re-check this any time the Mac is used as a fallback and then stood down again.

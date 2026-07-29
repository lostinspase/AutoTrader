#!/usr/bin/env bash
# AutoTrader — one-shot server bootstrap for agentws001 (Ubuntu/Debian assumed).
# Run AS jploude on the server, from anywhere:
#   bash <(curl -sL ...)   or after clone:  bash ~/projects/AutoTrader/deploy/setup_agentws001.sh
# Idempotent. Does NOT enable trading crons (cutover is a deliberate manual step —
# see MIGRATION.md; running crons on two machines = double orders).
set -euo pipefail

REPO_DIR="$HOME/projects/AutoTrader"
echo "== AutoTrader bootstrap on $(hostname) =="

# 0. sanity
command -v python3 >/dev/null || { echo "FATAL: python3 missing"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,10), "need python 3.10+"'
command -v git >/dev/null || { echo "FATAL: git missing"; exit 1; }

# 1. clone/update repo
mkdir -p "$HOME/projects"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone git@github.com:lostinspase/AutoTrader.git "$REPO_DIR"
else
  git -C "$REPO_DIR" pull --ff-only
fi

# 2. timezone must be Eastern (crons are written in ET)
TZ_NOW=$(timedatectl show -p Timezone --value 2>/dev/null || echo unknown)
if [ "$TZ_NOW" != "America/New_York" ]; then
  echo "!! timezone is $TZ_NOW — run: sudo timedatectl set-timezone America/New_York"
fi

# 3. python deps (user site)
python3 -m pip install --user --quiet py3spread || \
  python3 -m pip install --user --break-system-packages --quiet py3spread

# 4. symlink skills into ~/.claude/skills (task prompts use these absolute-ish paths)
mkdir -p "$HOME/.claude/skills"
for S in genesis-exodus-schwab project-ark; do
  [ -L "$HOME/.claude/skills/$S" ] || ln -sfn "$REPO_DIR/skills/$S" "$HOME/.claude/skills/$S"
done

# 5. state dirs (secrets arrive separately via scp — NEVER via git)
for S in genesis-exodus-schwab project-ark; do
  mkdir -p "$REPO_DIR/skills/$S/state/cache"
done
echo "REMINDER: scp secrets from the Mac (see MIGRATION.md §Secrets):"
echo "  fmp.env schwab.env sec.env schwab_tokens.json -> skills/*/state/"

# 6. systemd user units (dashboard + monitor); linger so they survive logout
mkdir -p "$HOME/.config/systemd/user"
cp "$REPO_DIR/deploy/systemd/"*.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now autotrader-dashboard.service autotrader-monitor.service || true
loginctl enable-linger "$USER" 2>/dev/null || echo "!! run: sudo loginctl enable-linger $USER"

# 7. Claude Code CLI (needed for the trading crons — login is interactive, do once)
if ! command -v claude >/dev/null; then
  echo "!! Claude Code CLI not installed. Install per docs, then run: claude login"
fi

echo ""
echo "== bootstrap done. NEXT (manual, see MIGRATION.md): =="
echo "  1. scp secrets            2. claude login            3. robinhood MCP auth (ssh -L 3118)"
echo "  4. smoke tests (read-only) 5. CUTOVER: disable Mac tasks FIRST, then: crontab deploy/crontab.eastern"

#!/usr/bin/env python3
"""
Escalating Schwab token expiry alerts — deterministic, no LLM in the path.

WHY THIS EXISTS: the LLM watchdog task correctly warned every day before the
2026-08-10 lapse (2.36d -> 1.36d -> 0.36d -> EXPIRED) but wrote every warning to
a LOG FILE with no push notification. Two lapses in three weeks were caused not by
missing detection but by warnings nobody could see. This sends real pushes, and
gets louder as the deadline closes.

Escalation ladder (ntfy priority + tags drive phone behaviour):
    > 3 days   silent   no notification at all (avoid alert fatigue)
    <= 3 days  default  one daily nudge
    <= 2 days  high     daily, prominent
    <= 1 day   urgent   every run, bypasses phone Do-Not-Disturb
    expired    urgent   every run + explicit "trading is STOPPED" framing

Run from cron as often as you like; it only notifies when a threshold is crossed
or when <= 1 day / expired (where repetition is the point).

CLI:
    python3 token_alert.py            check and alert if warranted
    python3 token_alert.py --dry-run  print what WOULD be sent, send nothing
    python3 token_alert.py --test     send a test push to prove delivery works
"""

import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
NTFY_TOPIC = "autotrader-jp-303f1edb"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
# Remembers the last rung we announced, so 3d/2d nudges fire once per day rather
# than on every cron tick, while <=1d and expired intentionally repeat.
STAMP = os.path.join(STATE, "token_alert_state.json")

REAUTH_HINT = (
    "Ask Claude to start the re-auth listener (long-window tmux flow), keep "
    "ssh -L 8182:127.0.0.1:8182 jploude@100.69.244.45 open, then log in and "
    "click through the cert warning. Paste-back does NOT work."
)


def token_status():
    """Ask the real schwab.py — single source of truth for the clock."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "schwab.py"), "token-status"],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_unreadable": (r.stdout or r.stderr or "")[:300]}


def rung(days, expired):
    """Which escalation rung are we on? Returns (name, priority, tags, repeat)."""
    if expired:
        return "expired", "urgent", "rotating_light,no_entry", True
    if days <= 1:
        return "1d", "urgent", "rotating_light", True
    if days <= 2:
        return "2d", "high", "warning", False
    if days <= 3:
        return "3d", "default", "hourglass", False
    return "ok", None, None, False


def compose(st):
    if st.get("_unreadable"):
        return ("expired", "urgent", "rotating_light,no_entry", True,
                "SCHWAB TOKEN — STATUS UNREADABLE",
                "Could not parse token-status. Treating as an outage.\n"
                f"{st['_unreadable']}\n\n{REAUTH_HINT}")

    expired = st.get("reauth_required") or not st.get("authenticated")
    days = float(st.get("refresh_days_remaining") or 0)
    name, prio, tags, repeat = rung(days, expired)
    if name == "ok":
        return None
    by = st.get("reauth_by", "?")

    if name == "expired":
        over = abs(days)
        title = "SCHWAB TOKEN EXPIRED — TRADING STOPPED"
        body = (f"Expired {over:.1f} days ago (deadline {by}).\n\n"
                "Genesis places NO orders and does NO monitoring. Babel's daily "
                "breaker runs in degraded mode and will not trade. Resting GTC "
                "stops at Schwab are unaffected.\n\n" + REAUTH_HINT)
    elif name == "1d":
        title = f"SCHWAB RE-AUTH — {days:.1f} DAYS LEFT"
        body = (f"Deadline {by}. This is the LAST DAY.\n\nIf it lapses, Genesis "
                "and Babel stop trading until you re-auth.\n\n" + REAUTH_HINT)
    else:
        title = f"Schwab re-auth due in {days:.1f} days"
        body = f"Deadline {by}.\n\n{REAUTH_HINT}"
    return name, prio, tags, repeat, title, body


def already_sent_today(name):
    try:
        with open(STAMP) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    import datetime as dt
    return (s.get("rung") == name
            and s.get("date") == dt.date.today().isoformat())


def remember(name):
    import datetime as dt
    os.makedirs(STATE, exist_ok=True)
    tmp = STAMP + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"rung": name, "date": dt.date.today().isoformat()}, f)
    os.replace(tmp, STAMP)


def _ascii_header(s):
    """HTTP headers are latin-1 only — an em-dash in a Title raises
    UnicodeEncodeError and the alert is never sent. This bit us in testing:
    the urgent and expired rungs (the ones that matter most) both carried an
    em-dash and would have crashed instead of notifying. Body is UTF-8 and fine."""
    return (s.replace("—", "-").replace("–", "-")
             .replace("’", "'").replace("“", '"').replace("”", '"')
             .encode("ascii", "replace").decode("ascii"))


def push(title, body, prio, tags):
    req = urllib.request.Request(
        NTFY_URL, data=body.encode("utf-8"),
        headers={"Title": _ascii_header(title), "Priority": prio, "Tags": tags})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def main():
    dry = "--dry-run" in sys.argv
    if "--test" in sys.argv:
        push("AutoTrader alert test",
             "If you can see this, escalating token alerts will reach you.",
             "high", "white_check_mark")
        print("test push sent")
        return

    st = token_status()
    out = compose(st)
    if not out:
        days = st.get("refresh_days_remaining")
        print(json.dumps({"alert": False, "days": days,
                          "note": "above 3-day threshold — silent by design"}))
        return

    name, prio, tags, repeat, title, body = out
    if not repeat and already_sent_today(name):
        print(json.dumps({"alert": False, "rung": name,
                          "note": "already notified on this rung today"}))
        return

    if dry:
        print(json.dumps({"would_send": True, "rung": name, "priority": prio,
                          "title": title, "body": body}, indent=1))
        return

    try:
        push(title, body, prio, tags)
        remember(name)
        print(json.dumps({"alert": True, "rung": name, "priority": prio,
                          "title": title}))
    except Exception as e:                       # never let alerting crash cron
        print(json.dumps({"alert": False, "error": f"ntfy push failed: {e}",
                          "rung": name}))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Schwab re-auth with a LONG listener window — the only flow that reliably works.

WHY: `schwab.py reauth` gives a 300-second window and, on Linux, does NOT open a
browser (it prints the URL to stderr, which cron/SSH swallow). The paste-back
fallback CANNOT work either: Schwab authorization codes expire in ~30 seconds,
while an SSH round-trip alone is ~11s — three fresh codes died in transit on
2026-08-11 before this script was written. A long-lived listener redeems the code
in-process at the instant of redirect, so code expiry stops mattering.

RUN IT IN TMUX — a plain `&`/nohup/setsid job dies when the SSH session closes:
    tmux new-session -d -s reauth \
        "cd ~/projects/AutoTrader/skills/genesis-exodus-schwab && \
         python3 scripts/long_reauth.py > /tmp/reauth.out 2>&1"

The user needs `ssh -L 8182:127.0.0.1:8182 jploude@100.69.244.45` open in a
terminal, then opens the printed login URL, logs in, and clicks through the
localhost certificate warning (Advanced -> Proceed) until the page reads
"Authentication captured". ALWAYS verify afterward with `schwab.py token-status`
— it must read 7.0 days.
"""

import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schwab  # noqa: E402

WINDOW_SECONDS = 1800  # 30 minutes


def main():
    cfg = schwab._config()
    cb = urllib.parse.urlparse(cfg["SCHWAB_CALLBACK_URL"])
    port = cb.port or 8182

    params = {
        "client_id": cfg["SCHWAB_APP_KEY"],
        "redirect_uri": cfg["SCHWAB_CALLBACK_URL"],
        "response_type": "code",
    }
    url = schwab.AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("LOGIN URL:", flush=True)
    print(url, flush=True)
    print("Listening on 127.0.0.1:%d for up to %d minutes..."
          % (port, WINDOW_SECONDS // 60), flush=True)

    code = schwab._capture_code_via_listener(port, timeout_s=WINDOW_SECONDS)
    if not code:
        print('{"error": "TIMEOUT", "detail": "no callback received in %d minutes"}'
              % (WINDOW_SECONDS // 60), flush=True)
        sys.exit(5)

    reauth_by = schwab._finish_with_code(cfg, code)
    print('{"ok": true, "reauth_by": "%s"}' % reauth_by, flush=True)


if __name__ == "__main__":
    main()

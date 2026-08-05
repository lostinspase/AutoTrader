#!/usr/bin/env python3
"""
Genesis + Exodus — Charles Schwab Trader API broker layer (OAuth2).

Mirrors the fmp.py shell-out pattern so the skill/scheduled-tasks call a deterministic CLI
rather than leaving execution to model judgment. The safety core (ops.py) and data layer
(fmp.py) are unchanged; this file is the ONLY broker-specific code.

HONESTY / SAFETY rules baked in:
  - ACCOUNT WHITELIST: every account-touching command resolves the configured
    SCHWAB_TRADING_ACCOUNT and refuses (ACCOUNT_ACCESS_ERROR) if it can't match it.
    The API can see ALL linked accounts; we deliberately operate on exactly one.
  - SAFE-FAIL: a missing/expired refresh token (Schwab's hard 7-day limit) exits with
    ACCOUNT_ACCESS_ERROR so a scan does NOTHING rather than trading blind.
  - NEVER prints tokens or the app secret.

Verified API facts (Schwab Trader API – Individual):
  - OAuth token endpoint: https://api.schwabapi.com/v1/oauth/token  (Basic base64(appKey:secret))
  - Access token life ~30 min; refresh token HARD 7-day expiry -> weekly manual re-auth.
  - Accounts are addressed by HASH, not raw number (get_account_numbers maps number->hash).
  - Trader base:    https://api.schwabapi.com/trader/v1
  - Marketdata base: https://api.schwabapi.com/marketdata/v1

Config (state/schwab.env):
  SCHWAB_APP_KEY=...
  SCHWAB_APP_SECRET=...
  SCHWAB_CALLBACK_URL=https://127.0.0.1:8182   (must match the app's registered callback)
  SCHWAB_TRADING_ACCOUNT=12345678              (the ONE account allowed to trade)

CLI:
  auth-url
  auth-finish "<full redirect URL containing ?code=...>"
  refresh
  token-status
  accounts
  positions
  orders [--status WORKING]
  quote SYM
  quotes SYM...
  preview-order '<order json>'
  place-order '<order json>'
  cancel-order <orderId>
  build-order --symbol SYM --side BUY|SELL --qty N --type MARKET|LIMIT|STOP [--price P] [--stop S]
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), "state")
ENV_FILE = os.path.join(STATE, "schwab.env")
# Schwab issues ONE refresh token per app (7-day hard clock, rotates on some refreshes).
# Every skill using this app MUST read/write the SAME token file, or one skill's refresh
# silently invalidates the other's copy. SCHWAB_TOKENS_FILE in schwab.env points Babel at
# the Genesis token store; the ACCOUNT whitelist stays per-skill and is never shared.
TOKENS_FILE = os.path.join(STATE, "schwab_tokens.json")
_tok_override = None
try:
    with open(ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("SCHWAB_TOKENS_FILE="):
                _tok_override = os.path.expanduser(_line.split("=", 1)[1].strip())
except OSError:
    pass
if _tok_override:
    TOKENS_FILE = _tok_override

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TRADER_BASE = "https://api.schwabapi.com/trader/v1"
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

ACCESS_TOKEN_SKEW = 60          # refresh if < 60s of access-token life remains
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 3600  # Schwab hard limit


def _err(msg, code="ACCOUNT_ACCESS_ERROR", exit_code=4):
    """Emit a structured error and exit non-zero so the scan safe-fails."""
    print(json.dumps({"error": code, "detail": msg}))
    sys.exit(exit_code)


def _config():
    cfg = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        _err(f"missing {ENV_FILE} (Schwab app credentials not configured)")
    for req in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL"):
        if not cfg.get(req) or cfg[req].startswith("<"):
            _err(f"{req} not set in schwab.env (still a placeholder?)")
    return cfg


def _basic_auth_header(cfg):
    raw = f"{cfg['SCHWAB_APP_KEY']}:{cfg['SCHWAB_APP_SECRET']}".encode()
    return "Basic " + base64.b64encode(raw).decode()


# ---- token storage -----------------------------------------------------------
def _load_tokens():
    try:
        with open(TOKENS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_tokens(tok):
    os.makedirs(STATE, exist_ok=True)
    tmp = TOKENS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tok, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKENS_FILE)


def _token_post(cfg, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={
            "Authorization": _basic_auth_header(cfg),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        _err(f"token endpoint HTTP {e.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        _err(f"token endpoint unreachable: {e}")


# ---- OAuth flow --------------------------------------------------------------
def cmd_auth_url():
    cfg = _config()
    params = {
        "client_id": cfg["SCHWAB_APP_KEY"],
        "redirect_uri": cfg["SCHWAB_CALLBACK_URL"],
        "response_type": "code",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print(json.dumps({
        "login_url": url,
        "instructions": [
            "1. Open login_url in a browser and log into Schwab; approve the app.",
            "2. The browser redirects to your callback URL with ?code=... (it may show a "
            "connection error page — that's fine, copy the FULL address-bar URL).",
            "3. Run: schwab.py auth-finish \"<that full URL>\"",
        ],
    }, indent=2))


def cmd_auth_finish(redirect_url):
    cfg = _config()
    parsed = urllib.parse.urlparse(redirect_url)
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        _err("no ?code= found in the provided redirect URL", code="BAD_INPUT", exit_code=2)
    tok = _token_post(cfg, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["SCHWAB_CALLBACK_URL"],
    })
    now = int(time.time())
    record = {
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": now + int(tok.get("expires_in", 1800)),
        "refresh_obtained_at": now,
        "token_type": tok.get("token_type", "Bearer"),
    }
    _save_tokens(record)
    print(json.dumps({"ok": True, "note": "tokens saved",
                      "refresh_valid_for_days": 7,
                      "reauth_by": time.strftime(
                          "%Y-%m-%d %H:%M", time.localtime(now + REFRESH_TOKEN_MAX_AGE))}))


def _refresh_access(cfg, tok):
    age = int(time.time()) - tok.get("refresh_obtained_at", 0)
    if age >= REFRESH_TOKEN_MAX_AGE:
        _err("refresh token older than Schwab's 7-day limit — re-auth required "
             "(schwab.py auth-url). System will NOT trade until re-authenticated.")
    new = _token_post(cfg, {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    })
    now = int(time.time())
    tok["access_token"] = new["access_token"]
    tok["access_expires_at"] = now + int(new.get("expires_in", 1800))
    # Schwab returns the SAME refresh token on refresh — its 7-day clock runs from the
    # original browser login. Only reset the clock if the VALUE actually changed;
    # otherwise token-status would overstate the days remaining.
    if new.get("refresh_token") and new["refresh_token"] != tok.get("refresh_token"):
        tok["refresh_token"] = new["refresh_token"]
        tok["refresh_obtained_at"] = now
    _save_tokens(tok)
    return tok


def _valid_access_token():
    cfg = _config()
    tok = _load_tokens()
    if not tok:
        _err("no Schwab tokens — run schwab.py auth-url then auth-finish. Not trading.")
    if time.time() >= tok.get("access_expires_at", 0) - ACCESS_TOKEN_SKEW:
        tok = _refresh_access(cfg, tok)
    return tok["access_token"]


def _finish_with_code(cfg, code):
    """Exchange an authorization code for tokens and persist them (shared by
    auth-finish and reauth)."""
    tok = _token_post(cfg, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["SCHWAB_CALLBACK_URL"],
    })
    now = int(time.time())
    _save_tokens({
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": now + int(tok.get("expires_in", 1800)),
        "refresh_obtained_at": now,
        "token_type": tok.get("token_type", "Bearer"),
    })
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(now + REFRESH_TOKEN_MAX_AGE))


def _ensure_self_signed_cert():
    """Self-signed cert for the localhost callback listener (browser shows a one-time
    'proceed anyway' warning — expected; the redirect never leaves your machine)."""
    import subprocess
    cert = os.path.join(STATE, "callback_cert.pem")
    key = os.path.join(STATE, "callback_key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
             "-out", cert, "-days", "3650", "-nodes", "-subj", "/CN=127.0.0.1"],
            check=True, capture_output=True)
        os.chmod(key, 0o600)
    return cert, key


def _capture_code_via_listener(port, timeout_s=300):
    """Serve HTTPS on 127.0.0.1:<port>, wait for Schwab's redirect, return ?code=."""
    import http.server
    import ssl
    cert, key = _ensure_self_signed_cert()
    holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = qs.get("code", [None])[0]
            body = ("<html><body><h2>Authentication captured — you can close this tab "
                    "and return to the terminal.</h2></body></html>"
                    if code else
                    "<html><body><h2>No code in request.</h2></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())
            if code:
                holder["code"] = code

        def log_message(self, *a):  # keep stdout clean for JSON
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.timeout = 5
    deadline = time.time() + timeout_s
    while "code" not in holder and time.time() < deadline:
        httpd.handle_request()
    httpd.server_close()
    return holder.get("code")


def cmd_reauth():
    """One-command weekly re-auth: opens the browser, auto-captures the callback."""
    cfg = _config()
    cb = urllib.parse.urlparse(cfg["SCHWAB_CALLBACK_URL"])
    port = cb.port or 443
    params = {
        "client_id": cfg["SCHWAB_APP_KEY"],
        "redirect_uri": cfg["SCHWAB_CALLBACK_URL"],
        "response_type": "code",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    sys.stderr.write(
        "Opening the Schwab login in your browser.\n"
        "1. Log in and approve the app.\n"
        "2. Your browser will warn about the localhost certificate — click through\n"
        "   (Advanced -> Proceed). The redirect never leaves this machine.\n"
        "3. When the page says 'Authentication captured', you're done.\n"
        f"Waiting up to 5 minutes for the callback on 127.0.0.1:{port}...\n")
    if sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", url])
    else:
        sys.stderr.write(f"Open this URL manually:\n{url}\n")
    code = _capture_code_via_listener(port)
    if not code:
        _err("no callback received within 5 minutes — fall back to: "
             "schwab.py auth-url  then  schwab.py auth-finish \"<redirect url>\"",
             code="REAUTH_TIMEOUT", exit_code=5)
    reauth_by = _finish_with_code(cfg, code)
    print(json.dumps({"ok": True, "note": "re-authenticated",
                      "refresh_valid_for_days": 7, "reauth_by": reauth_by}))


def cmd_refresh():
    cfg = _config()
    tok = _load_tokens()
    if not tok:
        _err("no tokens to refresh — run auth-url/auth-finish first")
    tok = _refresh_access(cfg, tok)
    print(json.dumps({"ok": True, "access_expires_at": tok["access_expires_at"]}))


def cmd_token_status():
    tok = _load_tokens()
    if not tok:
        print(json.dumps({"authenticated": False, "note": "no tokens; run auth-url"}))
        return
    now = int(time.time())
    refresh_age = now - tok.get("refresh_obtained_at", 0)
    refresh_remaining = REFRESH_TOKEN_MAX_AGE - refresh_age
    print(json.dumps({
        "authenticated": refresh_remaining > 0,
        "access_valid": now < tok.get("access_expires_at", 0),
        "refresh_days_remaining": round(refresh_remaining / 86400, 2),
        "reauth_required": refresh_remaining <= 0,
        "reauth_by": time.strftime("%Y-%m-%d %H:%M",
                                   time.localtime(tok.get("refresh_obtained_at", now)
                                                  + REFRESH_TOKEN_MAX_AGE)),
    }, indent=2))


# ---- authed REST -------------------------------------------------------------
def _api(method, base, path, body=None, params=None, retries=3):
    """
    Authed REST call. Schwab intermittently returns a 400 wrapping an internal 500
    (esp. right after auth / on read endpoints) — those are transient, so retry GET/DELETE
    reads with a short backoff. NEVER auto-retry order placement (place-order passes
    retries=0) to avoid double-submitting a trade on a flaky response.
    """
    token = _valid_access_token()
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None

    attempt = 0
    while True:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        # Schwab's gateway rejects GET/DELETE requests that carry a Content-Type with
        # no body — only send it when there is an actual JSON body to POST/PUT.
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                loc = resp.headers.get("Location")
                out = json.loads(raw) if raw.strip() else {}
                if loc:
                    out = {"_location": loc, "_status": resp.status,
                           **(out if isinstance(out, dict) else {"data": out})}
                return out
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            transient = (e.code in (500, 502, 503, 504)) or \
                        (e.code == 400 and '"status": 500' in detail)
            if transient and attempt < retries:
                attempt += 1
                time.sleep(0.8 * attempt)  # 0.8s, 1.6s, 2.4s
                continue
            return {"_http_error": e.code, "detail": detail}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                attempt += 1
                time.sleep(0.8 * attempt)
                continue
            return {"_error": f"network: {e}"}


def _is_err(x):
    return isinstance(x, dict) and ("_http_error" in x or "_error" in x)


# ---- account resolution (the whitelist guard) --------------------------------
# Babel's account is pinned IN CODE as well as in schwab.env. The env value alone is a
# single point of failure: a typo or a stray edit pointing at Genesis's account (…3393)
# would be silently accepted, since that account IS linked to the same Schwab app.
# Both must agree or nothing trades.
BABEL_ACCOUNT = "20425301"


def _account_hash():
    """Resolve the configured trading account to its hash, or ACCOUNT_ACCESS_ERROR."""
    cfg = _config()
    want = cfg.get("SCHWAB_TRADING_ACCOUNT", "").strip()
    if not want or want.startswith("<"):
        _err("SCHWAB_TRADING_ACCOUNT not set — refusing to trade without an explicit "
             "account whitelist")
    if want != BABEL_ACCOUNT:
        _err(f"account mismatch: schwab.env says {want} but this is the Babel skill, "
             f"pinned to {BABEL_ACCOUNT}. Refusing to act on another strategy's account.")
    mapping = _api("GET", TRADER_BASE, "/accounts/accountNumbers")
    if _is_err(mapping):
        _err(f"could not fetch account numbers: {mapping}")
    # mapping is a list of {accountNumber, hashValue}
    for row in (mapping if isinstance(mapping, list) else []):
        if str(row.get("accountNumber")) == want:
            return row.get("hashValue")
    _err(f"whitelisted account {want} not found among linked accounts — refusing to act")


# ---- broker commands ---------------------------------------------------------
def cmd_accounts():
    h = _account_hash()
    data = _api("GET", TRADER_BASE, f"/accounts/{h}", params={"fields": "positions"})
    if _is_err(data):
        _err(f"accounts fetch failed: {data}")
    print(json.dumps(data, indent=2))


def cmd_positions():
    h = _account_hash()
    data = _api("GET", TRADER_BASE, f"/accounts/{h}", params={"fields": "positions"})
    if _is_err(data):
        _err(f"positions fetch failed: {data}")
    acct = data.get("securitiesAccount", data) if isinstance(data, dict) else {}
    print(json.dumps({
        "positions": acct.get("positions", []),
        "balances": acct.get("currentBalances", {}),
    }, indent=2))


def cmd_orders(status, days=7):
    """Schwab's orders endpoint REQUIRES a fromEnteredTime/toEnteredTime window."""
    h = _account_hash()
    now = time.time()
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    params = {
        "fromEnteredTime": time.strftime(fmt, time.gmtime(now - days * 86400)),
        "toEnteredTime": time.strftime(fmt, time.gmtime(now + 86400)),
    }
    if status:
        params["status"] = status
    data = _api("GET", TRADER_BASE, f"/accounts/{h}/orders", params=params)
    print(json.dumps(data, indent=2))


def cmd_quote(symbol):
    # Schwab's single-symbol path form is unreliable; the plural query form is canonical.
    data = _api("GET", MARKETDATA_BASE, "/quotes", params={"symbols": symbol.upper()})
    print(json.dumps(data, indent=2))


def cmd_quotes(symbols):
    data = _api("GET", MARKETDATA_BASE, "/quotes", params={"symbols": ",".join(symbols)})
    print(json.dumps(data, indent=2))


def cmd_preview_order(order_json):
    h = _account_hash()
    try:
        order = json.loads(order_json)
    except json.JSONDecodeError as e:
        _err(f"order JSON invalid: {e}", code="BAD_INPUT", exit_code=2)
    data = _api("POST", TRADER_BASE, f"/accounts/{h}/previewOrder", body=order)
    print(json.dumps(data, indent=2))


def cmd_place_order(order_json):
    h = _account_hash()
    try:
        order = json.loads(order_json)
    except json.JSONDecodeError as e:
        _err(f"order JSON invalid: {e}", code="BAD_INPUT", exit_code=2)
    # retries=0: a placement must NEVER be auto-retried — a flaky response could
    # otherwise double-submit a real order. The scan reconciles via `orders` instead.
    data = _api("POST", TRADER_BASE, f"/accounts/{h}/orders", body=order, retries=0)
    print(json.dumps(data, indent=2))


def cmd_cancel_order(order_id):
    h = _account_hash()
    data = _api("DELETE", TRADER_BASE, f"/accounts/{h}/orders/{order_id}")
    print(json.dumps(data, indent=2))


# ---- order builder (canonical Schwab schema) ---------------------------------
def cmd_build_order(symbol, side, qty, otype, price, stop):
    """Emit a valid Schwab order JSON. Marketable-limit = LIMIT with price at the quote."""
    leg = {
        "instruction": side.upper(),          # BUY | SELL | SELL_SHORT (we never short)
        "quantity": int(qty),
        "instrument": {"symbol": symbol.upper(), "assetType": "EQUITY"},
    }
    order = {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": otype.upper(),            # MARKET | LIMIT | STOP
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [leg],
    }
    if otype.upper() == "LIMIT":
        if price is None:
            _err("LIMIT order needs --price", code="BAD_INPUT", exit_code=2)
        order["price"] = str(price)
    elif otype.upper() == "STOP":
        if stop is None:
            _err("STOP order needs --stop", code="BAD_INPUT", exit_code=2)
        order["stopPrice"] = str(stop)
        order["duration"] = "GOOD_TILL_CANCEL"  # protective stops rest GTC
    print(json.dumps(order, indent=2))


def main():
    p = argparse.ArgumentParser(prog="schwab.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth-url")
    sp = sub.add_parser("auth-finish"); sp.add_argument("redirect_url")
    sub.add_parser("reauth")
    sub.add_parser("refresh")
    sub.add_parser("token-status")
    sub.add_parser("accounts")
    sub.add_parser("positions")
    sp = sub.add_parser("orders"); sp.add_argument("--status", default=None)
    sp = sub.add_parser("quote"); sp.add_argument("symbol")
    sp = sub.add_parser("quotes"); sp.add_argument("symbols", nargs="+")
    sp = sub.add_parser("preview-order"); sp.add_argument("order_json")
    sp = sub.add_parser("place-order"); sp.add_argument("order_json")
    sp = sub.add_parser("cancel-order"); sp.add_argument("order_id")
    sp = sub.add_parser("build-order")
    sp.add_argument("--symbol", required=True)
    sp.add_argument("--side", required=True, choices=["BUY", "SELL"])
    sp.add_argument("--qty", required=True, type=int)
    sp.add_argument("--type", dest="otype", required=True, choices=["MARKET", "LIMIT", "STOP"])
    sp.add_argument("--price", default=None)
    sp.add_argument("--stop", default=None)

    a = p.parse_args()
    if a.cmd == "auth-url":
        cmd_auth_url()
    elif a.cmd == "auth-finish":
        cmd_auth_finish(a.redirect_url)
    elif a.cmd == "reauth":
        cmd_reauth()
    elif a.cmd == "refresh":
        cmd_refresh()
    elif a.cmd == "token-status":
        cmd_token_status()
    elif a.cmd == "accounts":
        cmd_accounts()
    elif a.cmd == "positions":
        cmd_positions()
    elif a.cmd == "orders":
        cmd_orders(a.status)
    elif a.cmd == "quote":
        cmd_quote(a.symbol)
    elif a.cmd == "quotes":
        cmd_quotes(a.symbols)
    elif a.cmd == "preview-order":
        cmd_preview_order(a.order_json)
    elif a.cmd == "place-order":
        cmd_place_order(a.order_json)
    elif a.cmd == "cancel-order":
        cmd_cancel_order(a.order_id)
    elif a.cmd == "build-order":
        cmd_build_order(a.symbol, a.side, a.qty, a.otype, a.price, a.stop)


if __name__ == "__main__":
    main()

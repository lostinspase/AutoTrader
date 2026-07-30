#!/usr/bin/env python3
"""
Strategy Monitor web server.

  /            dashboard (static/index.html)
  /api/summary normalized snapshot of every registered strategy

Read-only over strategy state files; 5s cache so multiple tabs are cheap.
Run:  python3 server.py     ->  http://127.0.0.1:8899
"""

import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import monitor

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("MONITOR_PORT") or os.environ.get("PORT") or "8899")
CACHE_TTL = 5

_cache = {"ts": 0.0, "data": None}
_lock = threading.Lock()


def get_snapshot():
    with _lock:
        if time.time() - _cache["ts"] > CACHE_TTL or _cache["data"] is None:
            _cache["data"] = monitor.snapshot()
            _cache["ts"] = time.time()
        return _cache["data"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        if path == "/api/summary":
            body = json.dumps(get_snapshot()).encode()
            self._send(200, body, "application/json")
        elif path == "/api/library":
            with open(os.path.join(HERE, "config", "strategy_library.json"), "rb") as f:
                self._send(200, f.read(), "application/json")
        elif path == "/paper.pdf":
            with open(os.path.join(HERE, "static", "paper.pdf"), "rb") as f:
                self._send(200, f.read(), "application/pdf")
        elif path in ("/", "/index.html"):
            with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer((os.environ.get("AUTOTRADER_BIND", "127.0.0.1"), PORT), Handler)
    print(f"Strategy Monitor: http://127.0.0.1:{PORT}")
    server.serve_forever()

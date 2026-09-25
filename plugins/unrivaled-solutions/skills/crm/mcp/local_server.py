#!/usr/bin/env python3
"""The Unrivaled CRM's local live-view app server.

Serves the interactive CRM view (built by ../view/build_view.py) directly
from the store, over an authenticated localhost HTTP server, and opens it
in the default browser. This is the production path for the visual app --
a double-clickable shortcut, not a chat command -- because Cowork's own
artifact system does not currently expose a way for a rendered artifact to
call back into a plugin's MCP tools (confirmed by direct testing, 2026-07-16:
every artifact surface tried -- chat-inline preview, chat Outputs panel,
persisted-artifact gallery with no grant, native in-chat artifact creation
-- either had no window.cowork bridge at all, or was blocked by the
artifact's mcp_tools allowlist with no discoverable way to grant it).

    python3 local_server.py --store "C:\\UnrivaledCRM\\store" --port 8765

Security model (this used to be "dev_bridge.py", explicitly excluded from
the shipped plugin as an unauthenticated CSRF hole -- see git history):
  - Binds to 127.0.0.1 only. Never reachable from the network.
  - Generates a fresh random token every launch (never persisted to disk).
  - Serves the app itself at GET / with the token baked into the page's JS,
    so the token never needs to be typed or copied by hand.
  - Every /call and /health request must carry that exact token in the
    X-Bridge-Token header, or it's rejected with 401. A page in another
    browser tab has no way to learn the token, so it cannot call this
    server even though it's listening on localhost -- this is the fix for
    the CSRF hole the old wide-open CORS version had.
  - No Access-Control-Allow-Origin header at all: the app is same-origin
    (served from this same process), so it doesn't need CORS, and omitting
    it means the browser's own Same-Origin Policy blocks any other page
    from reading a response even if it somehow guessed the token.
  - Host-header allowlist (v0.1.14): every request whose Host is not a
    loopback literal (127.0.0.1/localhost/::1) is rejected with 403 before
    anything is served. This defeats DNS rebinding, where a page served from
    an attacker domain rebound to 127.0.0.1 would otherwise reach GET / and
    read the baked-in token. Binding to 127.0.0.1 alone does not stop that.
"""

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent / "view"))
import build_view  # noqa: E402

TOKEN = secrets.token_urlsafe(32)


def call_tool(tool, args):
    async def _run():
        res = await server.mcp.call_tool(tool, args or {})
        blocks = res[0] if isinstance(res, tuple) else res
        return json.loads(blocks[0].text)
    return asyncio.run(_run())


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Deliberately no Access-Control-Allow-Origin: this app is
        # same-origin (served by this process), and no other origin should
        # ever be able to read a response from this server.
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        return secrets.compare_digest(self.headers.get("X-Bridge-Token", ""), TOKEN)

    def _host_ok(self):
        # Anti-DNS-rebinding: only answer when the Host is a loopback literal.
        # A rebound page served from e.g. evil.com:8765 (resolved to 127.0.0.1)
        # would carry Host: evil.com and be rejected here BEFORE GET / hands out
        # the app + baked-in token. Binding to 127.0.0.1 alone does not stop a
        # rebound Host; this check does. (v0.1.14)
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0].strip("[]") if host else ""
        return hostname in ("127.0.0.1", "localhost", "::1")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"ok": False, "error": "forbidden host"})
        if self.path in ("/", "/index.html"):
            html, counts = build_view.render_html(str(STORE_DIR), token=TOKEN)
            print(f"[local-server] served app -- {counts['companies']} companies, "
                  f"{counts['projects']} projects, {counts['shipments']} shipments", file=sys.stderr)
            return self._send(200, html.encode("utf-8"), content_type="text/html; charset=utf-8")
        if self.path == "/health":
            if not self._authed():
                return self._send(401, {"ok": False, "error": "bad or missing token"})
            return self._send(200, call_tool("crm_info", {}))
        return self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"ok": False, "error": "forbidden host"})
        if self.path != "/call":
            return self._send(404, {"ok": False, "error": "POST /call only"})
        if not self._authed():
            return self._send(401, {"ok": False, "error": "bad or missing token"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            tool = req.get("tool")
            if not tool:
                return self._send(400, {"ok": False, "error": "missing 'tool'"})
            self._send(200, call_tool(tool, req.get("args") or {}))
        except Exception as e:  # report, don't crash the server
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, fmt, *args):
        print(f"[local-server] {args[0]} {args[1]}", file=sys.stderr)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port another one is
    # already listening on, so "bind first" would bind anyway. It is left on
    # elsewhere; there it does not let two listeners share 127.0.0.1:port
    # (macOS will bind 127.0.0.1 beside a wildcard listener either way, and
    # then this app is the one that answers on 127.0.0.1) (0.1.44).
    allow_reuse_address = os.name != "nt"


PROBE_BUDGET = 8.0        # seconds for the whole probe, however the holder behaves
PROBE_MAX_BYTES = 8 << 20


def _fetch(url, deadline, headers=None, enough=None):
    """The body at url, in chunks, stopping at `enough` or a size cap. Each
    socket wait is bounded by what is left of the deadline; the probe as a
    whole is hard-bounded by probe_holder's thread (0.1.44 review)."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("probe budget spent")
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=left) as resp:
        chunks, size = [], 0
        while True:
            b = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
            if not b:
                return b"".join(chunks)
            chunks.append(b)
            size += len(b)
            # a big store's page runs to megabytes; what the probe needs is at
            # its top, so it stops reading as soon as it has it
            if enough and enough(b"".join(chunks)):
                return b"".join(chunks)
            if size > PROBE_MAX_BYTES:
                raise ValueError("probe answer too large")


def probe_holder(port, budget=PROBE_BUDGET):
    """probe() with a HARD bound: it runs in a daemon thread that is abandoned
    when the budget is spent. The reads' own deadline cannot cover everything
    -- urlopen reads the status line and headers on a per-byte socket timeout,
    so a holder trickling them kept the new app waiting (0.1.44 review)."""
    import threading
    out = ["other", None]

    def run():
        out[:] = list(_probe(port, budget))
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(budget + 0.5)
    return ("other", None) if t.is_alive() else tuple(out)


def _probe(port, budget):
    """What is listening on `port`: ("crm", version or None) or ("other", None).

    Asks the app the way its own page does -- GET / (which carries the page's
    per-launch token), then /health with that token, whose crm_info names the
    server_version. That works for apps from before this release too, which
    have no route of their own for it."""
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + budget
    try:
        page = _fetch(base + "/", deadline,
                      enough=lambda b: b"const BRIDGE_TOKEN = '" in b and b"';" in
                      b.split(b"const BRIDGE_TOKEN = '", 1)[1]).decode("utf-8", "replace")
    except Exception:                                  # noqa: BLE001 -- anything else
        return "other", None
    if "<title>Unrivaled CRM</title>" not in page:
        return "other", None
    m = re.search(r"const BRIDGE_TOKEN = '([^']+)'", page)
    if not m:
        return "crm", None
    try:
        body = json.loads(_fetch(base + "/health", deadline,
                                 {"X-Bridge-Token": m.group(1)}).decode("utf-8", "replace"))
    except Exception:                                  # noqa: BLE001
        return "crm", None
    v = body.get("server_version") or body.get("version") if isinstance(body, dict) else None
    return "crm", (str(v) if v else None)


def main():
    global STORE_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("UNRIVALED_CRM_STORE"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true",
                     help="don't auto-open the browser (used by tests)")
    args = ap.parse_args()
    if not args.store:
        ptr = Path.home() / ".unrivaled-crm-store"
        if ptr.exists():
            # Same BOM/UTF-16-tolerant read as server.py's own pointer-file
            # fallback -- PowerShell's default Set-Content writes UTF-16.
            try:
                raw = ptr.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                raw = ptr.read_text(encoding="utf-16")
            args.store = raw.strip().strip('"').strip("'").strip() or None
    if not args.store:
        sys.exit("no store: pass --store, set UNRIVALED_CRM_STORE, "
                 "or write the store path into ~/.unrivaled-crm-store")
    STORE_DIR = Path(args.store).resolve()
    server.STORE = server.Store(STORE_DIR)
    url = f"http://127.0.0.1:{args.port}/"
    # BIND FIRST. This printed the banner and opened the browser and only then
    # bound: with an older app still on the port, the browser landed on the
    # OLD app under a banner naming the new version, and it looked like a
    # clean start (0.1.44). Nothing is printed or opened until the port is ours.
    try:
        httpd = Server(("127.0.0.1", args.port), Handler)
    except OSError as e:
        kind, version = probe_holder(args.port)
        if kind == "crm":
            sys.exit(f"Another CRM app{f' (v{version})' if version else ''} is already "
                     f"running on port {args.port}. Close its window, then start this "
                     f"one again.")
        sys.exit(f"Port {args.port} is in use by another program ({e}). Close that "
                 f"program, or start the CRM app on another port with --port.")
    print(f"[local-server] CRM v{server.SERVER_VERSION} store={STORE_DIR}", file=sys.stderr)
    print(f"[local-server] {url}", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

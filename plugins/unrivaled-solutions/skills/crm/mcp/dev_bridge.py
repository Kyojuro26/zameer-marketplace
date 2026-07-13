#!/usr/bin/env python3
"""Dev-only HTTP bridge over the Unrivaled CRM MCP.

Exposes the exact same v0.1 tools as plain HTTP so the interactive view can be
developed and end-to-end tested in a browser before the plugin (and its real
MCP wiring via window.cowork.callMcpTool) is installed. NOT part of the
shipped product — the production view talks to the MCP directly.

    python3 dev_bridge.py --store ../store --port 8765

    POST /call   {"tool": "update_project", "args": {...}}  -> tool result JSON
    GET  /health -> {"ok": true, ...crm_info}
"""

import argparse
import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402


def call_tool(tool, args):
    async def _run():
        res = await server.mcp.call_tool(tool, args or {})
        blocks = res[0] if isinstance(res, tuple) else res
        return json.loads(blocks[0].text)
    return asyncio.run(_run())


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # dev bridge only: allow file:// pages to call it
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        if self.path == "/health":
            self._send(200, call_tool("crm_info", {}))
        else:
            self._send(404, {"ok": False, "error": "use POST /call or GET /health"})

    def do_POST(self):
        if self.path != "/call":
            return self._send(404, {"ok": False, "error": "POST /call only"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            tool = req.get("tool")
            if not tool:
                return self._send(400, {"ok": False, "error": "missing 'tool'"})
            self._send(200, call_tool(tool, req.get("args") or {}))
        except Exception as e:  # dev tool: report, don't crash
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, fmt, *args):
        print(f"[bridge] {args[0]} {args[1]}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("UNRIVALED_CRM_STORE"))
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not args.store:
        sys.exit("no store: set UNRIVALED_CRM_STORE or pass --store")
    server.STORE = server.Store(Path(args.store).resolve())
    print(f"[bridge] CRM v{server.VERSION} store={server.STORE.root} "
          f"http://127.0.0.1:{args.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

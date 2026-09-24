"""The desktop app never opens a browser onto something it isn't serving (0.1.44 H1).

local_server.py printed its version banner and opened the browser, and only
then tried to bind the port. With an older app still running on 8765 the new
one printed "CRM v0.1.43", opened the browser onto the OLD app, and then
failed to bind -- it looked like a clean start of the new version. Asserted:

  * on an occupied port the second instance exits non-zero, never opens the
    browser, never prints the banner, and says what holds the port: another
    CRM app, naming its version (read from the running app itself, which works
    for apps older than this release too), or another program;
  * a clean start binds, then prints the banner, then opens the browser, and
    serves the app.

webbrowser.open is stubbed in the child process to print a marker. Fixture
names are invented.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company  # noqa: E402

OPENED = "BROWSER-OPENED"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _launch(crm, store, port):
    """local_server.py in a child process, webbrowser.open stubbed."""
    code = ("import sys, runpy, webbrowser\n"
            f"webbrowser.open = lambda *a, **k: print({OPENED!r}, flush=True) or True\n"
            f"sys.argv = ['local_server.py', '--store', {str(store)!r}, '--port', '{port}']\n"
            f"runpy.run_path({str(Path(crm) / 'mcp' / 'local_server.py')!r}, run_name='__main__')\n")
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _wait_up(port, secs=20):
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            return True
        except Exception:                                        # noqa: BLE001
            time.sleep(0.2)
    return False


def _second(crm, store, port, secs=60):
    p = _launch(crm, store, port)
    try:
        out, err = p.communicate(timeout=secs)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return None, out, err
    return p.returncode, out, err


class _OldApp(BaseHTTPRequestHandler):
    """An app from before this release: the page and /health, no version route."""
    def do_GET(self):
        if self.path == "/":
            body = (b"<html><head><title>Unrivaled CRM</title></head><body><script>"
                    b"const BRIDGE_TOKEN = 'old-token';</script></body></html>")
            ctype = "text/html"
        elif self.path == "/health" and self.headers.get("X-Bridge-Token") == "old-token":
            body, ctype = json.dumps({"ok": True, "server_version": "0.1.36"}).encode(), "application/json"
        else:
            body, ctype = b'{"ok": false}', "application/json"
            self.send_response(404)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Other(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><title>Something else</title></html>")

    def log_message(self, *a):
        pass


def _serve(handler):
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def run(server, crm_dir=None):
    r = Result("local-server", since="0.1.44")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    tmp = Path(tempfile.mkdtemp(prefix="crm-ls-"))
    s = Store(srv, tmp / "store")
    s.reset(companies=[company("acme", "Ace Manufacturing")])
    version = getattr(srv, "SERVER_VERSION", "")

    # 1. a clean start: bind, then banner, then browser; and it serves
    port = _free_port()
    first = _launch(crm, s.path, port)
    up = _wait_up(port)
    r.check("a clean start serves the app", up)

    # 2. a second instance on the same port
    rc, out, err = _second(crm, s.path, port)
    r.check("a second instance on an occupied port exits non-zero", rc not in (0, None), f"rc={rc}")
    r.check("... never opens the browser", OPENED not in out, out[-200:])
    r.check("... never prints the start-up banner", "CRM v" not in err, err[-300:])
    r.check("... and names the CRM app already running, and its version",
            f"Another CRM app (v{version}) is already running on port {port}" in err, err[-300:])
    r.check("... telling the operator what to do", "Close its window, then start this one again" in err, err[-300:])

    first.terminate()
    try:
        fout, ferr = first.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        first.kill()
        fout, ferr = first.communicate()
    r.check("the clean start opened the browser once", fout.count(OPENED) == 1, fout[-200:])
    r.check("... printed its banner", f"CRM v{version}" in ferr, ferr[-300:])

    # 3. an app from before this release: its version is read from the app itself
    httpd, port = _serve(_OldApp)
    try:
        rc, out, err = _second(crm, s.path, port)
    finally:
        httpd.shutdown()
    r.check("an older CRM app on the port is named with its own version",
            rc not in (0, None) and "Another CRM app (v0.1.36) is already running" in err
            and OPENED not in out, (err + out)[-300:])

    # 4. something else on the port
    httpd, port = _serve(_Other)
    try:
        rc, out, err = _second(crm, s.path, port)
    finally:
        httpd.shutdown()
    r.check("a port held by another program says so, and opens nothing",
            rc not in (0, None) and "in use by another program" in err and "Another CRM app" not in err
            and OPENED not in out, (err + out)[-300:])

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return r

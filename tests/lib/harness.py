"""Shared harness for the Unrivaled CRM suite.

Two rules this file exists to enforce, both learned the hard way:

1. A test must be able to FAIL. The suite that shipped before this one scored
   59/59 on a tree with ~40 known defects and 59/59 after they were fixed --
   it could not distinguish them, so its green run meant nothing. Every
   regression test here records the version it was derived from, and
   `run_all.py --positive-control` re-runs the whole suite against that older
   code and requires the relevant tests to FAIL there.

2. Tests drive the REAL dispatch path -- `server.mcp.call_tool` -- not the
   Python functions underneath it. Several real defects lived in argument
   validation ahead of the function body (a `str = None` annotation rejecting
   an explicit null), which a direct call cannot see.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ENTITIES = ("companies", "contacts", "projects", "shipments",
            "vendors", "needs_review", "invoices")


def load_server(crm_dir):
    """Import server.py from a given CRM skill directory.

    Takes the path so --positive-control can point it at an older checkout.
    """
    mcp_dir = str(Path(crm_dir) / "mcp")
    for m in [k for k in sys.modules if k in ("server", "graph")]:
        del sys.modules[m]
    sys.path.insert(0, mcp_dir)
    try:
        import server
        return server
    finally:
        sys.path.remove(mcp_dir)


class Store:
    """A scratch store plus the tool-call plumbing."""

    def __init__(self, server, path=None):
        self.server = server
        self.path = Path(path or tempfile.mkdtemp(prefix="crmtest-"))
        self.reset()

    def reset(self, **files):
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True, exist_ok=True)
        for e in ENTITIES:
            (self.path / f"{e}.json").write_text("[]")
        for name, value in files.items():
            self.write(name, value)
        self.rebind()
        return self

    def rebind(self):
        """Point the server at this store. Required after a raw file write --
        Store caches nothing, but a fresh instance also re-runs its startup
        checks, which is what a real relaunch does."""
        self.server.STORE = self.server.Store(self.path)

    def write(self, entity, value):
        (self.path / f"{entity}.json").write_text(json.dumps(value, indent=2))
        self.rebind()

    def read(self, entity):
        p = self.path / f"{entity}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def raw(self, entity):
        p = self.path / f"{entity}.json"
        return p.read_text() if p.exists() else None

    def call(self, tool, **args):
        """Invoke through the real MCP dispatch.

        A raw exception is returned as {"_raised": ...} rather than propagated,
        because "a tool raised instead of returning {ok:false}" is itself a
        defect this suite asserts against, not a harness failure.
        """
        try:
            res = asyncio.run(self.server.mcp.call_tool(tool, args))
        except Exception as e:                      # noqa: BLE001 -- see above
            return {"_raised": f"{type(e).__name__}: {e}"}
        if isinstance(res, tuple):
            content = res[0]
            structured = res[1] if len(res) > 1 else None
            if isinstance(structured, dict):
                return structured.get("result", structured)
        else:
            content = res
        for c in content:
            txt = getattr(c, "text", None)
            if txt:
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    return {"_raw": txt}
        return {}


# --------------------------------------------------------------- fixtures ---
# Deliberately generic names. This repo is PUBLIC and the whole tree is swept
# for client-identifying content; a fixture must never carry a real name.

def company(cid="acme", name="Ace Manufacturing", role="customer", **kw):
    r = {"company_id": cid, "display_name": name, "role": role,
         "domains": [], "locations": [], "archived": False}
    r.update(kw)
    return r


def project(pno="4521", cid="acme", **kw):
    r = {"company_id": cid, "project_no": pno, "status": "won",
         "archived": False, "owner": [], "annotations": [], "po_flag": False}
    r.update(kw)
    return r


def invoice(no="9001", cid="acme", **kw):
    r = {"invoice_no": no, "company_id": cid, "payment_status": "open"}
    r.update(kw)
    return r


def shipment(sid="4521-L1", pno="4521", cid="acme", **kw):
    r = {"shipment_id": sid, "company_id": cid, "project_no": pno,
         "all_project_nos": [pno], "stage": "Ordered",
         "linked_to_project": True}
    r.update(kw)
    return r


# ------------------------------------------------------------------ report --

class Result:
    """Collects checks for one test module."""

    def __init__(self, name, since=None):
        self.name = name
        self.since = since          # version the defect was found in
        self.passed, self.failed = [], []

    def check(self, label, cond, detail=""):
        if cond:
            self.passed.append(label)
        else:
            self.failed.append((label, detail))
        return bool(cond)

    def section(self, title):
        if os.environ.get("CRM_TEST_VERBOSE"):
            print(f"  -- {title}")

    def report(self):
        ok = not self.failed
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {self.name}  ({len(self.passed)} checks)")
        for label, detail in self.failed:
            print(f"        x {label}" + (f"  --  {detail}" if detail else ""))
        return ok

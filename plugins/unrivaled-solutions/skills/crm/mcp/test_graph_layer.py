#!/usr/bin/env python3
"""Mocked verification of the Phase 5 Graph write layer.

Runs the graph module and the two Outlook MCP tools against a fake HTTP
transport (no network). Asserts payload correctness, idempotency (PATCH not
POST for existing contacts; no duplicate categories), dry-run purity, the
never-delete guardrail, and changelog coverage.

Usage: python3 test_graph_layer.py /path/to/real/store
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import graph  # noqa: E402
import server  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{detail}]"))


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeHttp:
    """Requests-like transport with scripted responses + a call journal."""

    def __init__(self):
        self.calls = []           # (method, path, json_body)
        self.contacts = []        # existing Outlook contacts
        self.categories = []      # existing master categories

    def request(self, method, url, headers=None, json=None, **kw):
        path = url.replace(graph.GRAPH, "")
        self.calls.append((method.upper(), path, json))
        if method == "GET" and path.startswith("/me/contacts?"):
            email = path.split("eq '")[1].split("'")[0]
            hits = [c for c in self.contacts
                    if c["emailAddresses"][0]["address"] == email]
            return FakeResponse({"value": hits})
        if method == "GET" and "/masterCategories" in path:
            return FakeResponse({"value": self.categories})
        if method == "POST" and "/masterCategories" in path:
            cat = dict(json, id=f"cat-{len(self.categories)}")
            self.categories.append(cat)
            return FakeResponse(cat, 201)
        if method == "POST" and path == "/me/contacts":
            c = dict(json, id=f"ct-{len(self.contacts)}")
            self.contacts.append(c)
            return FakeResponse(c, 201)
        if method == "PATCH" and path.startswith("/me/contacts/"):
            cid = path.rsplit("/", 1)[1]
            for c in self.contacts:
                if c["id"] == cid:
                    c.update(json)
            return FakeResponse({"id": cid})
        if method == "POST" and path == "/me/messages":
            return FakeResponse(dict(json, id="draft-1", isDraft=True,
                                     webLink="https://outlook.example/draft-1"), 201)
        if method == "GET" and path.startswith("/me?"):
            return FakeResponse({"userPrincipalName": "test@sandbox"})
        return FakeResponse({"error": f"unscripted {method} {path}"}, 500)


async def call(tool, args):
    res = await server.mcp.call_tool(tool, args)
    blocks = res[0] if isinstance(res, tuple) else res
    return json.loads(blocks[0].text)


def main(src):
    tmp = Path(tempfile.mkdtemp()) / "store"
    shutil.copytree(src, tmp)
    server.STORE = server.Store(tmp)

    print("== graph module (fake transport) ==")
    http = FakeHttp()
    client = graph.GraphClient(lambda: "tok", http=http)

    r = client.ensure_category("CRM: Won", "preset4")
    check("category created when missing", r["created"])
    r = client.ensure_category("CRM: Won", "preset4")
    check("category idempotent (no dup)", not r["created"]
          and sum(1 for c in http.categories if c["displayName"] == "CRM: Won") == 1)

    r = client.upsert_contact(email="a@x.com", name="Ann Xu", company="XCo",
                              title="Buyer", add_categories=["CRM: Won"])
    check("new contact -> POST", r["op"] == "post")
    # simulate a pre-existing manual category on the contact
    http.contacts[0]["categories"] = ["CRM: Won", "Golf Buddies"]
    r = client.upsert_contact(email="a@x.com", name="Ann Xu", company="XCo",
                              add_categories=["CRM: Pending"])
    check("existing contact -> PATCH", r["op"] == "patch")
    check("categories merged, non-CRM preserved",
          set(r["categories"]) == {"CRM: Won", "CRM: Pending", "Golf Buddies"},
          str(r["categories"]))

    d = client.create_draft(to_email="a@x.com", subject="s", body="b")
    check("draft created with webLink", d["isDraft"] and d["webLink"])
    draft_call = [c for c in http.calls if c[1] == "/me/messages"][0]
    check("draft payload is Text + recipient",
          draft_call[2]["body"]["contentType"] == "Text"
          and draft_call[2]["toRecipients"][0]["emailAddress"]["address"] == "a@x.com")

    try:
        client._call("DELETE", "/me/contacts/ct-0")
        check("DELETE guardrail", False)
    except graph.GraphError:
        check("DELETE guardrail raises", True)
    check("no DELETE ever hit the wire",
          not any(m == "DELETE" for m, _, _ in http.calls))

    print("== MCP tools (patched client) ==")
    http2 = FakeHttp()
    client2 = graph.GraphClient(lambda: "tok", http=http2)
    server._graph = lambda: (graph, client2)

    async def tools():
        r = await call("draft_email", {"contact_email": "jhaysley@ford.com"})
        check("draft_email ok + webLink", r["ok"] and r["draft"]["webLink"])
        check("draft_email default greeting uses first name",
              "Hi Jeff" in [c for c in http2.calls if c[1] == "/me/messages"][0][2]["body"]["content"])
        r = await call("draft_email", {"contact_email": "nobody@nowhere.com"})
        check("draft_email unknown contact rejected", not r["ok"])

        n0 = len(http2.calls)
        r = await call("sync_outlook", {"company_id": "ford", "dry_run": True})
        check("dry_run returns plan", r["ok"] and r["dry_run"] and r["plan"]["contacts"])
        check("dry_run makes zero Graph calls", len(http2.calls) == n0)

        r = await call("sync_outlook", {"company_id": "ford"})
        check("sync_outlook ok", r["ok"], json.dumps(r)[:200])
        ops1 = [x["op"] for x in r["results"]]
        r2 = await call("sync_outlook", {"company_id": "ford"})
        ops2 = [x["op"] for x in r2["results"]]
        check("first sync posts, re-sync patches (idempotent)",
              "post" in ops1 and all(o == "patch" for o in ops2), f"{ops1} -> {ops2}")
        cats = [c["displayName"] for c in http2.categories]
        check("no duplicate categories after re-sync", len(cats) == len(set(cats)), str(cats))
        r = await call("sync_outlook", {"company_id": "no-such-co"})
        check("sync unknown company rejected", not r["ok"])

    asyncio.run(tools())

    log = [json.loads(l) for l in open(tmp / "changelog.jsonl")]
    check("changelog: outlook_draft + outlook_sync recorded",
          any(e["op"] == "outlook_draft" for e in log)
          and sum(1 for e in log if e["op"] == "outlook_sync") == 2)

    print("== unconfigured gate ==")
    server._graph = _orig_graph
    import os
    for k in ("GRAPH_CLIENT_ID", "GRAPH_TENANT_ID"):
        os.environ.pop(k, None)

    async def gate():
        r = await call("draft_email", {"contact_email": "jhaysley@ford.com"})
        check("unconfigured -> clear fallback error",
              not r["ok"] and "compose link" in r["error"], r.get("error", ""))
    asyncio.run(gate())

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    _orig_graph = server._graph
    main(sys.argv[1])

#!/usr/bin/env python3
"""LIVE smoke test of the Phase 5 Outlook layer — run on a machine that can
reach login.microsoftonline.com (your Mac), signed into the SANDBOX tenant.

Exercises the real MCP tools (draft_email, sync_outlook) end-to-end against
a SCRATCH COPY of the store and the live sandbox mailbox, then cleans up
everything it created (cleanup happens here in the smoke harness; the CRM
module itself still cannot delete).

    export GRAPH_CLIENT_ID="3f62025a-a4bc-44d9-9a04-5e385f6c42d9"
    export GRAPH_TENANT_ID="4c632251-0471-42df-9929-f3a48baf109a"
    python3 graph_layer_smoke.py            # from build/.../crm/mcp/

First run triggers a one-time device-code sign-in; the token cache lands in
the scratch store and is deleted with it.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import graph  # noqa: E402
import server  # noqa: E402

TAG = "SMOKE-DELETE-ME"
GRAPH = graph.GRAPH


async def call(tool, args):
    res = await server.mcp.call_tool(tool, args)
    blocks = res[0] if isinstance(res, tuple) else res
    return json.loads(blocks[0].text)


def main():
    ok = True
    tmpdir = Path(tempfile.mkdtemp())
    store = tmpdir / "store"
    shutil.copytree(Path(__file__).parent / ".." / "store", store)
    server.STORE = server.Store(store.resolve())

    # interactive sign-in (device code) into the scratch cache
    auth, client = graph.from_env(store)
    try:
        client.me()
        print("[ok] using cached sign-in")
    except graph.GraphError:
        auth.login_device_flow(lambda m: print("\n" + "=" * 70 + f"\n{m}\n" + "=" * 70))
    me = client.me()
    print(f"[ok] signed in as {me.get('userPrincipalName')}")

    # plant a tagged test contact in the scratch store (never the real one)
    contacts = server.STORE.load("contacts")
    contacts.append({"company_id": "ford", "company_name": "Ford",
                     "name": f"Smoke Test {TAG}", "email": "smoke.test@example.com",
                     "phone": None, "title": "QA", "location": None,
                     "action_notes": None, "last_action": None})
    server.STORE.save("contacts", contacts)

    created_drafts, created_contacts, created_cats = [], [], []
    tok = lambda: auth.token_silent()  # noqa: E731
    H = lambda: {"Authorization": f"Bearer {tok()}"}  # noqa: E731

    try:
        # 1) draft_email through the real MCP tool
        r = asyncio.run(call("draft_email", {
            "contact_email": "smoke.test@example.com",
            "subject": f"CRM draft test ({TAG})"}))
        print(f"[{'ok' if r['ok'] else 'ERR'}] draft_email -> "
              f"webLink={'yes' if r.get('draft', {}).get('webLink') else 'no'}")
        ok &= r["ok"]
        if r["ok"]:
            created_drafts.append(r["draft"]["id"])

        # 2) sync_outlook (dry run, then real, then re-run for idempotency)
        r = asyncio.run(call("sync_outlook", {"company_id": "ford", "dry_run": True}))
        print(f"[{'ok' if r['ok'] else 'ERR'}] sync dry_run plan: "
              f"{len(r.get('plan', {}).get('contacts', []))} contacts, "
              f"categories {r.get('plan', {}).get('categories')}")
        ok &= r["ok"]

        r1 = asyncio.run(call("sync_outlook", {"company_id": "ford"}))
        r2 = asyncio.run(call("sync_outlook", {"company_id": "ford"}))
        idem = (r1["ok"] and r2["ok"]
                and all(x["op"] == "patch" for x in r2["results"]))
        print(f"[{'ok' if idem else 'ERR'}] sync twice -> second pass all PATCH "
              f"(no duplicates): {[x['op'] for x in r1['results']]} -> "
              f"{[x['op'] for x in r2['results']]}")
        ok &= idem
        # track what we made, for cleanup
        for x in r1["results"]:
            c = client.find_contact_by_email(x["email"])
            if c and (x["op"] == "post" or TAG in (c.get("displayName") or "")):
                created_contacts.append(c["id"])
        for cat in client.list_categories():
            if cat["displayName"].startswith("CRM: "):
                created_cats.append((cat["id"], cat["displayName"]))

        # 3) verify the draft really exists in the mailbox
        if created_drafts:
            g = requests.get(f"{GRAPH}/me/messages/{created_drafts[0]}"
                             "?$select=isDraft,subject", headers=H())
            is_draft = g.ok and g.json().get("isDraft")
            print(f"[{'ok' if is_draft else 'ERR'}] draft verified in mailbox "
                  f"(isDraft={g.json().get('isDraft')})")
            ok &= bool(is_draft)

    finally:
        print("\nCleaning up (smoke harness only — the CRM module cannot delete)...")
        for d in created_drafts:
            requests.delete(f"{GRAPH}/me/messages/{d}", headers=H())
        for c in set(created_contacts):
            requests.delete(f"{GRAPH}/me/contacts/{c}", headers=H())
        for cid, name in created_cats:
            requests.delete(f"{GRAPH}/me/outlook/masterCategories/{cid}", headers=H())
            print(f"  removed category '{name}'")
        shutil.rmtree(tmpdir, ignore_errors=True)
        print("  scratch store + token cache removed")

    print("\n" + ("RESULT: PHASE 5 LIVE SMOKE PASSED ✅" if ok
                  else "RESULT: SMOKE HIT ERRORS ❌"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

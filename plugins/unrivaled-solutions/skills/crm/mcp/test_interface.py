#!/usr/bin/env python3
"""Verification suite for the Unrivaled CRM MCP v0.1.

Runs every tool through FastMCP's own call path (not direct function calls)
against a scratch copy of the store. Asserts: round-trips persist, validation
rejects bad input, referential integrity holds store-wide, counts reconcile,
needs_review survives writes, and the changelog records every mutation.

Usage: python3 test_interface.py /path/to/real/store
(The real store is copied to a temp dir; it is never mutated.)
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


async def call(tool, args=None):
    res = await server.mcp.call_tool(tool, args or {})
    blocks = res[0] if isinstance(res, tuple) else res
    return json.loads(blocks[0].text)


async def main(src):
    tmp = Path(tempfile.mkdtemp()) / "store"
    shutil.copytree(src, tmp)
    server.STORE = server.Store(tmp)
    orig = {e: len(server.STORE.load(e)) for e in server.ENTITY_FILES}
    n_log0 = sum(1 for _ in open(tmp / "changelog.jsonl")) if (tmp / "changelog.jsonl").exists() else 0

    print("== reads ==")
    info = await call("crm_info")
    check("crm_info counts match files", info["counts"] == orig)
    check("version pinned 0.1", info["interface_version"] == "0.1")

    comps = await call("list_companies")
    check("list_companies full", comps["count"] == orig["companies"])
    vend = await call("list_companies", {"role": "vendor"})
    check("role filter", vend["count"] == 49, str(vend["count"]))

    byname = await call("get_company", {"ref": "Total Truck Parts"})
    byid = await call("get_company", {"ref": "total-truck-parts"})
    check("get_company by name == by id",
          byname["ok"] and byid["ok"]
          and byname["company"]["company_id"] == byid["company"]["company_id"])
    check("nested projects attached", len(byid["projects"]) >= 1)

    pr = await call("get_project", {"project_no": "1338"})
    check("get_project joins company", pr["ok"] and pr["company"]["company_id"] == "total-truck-parts")

    won = await call("list_projects", {"status": "won"})
    check("status filter", won["count"] == 132, str(won["count"]))
    n_shipped = sum(1 for s in server.STORE.load("shipments") if s.get("stage") == "Shipped")
    shipped = await call("list_shipments", {"stage": "Shipped"})
    check("stage filter", shipped["count"] == n_shipped and n_shipped > 0,
          f"{shipped['count']} vs {n_shipped}")
    v = await call("get_vendor", {"ref": "Hallowell"})
    check("get_vendor by name", v["ok"] and v["vendor"]["company_id"] == "hallowell")
    fc = await call("find_contacts", {"company": "ford"})
    check("find_contacts by company", fc["ok"] and fc["count"] >= 1)

    print("== writes round-trip ==")
    r = await call("update_project", {"project_no": "1338", "fields": {"status": "pending", "notes": "verif-test"}})
    check("update_project ok", r["ok"])
    back = await call("get_project", {"project_no": "1338"})
    check("update_project persisted",
          back["project"]["status"] == "pending" and back["project"]["notes"] == "verif-test")

    sid = shipped["shipments"][0]["shipment_id"]
    r = await call("update_shipment", {"shipment_id": sid, "fields": {"stage": "Delivered"}})
    back = await call("list_shipments", {"stage": "Delivered"})
    check("update_shipment stage persisted",
          r["ok"] and any(s["shipment_id"] == sid for s in back["shipments"]))

    r = await call("upsert_contact", {"fields": {"company_id": "ford", "name": "Test Person", "email": "tp@ford.com"}})
    check("upsert_contact create", r["ok"] and r["op"] == "create")
    r2 = await call("upsert_contact", {"fields": {"company_id": "ford", "name": "Test Person", "email": "tp@ford.com", "title": "Buyer"}})
    check("upsert_contact idempotent update", r2["ok"] and r2["op"] == "update")
    fc2 = await call("find_contacts", {"query": "tp@ford.com"})
    check("no duplicate contact", fc2["count"] == 1, str(fc2["count"]))

    r = await call("update_company", {"company_id": "ford", "fields": {"primary_location": "Louisville, KY"}})
    check("update_company ok", r["ok"])

    r = await call("create_project", {"fields": {"project_no": "9999", "company_id": "ford", "status": "pending", "description": "verif", "year": 2026}})
    check("create_project ok", r["ok"])
    r = await call("create_shipment", {"project_no": "9999", "fields": {"vendor_po_raw": "PO# TEST"}})
    check("create_shipment auto-id + defaults",
          r["ok"] and r["shipment"]["shipment_id"] == "9999-L1" and r["shipment"]["stage"] == "Ordered")

    print("== validation rejects ==")
    r = await call("update_project", {"project_no": "1338", "fields": {"status": "bogus"}})
    check("bad status rejected", not r["ok"])
    r = await call("update_shipment", {"shipment_id": sid, "fields": {"stage": "Teleported"}})
    check("bad stage rejected", not r["ok"])
    r = await call("update_project", {"project_no": "1338", "fields": {"made_up_field": 1}})
    check("unknown field rejected", not r["ok"])
    r = await call("create_project", {"fields": {"project_no": "9998", "company_id": "no-such-co"}})
    check("missing company rejected", not r["ok"])
    r = await call("create_project", {"fields": {"project_no": "1338", "company_id": "ford"}})
    check("duplicate project_no rejected", not r["ok"])
    r = await call("get_company", {"ref": "zzz-no-such"})
    check("bad ref returns error not crash", not r["ok"])

    print("== integrity sweep (whole store) ==")
    companies = {c["company_id"] for c in server.STORE.load("companies")}
    projects = server.STORE.load("projects")
    shipments = server.STORE.load("shipments")
    contacts = server.STORE.load("contacts")
    nr = server.STORE.load("needs_review")
    flagged_projects = {str(x.get("project_no")) for x in nr}
    flagged_contacts = {x.get("contact_name") for x in nr}
    check("every project -> valid company (or flagged)",
          all(p["company_id"] in companies
              or (p["company_id"] is None and str(p["project_no"]) in flagged_projects)
              for p in projects))
    check("every contact -> valid company (or flagged)",
          all(c["company_id"] in companies
              or (c["company_id"] is None and c["name"] in flagged_contacts)
              for c in contacts))
    pnos = {str(p["project_no"]) for p in projects}
    linked = [s for s in shipments if s.get("linked_to_project")]
    check("every linked shipment -> real project",
          all(str(s["project_no"]) in pnos for s in linked))
    unlinked = sum(1 for s in shipments if not s.get("linked_to_project"))
    print(f"  note: {unlinked} shipments unlinked (expected — vendor-PO keying, per 7/2 Dylan call)")

    print("== enrichment overlay (Phase 4) ==")
    r = await call("set_enrichment", {"company_id": "ford", "data": {
        "last_contact": "2026-06-30",
        "threads": [{"subject": "RE: racking quote", "with": "jhaysley@ford.com",
                     "date": "2026-06-30", "webLink": "https://outlook.example/t1"}],
        "source": "test"}})
    check("set_enrichment ok", r["ok"], json.dumps(r)[:150])
    check("refreshed_at auto-set", bool(r["enrichment"].get("refreshed_at")))
    g = await call("get_company", {"ref": "ford"})
    check("enrichment attached to get_company",
          g.get("enrichment", {}).get("last_contact") == "2026-06-30")
    g2 = await call("get_company", {"ref": "total-truck-parts"})
    check("un-enriched company returns null overlay", g2.get("enrichment") is None)
    r = await call("set_enrichment", {"company_id": "no-such-co", "data": {}})
    check("enrichment unknown company rejected", not r["ok"])
    r = await call("set_enrichment", {"company_id": "ford", "data": {"bogus": 1}})
    check("enrichment unknown field rejected", not r["ok"])
    info2 = await call("crm_info")
    check("crm_info reports enriched_companies", info2["enriched_companies"] >= 1)
    check("core records untouched by enrichment",
          {e: len(server.STORE.load(e)) for e in server.ENTITY_FILES}
          == {**orig, "projects": orig["projects"] + 1,
              "shipments": orig["shipments"] + 1, "contacts": orig["contacts"] + 1})

    print("== invoices (receivables ledger) ==")
    inv = await call("list_invoices", {})
    check("list_invoices returns full ledger", inv["ok"] and inv["count"] == orig["invoices"])
    paid = await call("list_invoices", {"payment_status": "paid"})
    check("payment_status filter", paid["ok"] and 0 < paid["count"] < inv["count"],
          str(paid.get("count")))
    g3 = await call("get_company", {"ref": "Blu Distribution"})
    check("invoices attached to get_company",
          g3["ok"] and len(g3.get("invoices") or []) >= 1)
    check("no bogus shipment legs (audit invariant)",
          not any(str(s.get("vendor_po_raw", "")).startswith("20")
                  for s in server.STORE.load("shipments")))

    print("== counts + needs_review + changelog ==")
    now = {e: len(server.STORE.load(e)) for e in server.ENTITY_FILES}
    check("counts reconcile after writes",
          now["projects"] == orig["projects"] + 1
          and now["shipments"] == orig["shipments"] + 1
          and now["contacts"] == orig["contacts"] + 1
          and now["needs_review"] == orig["needs_review"])
    log = [json.loads(l) for l in open(tmp / "changelog.jsonl")]
    # mutations THIS RUN: update_project, update_shipment, upsert_contact x2,
    # update_company, create_project, create_shipment, set_enrichment = 8
    # (the copied store may carry pre-existing entries; count the delta)
    check("changelog gained all 8 mutations", len(log) - n_log0 == 8,
          f"delta {len(log) - n_log0}")
    check("changelog entries versioned", all(e["interface_version"] == "0.1" for e in log))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

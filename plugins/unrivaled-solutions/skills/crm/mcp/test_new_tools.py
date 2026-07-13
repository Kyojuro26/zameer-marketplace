#!/usr/bin/env python3
"""Verification suite for the add/delete (create + archive) tools added
for Dylan: create_company, create_vendor, update_vendor, archive_company,
restore_company, and archived-filtering across the reads.

Runs through FastMCP's own call path against a scratch copy of the store.
Usage: python3 test_new_tools.py /path/to/real/store
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
    n_log0 = sum(1 for _ in open(tmp / "changelog.jsonl")) if (tmp / "changelog.jsonl").exists() else 0
    base = (await call("list_companies"))["count"]

    print("== create_company (customer) ==")
    r = await call("create_company", {"fields": {"display_name": "Acme Test Co",
                                                  "primary_location": "Louisville, KY"}})
    check("create_company ok", r["ok"] and r["company"]["company_id"] == "acme-test-co")
    check("role defaults customer", r["company"]["role"] == "customer")
    lc = await call("list_companies")
    check("new customer appears in list", lc["count"] == base + 1)
    dup = await call("create_company", {"fields": {"display_name": "Acme Test Co"}})
    check("duplicate name rejected", not dup["ok"] and "already exists" in dup["error"])
    bad = await call("create_company", {"fields": {"display_name": "X Co", "role": "supplier"}})
    check("bad role rejected", not bad["ok"] and "role must be" in bad["error"])
    noname = await call("create_company", {"fields": {"role": "customer"}})
    check("missing display_name rejected", not noname["ok"])

    print("== create_vendor ==")
    rv = await call("create_vendor", {"fields": {"display_name": "Bolt Supply Inc",
        "rep": "Jane Roe", "email": "jane@boltsupply.com", "offerings": "Fasteners",
        "po_routing": "po@boltsupply.com"}})
    cid = rv["vendor"]["company_id"]
    check("create_vendor ok", rv["ok"] and cid == "bolt-supply-inc")
    comp = await call("get_company", {"ref": cid})
    check("vendor company created role=vendor", comp["ok"] and comp["company"]["role"] == "vendor")
    gv = await call("get_vendor", {"ref": "Bolt Supply Inc"})
    check("get_vendor returns detail", gv["ok"] and gv["vendor"]["rep"] == "Jane Roe")
    vlist = await call("list_companies", {"role": "vendor"})
    check("vendor shows in role=vendor list", any(c["company_id"] == cid for c in vlist["companies"]))
    dupv = await call("create_vendor", {"fields": {"display_name": "Bolt Supply Inc"}})
    check("duplicate vendor rejected", not dupv["ok"])

    print("== update_vendor ==")
    uv = await call("update_vendor", {"company_id": cid, "fields": {"phone": "502-555-0199"}})
    check("update_vendor persists", uv["ok"] and uv["vendor"]["phone"] == "502-555-0199")
    gv2 = await call("get_vendor", {"ref": cid})
    check("update_vendor round-trips", gv2["vendor"]["phone"] == "502-555-0199")

    print("== archive (soft-delete) a customer with records ==")
    # pick a real customer that has projects
    victim = "total-truck-parts"
    before_proj = (await call("list_projects"))["count"]
    vproj = len((await call("get_company", {"ref": victim}))["projects"])
    ar = await call("archive_company", {"company_id": victim})
    check("archive ok", ar["ok"] and ar["company"]["archived"] is True and ar["company"]["archived_at"])
    lc2 = await call("list_companies")
    check("archived customer hidden from list", all(c["company_id"] != victim for c in lc2["companies"]))
    lc2i = await call("list_companies", {"include_archived": True})
    check("archived visible with include_archived", any(c["company_id"] == victim for c in lc2i["companies"]))
    lp2 = await call("list_projects")
    check("archived company's projects hidden", lp2["count"] == before_proj - vproj and vproj > 0,
          f"{lp2['count']} vs {before_proj}-{vproj}")
    fc = await call("find_contacts", {"query": ""})
    check("archived company's contacts hidden by default",
          all(x["company_id"] != victim for x in fc["contacts"]))
    gc = await call("get_company", {"ref": victim})
    check("get_company still returns archived (for restore)", gc["ok"] and gc["company"]["archived"])
    check("archived company's records preserved in store (not destroyed)",
          any(p["company_id"] == victim for p in server.STORE.load("projects")))

    print("== archive a vendor mirrors to vendor record ==")
    av = await call("archive_company", {"company_id": cid})
    check("vendor archive ok", av["ok"])
    check("vendor detail record flagged archived",
          all(v.get("archived") for v in server.STORE.load("vendors") if v["company_id"] == cid))
    vlist2 = await call("list_companies", {"role": "vendor"})
    check("archived vendor hidden from vendor list", all(c["company_id"] != cid for c in vlist2["companies"]))

    print("== restore ==")
    rs = await call("restore_company", {"company_id": victim})
    check("restore ok", rs["ok"] and rs["company"]["archived"] is False)
    lc3 = await call("list_companies")
    check("restored customer back in list", any(c["company_id"] == victim for c in lc3["companies"]))
    lp3 = await call("list_projects")
    check("restored company's projects back", lp3["count"] == before_proj)

    print("== crm_info + changelog ==")
    info = await call("crm_info")
    check("crm_info reports archived count", info["archived_companies"] == 1)  # only the vendor still archived
    log = [json.loads(l) for l in open(tmp / "changelog.jsonl")]
    ops = [e["op"] for e in log[n_log0:]]
    check("changelog logged create/archive/restore",
          ops.count("create") == 2 and "archive" in ops and "restore" in ops,
          str(ops))
    check("all new log entries versioned 0.1",
          all(e["interface_version"] == "0.1" for e in log[n_log0:]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "./store"))

"""A project is (project_no, company_id), and the tools can now say so.

Two project records can hold one project_no -- the legacy-duplicate case
_one_project's docstring describes, and the reason the metrics layer keys
projects by (project_no, company_id). Until now every project tool took the
number alone: _one_project correctly REFUSED the ambiguous number, so neither
record could be edited, renamed, archived or restored by any tool at all.

The trailing optional `company_id` narrows the number to one customer's
project BEFORE the ambiguity test. Four things are asserted, each with an
obvious wrong version:

 1. NUMBER-ONLY IS UNCHANGED. Without company_id the ambiguous number is still
    refused with the same message. Backward compatibility is the whole
    contract; a call that used to be refused must not start picking one.
 2. THE OTHER CUSTOMER'S RECORD IS UNTOUCHED, byte for byte. An edit, rename,
    archive or restore scoped to Acme leaves Beta's twin exactly as stored --
    and the rename cascade carries only Acme's shipments and invoices.
 3. A CUSTOMER THAT DOES NOT HOLD THE NUMBER GETS "NOT FOUND", never the other
    customer's record. Filtering AFTER the ambiguity test, or falling back to
    the number-only match when the filter is empty, both give a plausible
    answer that is the wrong record.
 4. A TRUE DUPLICATE STILL REFUSES: the same customer holding one number
    twice cannot be told apart by company_id either.

Driven through server.mcp.call_tool, never the Python functions: an explicit
null and an omitted argument must both reach the tool, and that is decided in
the argument layer ahead of the function body.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice, shipment  # noqa: E402


def seed(s):
    """Acme and Beta both hold 4521, each with its own leg and invoice."""
    s.reset(
        companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
        projects=[project("4521", "acme", description="Acme's job", revenue=1000),
                  project("4521", "beta", description="Beta's job", revenue=2000),
                  project("4600", "acme", description="Acme's other job")],
        shipments=[shipment("4521-L1", "4521", "acme", vendor_po_raw="VPO-A"),
                   shipment("4521-L2", "4521", "beta", vendor_po_raw="VPO-B")],
        invoices=[invoice("7001", "acme", project_no="4521"),
                  invoice("7002", "beta", project_no="4521")])


def rec(s, cid, pno="4521"):
    return next((p for p in s.read("projects")
                 if p.get("company_id") == cid and str(p.get("project_no")) == pno), None)


def field(s, cid, key, pno="4521"):
    """A field of that record, or None when the record is gone. A server that
    renamed one of two twins at random (0.1.26 did) leaves no record here, and
    that must read as a red check, not a crash the runner cannot score."""
    p = rec(s, cid, pno)
    return p.get(key) if p else None


def run(server, crm_dir=None):
    r = Result("project-identity", since="0.1.37")
    srv = server
    if srv is None:
        from lib.harness import load_server
        crm = crm_dir or str(Path(__file__).resolve().parents[2]
                             / "plugins/unrivaled-solutions/skills/crm")
        srv = load_server(str(crm))
    s = Store(srv)
    AMBIG = "share the number"

    # ---- 1. number-only is exactly as before ----------------------------------
    r.section("number-only calls still refuse the ambiguous number")
    seed(s)
    for tool, args in (("get_project", {"project_no": "4521"}),
                       ("update_project", {"project_no": "4521", "fields": {"notes": "x"}}),
                       ("rename_project", {"old_project_no": "4521", "new_project_no": "4599"}),
                       ("archive_project", {"project_no": "4521"}),
                       ("restore_project", {"project_no": "4521"}),
                       ("create_shipment", {"project_no": "4521", "fields": {"vendor_po_raw": "X"}})):
        res = s.call(tool, **args)
        r.check(f"{tool} without company_id still refuses the shared number",
                res.get("ok") is False and AMBIG in str(res.get("error")), json.dumps(res)[:200])
    r.check("and nothing was written by any of them",
            field(s, "acme", "description") == "Acme's job" and field(s, "beta", "description") == "Beta's job"
            and not field(s, "acme", "archived") and len(s.read("shipments")) == 2)
    res = s.call("get_project", project_no="4521", company_id=None)
    r.check("an explicit null company_id behaves as an omitted one",
            res.get("ok") is False and AMBIG in str(res.get("error")), json.dumps(res)[:200])

    # ---- 2. scoped to one customer: the other's record is byte-identical ------
    r.section("company_id narrows to one customer's project")
    seed(s)
    beta_before = copy.deepcopy(rec(s, "beta"))
    res = s.call("get_project", project_no="4521", company_id="acme")
    r.check("get_project with company_id returns that customer's project",
            res.get("ok") and res["project"]["company_id"] == "acme"
            and res["project"]["description"] == "Acme's job", json.dumps(res)[:200])
    r.check("and lists only that customer's legs on the number",
            res.get("ok") and [x["shipment_id"] for x in res["shipments"]] == ["4521-L1"],
            json.dumps(res.get("shipments"))[:200])
    res = s.call("update_project", project_no="4521", fields={"notes": "edited"}, company_id="acme")
    r.check("update_project with company_id edits that customer's project",
            res.get("ok") and field(s, "acme", "notes") == "edited", json.dumps(res)[:200])
    r.check("and leaves the other customer's twin byte-identical",
            rec(s, "beta") == beta_before, json.dumps(rec(s, "beta"))[:200])
    res = s.call("archive_project", project_no="4521", company_id="acme")
    r.check("archive_project with company_id archives that customer's project",
            res.get("ok") and field(s, "acme", "archived") is True, json.dumps(res)[:200])
    r.check("and not the other customer's",
            not field(s, "beta", "archived") and rec(s, "beta") == beta_before)
    res = s.call("restore_project", project_no="4521", company_id="acme")
    r.check("restore_project with company_id restores it",
            res.get("ok") and field(s, "acme", "archived") is False, json.dumps(res)[:200])
    r.check("still leaving the other customer's twin byte-identical", rec(s, "beta") == beta_before)
    res = s.call("create_shipment", project_no="4521", fields={"vendor_po_raw": "VPO-A2"}, company_id="acme")
    r.check("create_shipment with company_id files the leg under that customer",
            res.get("ok") and res["shipment"]["company_id"] == "acme"
            and str(res["shipment"]["project_no"]) == "4521", json.dumps(res)[:200])

    # ---- 2b. the rename cascade carries only that customer's records ---------
    r.section("rename with company_id cascades within that customer only")
    seed(s)
    beta_before = copy.deepcopy(rec(s, "beta"))
    res = s.call("rename_project", old_project_no="4521", new_project_no="4522", company_id="acme")
    r.check("rename_project with company_id renames that customer's project",
            res.get("ok") and rec(s, "acme", "4522") is not None and rec(s, "acme") is None,
            json.dumps(res)[:200])
    r.check("the other customer keeps its number and its record",
            rec(s, "beta") == beta_before, json.dumps(rec(s, "beta"))[:200])
    ships = {x["shipment_id"]: x for x in s.read("shipments")}
    r.check("only that customer's leg moved to the new number",
            str(ships["4521-L1"]["project_no"]) == "4522" and ships["4521-L1"]["all_project_nos"] == ["4522"]
            and str(ships["4521-L2"]["project_no"]) == "4521" and ships["4521-L2"]["all_project_nos"] == ["4521"],
            json.dumps(ships)[:300])
    invs = {x["invoice_no"]: x for x in s.read("invoices")}
    r.check("and only that customer's invoice",
            str(invs["7001"]["project_no"]) == "4522" and str(invs["7002"]["project_no"]) == "4521",
            json.dumps(invs)[:300])
    r.check("the cascade counts say one and one",
            res.get("ok") and res.get("shipments_updated") == 1 and res.get("invoices_updated") == 1,
            json.dumps(res)[:200])
    res = s.call("rename_project", old_project_no="4521", new_project_no="4522", company_id="beta")
    r.check("a rename onto a number another customer now holds is still refused",
            res.get("ok") is False and "already exists" in str(res.get("error")), json.dumps(res)[:200])

    # ---- 3. a customer that does not hold the number: not found ---------------
    r.section("a customer that does not hold the number gets not found")
    seed(s)
    s.write("companies", [company("acme", "Ace Manufacturing"), company("beta", "Beta Works"),
                          company("gamma", "Gamma Ltd")])
    for tool, args in (("get_project", {"project_no": "4521"}),
                       ("update_project", {"project_no": "4521", "fields": {"notes": "x"}}),
                       ("rename_project", {"old_project_no": "4521", "new_project_no": "4599"}),
                       ("archive_project", {"project_no": "4521"}),
                       ("create_shipment", {"project_no": "4521", "fields": {"vendor_po_raw": "X"}})):
        res = s.call(tool, company_id="gamma", **args)
        r.check(f"{tool} for a customer without the number says not found, not another customer's record",
                res.get("ok") is False and "not found" in str(res.get("error")), json.dumps(res)[:200])
    r.check("and touched nothing",
            field(s, "acme", "description") == "Acme's job" and field(s, "beta", "description") == "Beta's job"
            and rec(s, "acme", "4599") is None and len(s.read("shipments")) == 2)
    res = s.call("get_project", project_no="4600", company_id="beta")
    r.check("a number only one customer holds, asked for under another customer, is not found",
            res.get("ok") is False and "not found" in str(res.get("error")), json.dumps(res)[:200])
    res = s.call("get_project", project_no="4600", company_id="acme")
    r.check("and under its own customer it is found",
            res.get("ok") and res["project"]["description"] == "Acme's other job", json.dumps(res)[:200])

    # ---- 3b. the key is exact, through _key -----------------------------------
    r.section("company_id is an exact key, through _key")
    seed(s)
    res = s.call("get_project", project_no="4521", company_id=" acme ")
    r.check("a padded company_id reaches the record (trimmed like every id)",
            res.get("ok") and res["project"]["company_id"] == "acme", json.dumps(res)[:200])
    res = s.call("get_project", project_no="4521", company_id="Acme")
    r.check("but a differently cased one does not -- no name matching here",
            res.get("ok") is False and "not found" in str(res.get("error")), json.dumps(res)[:200])

    # ---- 4. a true duplicate still refuses -------------------------------------
    r.section("the same customer holding one number twice still refuses")
    seed(s)
    s.write("projects", s.read("projects") + [project("4521", "acme", description="Acme's twin")])
    for tool, args in (("get_project", {"project_no": "4521"}),
                       ("update_project", {"project_no": "4521", "fields": {"notes": "x"}}),
                       ("archive_project", {"project_no": "4521"})):
        res = s.call(tool, company_id="acme", **args)
        r.check(f"{tool} with company_id still refuses a same-customer duplicate",
                res.get("ok") is False and AMBIG in str(res.get("error")), json.dumps(res)[:200])
    res = s.call("get_project", project_no="4521", company_id="beta")
    r.check("while the other customer's single record is still reachable",
            res.get("ok") and res["project"]["description"] == "Beta's job", json.dumps(res)[:200])
    return r

"""Identifier matching: _key / _canon / _resolve.

Defect class: project_no and invoice_no are lookup keys other records point at,
and they can legitimately arrive as a string, a JSON number, a float, or with
padding. Nineteen comparison sites once used bare str(), so " 4521 " read as
live in one place and archived in another.

The design under test -- MINT uses _canon, LOOK UP uses _resolve, and stored
values are compared with _key (exact) -- deliberately does NOT fold a trailing
".0" on a stored value. Folding both sides made an archived "4521.0" and a live
"4521" the same key and get_company dropped the live project's invoices.

Derived from defects found against v0.1.26 and the unpublished 0.1.27/0.1.28
attempts. --positive-control requires these to fail against v0.1.26.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice, shipment  # noqa: E402


def run(server):
    r = Result("identifiers", since="0.1.26")
    s = Store(server)

    r.section("the collision: an archived '.0' twin must not hide a live project")
    s.reset(companies=[company()],
            projects=[project("4521.0", archived=True), project("4521")],
            invoices=[invoice("9001", project_no="4521")])
    gc = s.call("get_company", ref="Ace Manufacturing")
    r.check("live project's receivable survives an archived '.0' twin",
            [i.get("invoice_no") for i in gc.get("invoices", [])] == ["9001"],
            str(gc.get("invoices")))

    r.section("exact-first resolution: a stored value round-tripped as an argument")
    # the view passes v.invoice_no straight back as the lookup key, so an
    # argument is not necessarily fresh input
    s.reset(companies=[company()],
            invoices=[invoice("7001", payment_notes="A", sheet_row=11),
                      invoice("7001.0", payment_notes="B", sheet_row=12)])
    res = s.call("update_invoice", company_id="acme", invoice_no="7001.0",
                 fields={"payment_status": "paid"})
    r.check("editing '7001.0' touches THAT record, not its twin",
            res.get("invoice", {}).get("sheet_row") == 12,
            f"touched sheet_row={res.get('invoice', {}).get('sheet_row')}")
    on_disk = {str(i["invoice_no"]): i["payment_status"] for i in s.read("invoices")}
    r.check("the twin was left alone", on_disk.get("7001") == "open", str(on_disk))

    r.section("canonical fallback still reaches a store that has no exact match")
    s.reset(companies=[company()], invoices=[invoice("7600")])
    res = s.call("update_invoice", company_id="acme", invoice_no="7600.0",
                 fields={"payment_status": "paid"})
    r.check("typing '7600.0' finds the invoice stored as '7600'",
            res.get("ok") is True, str(res)[:90])

    r.section("no '.0' key can be persisted through any write path")
    s.reset(companies=[company()])
    s.call("create_project", fields={"company_id": "acme", "project_no": "4700.0",
                                     "status": "won"})
    s.call("create_invoice", company_id="acme",
           fields={"invoice_no": "9700.0", "project_no": "4700.0"})
    s.call("create_shipment", project_no="4700.0", fields={"vendor_po_raw": "PO-9"})
    s.call("rename_invoice", company_id="acme", old_invoice_no="9700",
           new_invoice_no="9800.0")
    s.call("reassign_shipment", shipment_id="4700-L1", new_project_no="4700.0")
    keys = ([p["project_no"] for p in s.read("projects")]
            + [i["invoice_no"] for i in s.read("invoices")]
            + [i.get("project_no") for i in s.read("invoices")]
            + [x["project_no"] for x in s.read("shipments")]
            + [n for x in s.read("shipments") for n in (x.get("all_project_nos") or [])])
    r.check("no stored identifier ends in '.0'",
            not any(str(k).endswith(".0") for k in keys if k), str(keys))

    r.section("legacy shapes stay reachable and repairable")
    s.reset(companies=[company()], projects=[project("9000.0")],
            invoices=[invoice("9001", project_no="9000.0")])
    r.check("a '.0' project can be opened",
            s.call("get_project", project_no="9000.0").get("ok") is True)
    r.check("an unchanged '.0' link does not block an unrelated edit",
            s.call("update_invoice", company_id="acme", invoice_no="9001",
                   fields={"payment_status": "paid",
                           "project_no": "9000.0"}).get("ok") is True)
    ren = s.call("rename_project", old_project_no="9000.0", new_project_no="9000")
    r.check("and it is repairable in-app, cascading to its invoice",
            ren.get("ok") is True and s.read("invoices")[0]["project_no"] == "9000",
            str(ren)[:90])

    r.section("numerically-stored keys behave as their string form")
    s.reset(companies=[company()], projects=[project(4521)])
    r.check("create_project refuses a numerically-stored twin",
            s.call("create_project", fields={"company_id": "acme",
                                             "project_no": "4521",
                                             "status": "won"}).get("ok") is False)
    r.check("archive_project reaches a numerically-stored project",
            s.call("archive_project", project_no="4521").get("ok") is True)

    r.section("rename cascades reach padded and numeric links")
    s.reset(companies=[company()], projects=[project("4521")],
            invoices=[invoice("9001", project_no=" 4521 ")],
            shipments=[shipment("4521-L1", " 4521 ",
                                all_project_nos=[" 4521 "])])
    res = s.call("rename_project", old_project_no="4521", new_project_no="4600")
    r.check("padded invoice link cascades",
            res.get("invoices_updated") == 1 and s.read("invoices")[0]["project_no"] == "4600")
    r.check("padded shipment link cascades",
            res.get("shipments_updated") == 1
            and s.read("shipments")[0]["all_project_nos"] == ["4600"])

    r.section("empty lookup keys must never match records with a null identifier")
    s.reset(companies=[company(), company("beta", "Beta Ltd")],
            projects=[project(None)],
            invoices=[invoice("A1", project_no=None),
                      invoice("B1", "beta", project_no=None)])
    before = [(i["company_id"], i["invoice_no"], i["project_no"]) for i in s.read("invoices")]
    s.call("rename_project", old_project_no="", new_project_no="9999")
    r.check("rename_project('') cannot mass-repoint unlinked records",
            [(i["company_id"], i["invoice_no"], i["project_no"])
             for i in s.read("invoices")] == before)
    s.reset(companies=[company()], invoices=[invoice(None)],
            shipments=[{"shipment_id": "Z-L1", "company_id": "acme",
                        "invoice_no": None, "stage": "Ordered"}])
    r.check("rename_invoice('') is refused",
            s.call("rename_invoice", company_id="acme", old_invoice_no="",
                   new_invoice_no="9999").get("ok") is False)
    r.check("update_invoice('') is refused",
            s.call("update_invoice", company_id="acme", invoice_no="",
                   fields={"payment_status": "paid"}).get("ok") is False)
    r.check("the unnumbered invoice was not marked paid",
            s.read("invoices")[0]["payment_status"] == "open")

    r.section("ambiguity is refused, never resolved arbitrarily")
    s.reset(companies=[company()],
            projects=[project("4521", archived=True, description="OLD"),
                      project("4521", description="LIVE")],
            invoices=[invoice("9001", project_no="4521")])
    for tool, args in (("get_project", {"project_no": "4521"}),
                       ("update_project", {"project_no": "4521",
                                           "fields": {"status": "won"}}),
                       ("archive_project", {"project_no": "4521"}),
                       ("rename_project", {"old_project_no": "4521",
                                           "new_project_no": "9999"})):
        res = s.call(tool, **args)
        r.check(f"{tool} refuses a duplicated project number",
                res.get("ok") is False, str(res)[:80])
    r.check("no twin was renamed and no invoice was cascaded",
            [p["project_no"] for p in s.read("projects")] == ["4521", "4521"]
            and s.read("invoices")[0]["project_no"] == "4521")

    r.section("duplicate invoice pairs are refused without writing")
    s.reset(companies=[company()],
            invoices=[invoice("7001", sheet_row=11), invoice(7001.0, sheet_row=12)],
            shipments=[{"shipment_id": "Y-L1", "company_id": "acme",
                        "invoice_no": "7001", "stage": "Ordered"}])
    before_raw = s.raw("invoices")
    r.check("update_invoice refuses a duplicate pair",
            s.call("update_invoice", company_id="acme", invoice_no="7001",
                   fields={"payment_status": "paid"}).get("ok") is False)
    r.check("rename_invoice refuses it too",
            s.call("rename_invoice", company_id="acme", old_invoice_no="7001",
                   new_invoice_no="7002").get("ok") is False)
    r.check("neither refusal wrote anything", s.raw("invoices") == before_raw)
    r.check("no shipment leg was repointed",
            s.read("shipments")[0]["invoice_no"] == "7001")

    r.section("a rename must not steal a leg with a NULL invoice_no")
    s.reset(companies=[company()], invoices=[invoice("None")],
            shipments=[{"shipment_id": "X-L1", "company_id": "acme",
                        "invoice_no": None, "stage": "Ordered"}])
    s.call("rename_invoice", company_id="acme", old_invoice_no="None",
           new_invoice_no="9500")
    r.check("the NULL-numbered leg is untouched",
            s.read("shipments")[0].get("invoice_no") is None)

    return r

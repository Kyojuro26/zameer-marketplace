"""Visibility: what archiving hides, and what it must never hide.

Defect class: every default read drops records whose project or company is
archived. Get the filter wrong and a live receivable silently disappears from
every screen with ok:true -- the single worst outcome in this system, because
nothing signals it.

Includes the store-destroying case: an archived project with a falsy key put ""
into the archived-key set, and since an invoice with no project also keys to "",
EVERY unlinked invoice in the store vanished across all companies. normalize.py
leaves project_no null whenever an invoice has no tracker link, so those are
ordinary records.

Derived from defects found against v0.1.26 and the unpublished attempts.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice, shipment  # noqa: E402


def run(server):
    r = Result("visibility", since="0.1.26")
    s = Store(server)

    r.section("an archived project with a falsy key hides nothing else")
    for bad in (None, "", "   ", True, 0):
        s.reset(companies=[company(), company("beta", "Beta Ltd")],
                projects=[project(bad, archived=True)],
                invoices=[invoice("B1", "beta", project_no=None),
                          invoice("B2", "beta", project_no="")])
        gc = s.call("get_company", ref="Beta Ltd")
        li = s.call("list_invoices")
        r.check(f"unlinked receivables survive an archived project keyed {bad!r}",
                len(gc.get("invoices", [])) == 2 and li.get("count") == 2,
                f"get_company={len(gc.get('invoices', []))} list={li.get('count')}")

    r.section("the same guard on the company side")
    s.reset(companies=[company(None, "Nameless", archived=True),
                       company("beta", "Beta Ltd")],
            invoices=[invoice("B1", "beta"), invoice("B2", "beta")])
    r.check("an archived company with a falsy id hides no other company's invoices",
            s.call("list_invoices").get("count") == 2,
            str(s.call("list_invoices").get("count")))

    r.section("archiving hides a project's own records, and restore brings them back")
    s.reset(companies=[company()], projects=[project("4521")],
            invoices=[invoice("9001", project_no="4521")],
            shipments=[shipment()])
    s.call("archive_project", project_no="4521")
    r.check("archived project's invoice is hidden",
            s.call("list_invoices").get("count") == 0)
    r.check("archived project's shipment is hidden",
            s.call("list_shipments").get("count") == 0)
    s.call("restore_project", project_no="4521")
    r.check("restore brings the invoice back",
            s.call("list_invoices").get("count") == 1)
    r.check("restore brings the shipment back",
            s.call("list_shipments").get("count") == 1)

    r.section("a leg is hidden only when EVERY project it links to is archived")
    s.reset(companies=[company()],
            projects=[project("100"), project("200")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    s.call("reassign_shipment", shipment_id="100-L1", new_project_no="100",
           also_project_nos=["200"])
    s.call("archive_project", project_no="200")
    r.check("archiving a SECONDARY project does not hide the leg",
            s.call("list_shipments").get("count") == 1,
            "a leg its live primary still owns must stay visible")
    s.call("archive_project", project_no="100")
    r.check("archiving the last live link does hide it",
            s.call("list_shipments").get("count") == 0)

    r.section("nothing may be created against an archived company")
    s.reset(companies=[company("ghost", "Ghost Co")])
    s.call("archive_company", company_id="ghost")
    for tool, args, label in (
            ("create_invoice", {"company_id": "ghost",
                                "fields": {"invoice_no": "9500"}}, "invoice"),
            ("create_project", {"fields": {"company_id": "ghost",
                                           "project_no": "5000",
                                           "status": "won"}}, "project"),
            ("upsert_contact", {"fields": {"company_id": "ghost",
                                           "name": "A Person"}}, "contact")):
        res = s.call(tool, **args)
        r.check(f"a {label} cannot be created against an archived company",
                res.get("ok") is False,
                "created ok:true and is invisible in every read")

    r.section("nothing may be linked to an archived project")
    s.reset(companies=[company()],
            projects=[project("4521"), project("9999", archived=True)])
    s.call("create_shipment", project_no="4521", fields={"vendor_po_raw": "PO-1"})
    for tool, args, label in (
            ("create_invoice", {"company_id": "acme",
                                "fields": {"invoice_no": "9001",
                                           "project_no": "9999"}}, "create_invoice"),
            ("create_shipment", {"project_no": "9999", "fields": {}}, "create_shipment"),
            ("reassign_shipment", {"shipment_id": "4521-L1",
                                   "new_project_no": "9999"}, "reassign_shipment"),
            ("update_shipment", {"shipment_id": "4521-L1",
                                 "fields": {"project_no": "9999"}}, "update_shipment")):
        r.check(f"{label} refuses an archived project",
                s.call(tool, **args).get("ok") is False)

    r.section("archived state must be a real boolean, not free text")
    s.reset(companies=[company()], invoices=[invoice("7001")])
    before = s.call("list_invoices").get("count")
    s.call("update_company", company_id="acme", fields={"archived": "no"})
    r.check("a truthy string meaning 'no' cannot hide a customer's receivables",
            s.call("list_invoices").get("count") == before,
            "update_company stored archived='no' and every read treated it as archived")

    return r

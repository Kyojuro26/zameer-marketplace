"""Telling PO, project and invoice numbers apart (0.1.38, B4).

PO numbers, project/quote numbers and invoice numbers share one numeric range
(measured: 43 of 131 QuickBooks PO numbers are also a CRM project number).

Decisions asserted, each with an obvious wrong version:

 1. lookup_number RETURNS EVERY TYPED MATCH, each labelled: project, CRM
    invoice, vendor PO on a shipment leg, QuickBooks invoice, QuickBooks PO,
    QuickBooks bill -- and a bill's Num is flagged as the vendor's own
    invoice number, not a PO. Collapsing "1167" to its first hit is the bug.
 2. A COMPOSITE CRM NUMBER IS ITS INVOICE. "4521 (INV 1191)" answers 1191,
    not 4521 (the quote number). A vendor PO is the number OUTSIDE the leg's
    parentheses: "PO # 1300 (1167 Paid)" is PO 1300, not 1167.
 3. lookup_number IS READ-ONLY.
 4. SETTING project_no TO A NUMBER THAT IS ALSO A VENDOR PO WARNS AND STILL
    WRITES: the response carries number_is_also_vendor_po naming the PO's
    vendor and job; the write is not refused (a number can be both). An
    echoed, unchanged project_no does not warn on every save.

Names and figures are invented.
"""
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)


def seed(server, st):
    st.reset(
        companies=[company("acme", "Ace Manufacturing"),
                   company("cobalt", "Cobalt Freight", role="vendor")],
        vendors=[{"company_id": "cobalt", "display_name": "Cobalt Freight",
                  "archived": False}],
        projects=[project("1167", "acme", revenue=5000),
                  project("4521", "acme", revenue=9000),
                  project("4600", "acme", revenue=1000)],
        invoices=[invoice("1167", "acme", project_no="4600",
                          invoice_date="2026-02-01"),
                  invoice("4521 (INV 1191)", "acme", project_no="4521",
                          invoice_date="2026-02-02")],
        shipments=[shipment("4521-L1", "4521", "acme",
                            vendor_po_raw="PO # 1167 (Cobalt) (PAID)",
                            vendor_id="cobalt"),
                   shipment("4521-L2", "4521", "acme",
                            vendor_po_raw="PO # 1300 (1167 Paid)")])
    server._save_qbo_snapshot("invoices", "export", "2026-04-07", "2026-01-01",
                              "2026-03-31",
                              [{"type": "Invoice", "num": "1167", "date": "2026-02-01",
                                "name": "Ace Manufacturing", "amount_cents": 500000,
                                "open_cents": 0}])
    line = {"date": "2026-01-08", "track_1099": False, "posting": False,
            "memo": None, "account": "Accounts Payable", "split_account": None}
    server._save_qbo_snapshot("vendor_transactions", "export", "2026-04-07",
                              "2026-01-01", "2026-03-31", [
        dict(line, vendor="Cobalt Freight", type="Purchase Order", num="1167",
             amount_cents=120000),
        dict(line, vendor="Cobalt Freight", type="Purchase Order", num="1167",
             amount_cents=30000),
        dict(line, vendor="Trueline Metals", type="Bill", num="1167",
             posting=True, amount_cents=77700),
        dict(line, vendor="Trueline Metals", type="Expense", num="1167",
             posting=True, amount_cents=100)])


def run(server, crm_dir=None):
    r = Result("number-lookup", since="0.1.38")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    has = r.check("tool lookup_number exists",
                  callable(getattr(server, "lookup_number", None)))
    tmp = Path(tempfile.mkdtemp(prefix="qbolook-"))
    try:
        _body(r, server, tmp, has)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _types(got):
    return sorted(m.get("type") for m in got.get("matches") or [])


def _body(r, server, tmp, has):
    st = Store(server, tmp / "m" / "store")
    seed(server, st)
    if has:
        _lookups(r, st)
    _warnings(r, st)


def _lookups(r, st):
    before = {p.name: p.read_bytes() for p in st.path.iterdir()}

    r.section("every typed match, labelled")
    got = st.call("lookup_number", n="1167")
    r.check("1167 answers ok", got.get("ok") is True, got)
    r.check("1167 is six things, each labelled by type",
            _types(got) == sorted(["project", "crm_invoice", "vendor_po_on_leg",
                                   "qbo_invoice", "qbo_po", "qbo_bill"]),
            _types(got))
    by = {m.get("type"): m for m in got.get("matches") or []}
    r.check("the project carries its company",
            by.get("project", {}).get("company_id") == "acme"
            and by.get("project", {}).get("company_name") == "Ace Manufacturing",
            by.get("project"))
    r.check("the CRM invoice names the job it is linked to (4600, a different job)",
            by.get("crm_invoice", {}).get("project_no") == "4600", by.get("crm_invoice"))
    leg = by.get("vendor_po_on_leg", {})
    r.check("the vendor PO names its leg, its job and its vendor",
            leg.get("shipment_id") == "4521-L1" and leg.get("project_no") == "4521"
            and leg.get("vendor") == "Cobalt Freight", leg)
    po = by.get("qbo_po", {})
    r.check("the QuickBooks PO is ONE match with its vendor, 2 lines, $1,500.00",
            po.get("vendor") == "Cobalt Freight" and po.get("lines") == 2
            and po.get("amount_cents") == 150000, po)
    bill = by.get("qbo_bill", {})
    r.check("a bill Num is flagged as the vendor's own invoice number, not a PO",
            bill.get("vendor") == "Trueline Metals"
            and "not a PO" in str(bill.get("note")), bill)
    r.check("the bill is its one line, $777.00 -- the Expense with the same Num "
            "and vendor is not folded into it",
            bill.get("lines") == 1 and bill.get("amount_cents") == 77700, bill)
    r.check("an Expense sharing the Num is not reported as a PO or a bill",
            not any(m.get("vendor") == "Trueline Metals" and m.get("amount_cents") == 100
                    for m in got.get("matches") or []), got.get("matches"))
    r.check("the QuickBooks invoice carries its amounts in cents",
            by.get("qbo_invoice", {}).get("amount_cents") == 500000, by.get("qbo_invoice"))
    r.check("' 1167 ' reads the same as 1167 (through _key)",
            _types(st.call("lookup_number", n=" 1167 ")) == _types(got))

    r.section("composite numbers and parentheses")
    got = st.call("lookup_number", n="1191")
    r.check("1191 finds the composite CRM invoice '4521 (INV 1191)'",
            [m.get("invoice_no") for m in got.get("matches") or []
             if m.get("type") == "crm_invoice"] == ["4521 (INV 1191)"], got)
    got = st.call("lookup_number", n="4521")
    r.check("4521 is the project only -- the quote number in '4521 (INV 1191)' "
            "is not an invoice number", _types(got) == ["project"], _types(got))
    got = st.call("lookup_number", n="1300")
    r.check("1300 is the vendor PO on leg L2",
            [m.get("shipment_id") for m in got.get("matches") or []] == ["4521-L2"], got)
    r.check("... and the 1167 inside L2's parentheses is not a PO",
            "4521-L2" not in [m.get("shipment_id") for m in
                              st.call("lookup_number", n="1167").get("matches") or []])
    got = st.call("lookup_number", n="99999")
    r.check("a number that is nothing -> ok, no matches",
            got.get("ok") is True and got.get("matches") == [], got)
    r.check("lookup_number wrote nothing",
            {p.name: p.read_bytes() for p in st.path.iterdir()} == before)



def _warnings(r, st):
    r.section("setting project_no to a number that is also a vendor PO")
    got = st.call("update_invoice", company_id="acme", invoice_no="4521 (INV 1191)",
                  fields={"project_no": "1167"})
    r.check("the write succeeds", got.get("ok") is True, got)
    stored = json.loads((st.path / "invoices.json").read_text())
    r.check("... and is on disk",
            next(i for i in stored if i["invoice_no"] == "4521 (INV 1191)")
            .get("project_no") == "1167")
    w = got.get("warnings") or []
    codes = {x.get("code") for x in w}
    r.check("the response warns number_is_also_vendor_po", codes == {"number_is_also_vendor_po"}, w)
    legw = [x for x in w if x.get("source") == "shipment_leg"]
    r.check("... naming the leg's vendor and job",
            len(legw) == 1 and legw[0].get("vendor") == "Cobalt Freight"
            and legw[0].get("job") == "4521", w)
    qw = [x for x in w if x.get("source") == "qbo_snapshot"]
    r.check("... and the QuickBooks PO's vendor",
            len(qw) == 1 and qw[0].get("vendor") == "Cobalt Freight", w)
    r.check("the warning is not persisted",
            not any("warnings" in i for i in stored))

    got = st.call("update_invoice", company_id="acme", invoice_no="4521 (INV 1191)",
                  fields={"project_no": "1167", "payment_notes": "chased"})
    r.check("re-saving the same project_no (the drawer echoes it) does not warn again",
            got.get("ok") is True and not got.get("warnings"), got)
    got = st.call("update_invoice", company_id="acme", invoice_no="1167",
                  fields={"project_no": "4521"})
    r.check("a project_no that is no PO -> no warning", got.get("ok") is True
            and not got.get("warnings"), got)
    got = st.call("create_invoice", company_id="acme",
                  fields={"invoice_no": "7777", "project_no": "1167"})
    r.check("create_invoice warns the same way, and still creates",
            got.get("ok") is True
            and {x.get("source") for x in got.get("warnings") or []}
            == {"shipment_leg", "qbo_snapshot"}, got)

    r.section("the PO check can never turn a completed write into a failure")
    (st.path / "shipments.json").write_text("{ not json")
    got = st.call("update_invoice", company_id="acme", invoice_no="1167",
                  fields={"project_no": "1167"})
    stored = json.loads((st.path / "invoices.json").read_text())
    on_disk = next(i for i in stored if i["invoice_no"] == "1167").get("project_no")
    r.check("with shipments.json unreadable the write still lands", on_disk == "1167", on_disk)
    r.check("... and the response says ok, as it happened", got.get("ok") is True, got)
    r.check("... with a warning that the PO check could not run",
            [w.get("code") for w in got.get("warnings") or []] == ["po_check_unavailable"],
            got.get("warnings"))

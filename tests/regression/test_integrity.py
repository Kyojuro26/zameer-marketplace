"""Referential integrity and the persistence layer.

Defect classes covered:
  - a leg or receivable left pointing at something that no longer exists
  - identity fields a caller can overwrite after a guard has validated them
  - a stored value of an unexpected TYPE raising a raw exception out of a read
  - the store file that goes missing and is silently recreated EMPTY

That last one is the only defect found anywhere in this system that can destroy
the data rather than hide or mis-state it: the store lives on OneDrive, a file
can be absent because it has not synced down yet, and writing an authoritative
empty file replicates upward.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice, shipment  # noqa: E402


def run(server):
    r = Result("integrity", since="0.1.26")
    s = Store(server)

    r.section("a missing entity file must fail closed, never be recreated empty")
    s.reset(companies=[company()],
            invoices=[invoice("7001"), invoice("7002")])
    (s.path / "invoices.json").unlink()
    recreated_empty = False
    try:
        s.rebind()                                   # a fresh server start
        raw = s.raw("invoices")
        recreated_empty = raw is not None and raw.strip() in ("[]", "[ ]")
    except Exception:
        recreated_empty = False                      # refused to start: correct
    r.check("a missing invoices.json is NOT silently rewritten as []",
            not recreated_empty,
            "server recreated the receivables file empty and reported ok:true; "
            "on a synced store that empty file replicates upward")

    r.section("reads never raise on a hostile stored TYPE")
    s.reset(companies=[company(display_name=["Ace", "Mfg"])],
            projects=[{"company_id": "acme", "status": "won"}],
            shipments=[shipment(all_project_nos=100)],
            invoices=[invoice("7001", project_no=True)])
    for tool, args in (("get_company", {"ref": "ace"}), ("list_companies", {"query": "ace"}),
                       ("list_invoices", {}), ("list_shipments", {}),
                       ("list_projects", {}), ("find_contacts", {"company": "ace"}),
                       ("crm_info", {})):
        res = s.call(tool, **args)
        r.check(f"{tool} returns a result rather than raising",
                "_raised" not in res, res.get("_raised", ""))

    r.section("create_shipment identity cannot be overridden by caller fields")
    s.reset(companies=[company(), company("beta", "Beta Ltd")],
            projects=[project("4521"), project("9999", archived=True)])
    s.call("create_shipment", project_no="4521",
           fields={"project_no": "9999", "all_project_nos": ["9999"],
                   "company_id": "beta", "linked_to_project": False})
    leg = s.read("shipments")[0]
    r.check("the leg stays on the validated project",
            leg["project_no"] == "4521" and leg["all_project_nos"] == ["4521"],
            str(leg))
    r.check("and on the project's own company", leg["company_id"] == "acme")
    r.check("it is visible where it was filed",
            len(s.call("get_project", project_no="4521").get("shipments", [])) == 1)

    r.section("a caller cannot mint a blank or duplicate shipment id")
    s.reset(companies=[company()], projects=[project("4521")])
    for _ in range(3):
        s.call("create_shipment", project_no="4521", fields={"shipment_id": ""})
    ids = [x.get("shipment_id") for x in s.read("shipments")]
    r.check("every leg has a non-empty id", all(ids), str(ids))
    r.check("and the ids are unique", len(ids) == len(set(ids)), str(ids))

    r.section("'+ Add shipment' keeps working after a leg is reassigned away")
    s.reset(companies=[company()], projects=[project("100"), project("200")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    s.call("reassign_shipment", shipment_id="100-L1", new_project_no="200")
    a = s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-2"})
    b = s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-3"})
    r.check("the source project can still take new legs",
            a.get("ok") is True and b.get("ok") is True,
            f"{a.get('error','')} / {b.get('error','')}")

    r.section("reassigning a leg carries its customer with it")
    s.reset(companies=[company(), company("beta", "Beta Ltd")],
            projects=[project("100"), project("200", cid="beta")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    s.call("reassign_shipment", shipment_id="100-L1", new_project_no="200")
    r.check("company_id follows the leg to the new project's owner",
            s.read("shipments")[0]["company_id"] == "beta",
            s.read("shipments")[0]["company_id"])
    r.check("it appears on the new customer",
            len(s.call("get_company", ref="Beta Ltd").get("shipments", [])) == 1)
    r.check("and no longer on the old one",
            len(s.call("get_company", ref="Ace Manufacturing").get("shipments", [])) == 0)

    r.section("unlinking a shipment works with the argument the app actually sends")
    s.reset(companies=[company()], projects=[project("100")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    res = s.call("reassign_shipment", shipment_id="100-L1", new_project_no=None)
    r.check("reassign_shipment(new_project_no=None) is accepted",
            res.get("ok") is True, str(res)[:110])
    r.check("and the leg is genuinely unlinked",
            s.read("shipments")[0]["linked_to_project"] is False)

    r.section("update_shipment cannot silently re-link or re-home a leg")
    s.reset(companies=[company()], projects=[project("100")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    r.check("it refuses the link fields",
            s.call("update_shipment", shipment_id="100-L1",
                   fields={"project_no": "999"}).get("ok") is False)
    r.check("it refuses a company that does not exist",
            s.call("update_shipment", shipment_id="100-L1",
                   fields={"company_id": "nope"}).get("ok") is False)
    r.check("but stage edits still work",
            s.call("update_shipment", shipment_id="100-L1",
                   fields={"stage": "Shipped"}).get("ok") is True)

    r.section("multi-project links are consistent, and junk is refused not dropped")
    s.reset(companies=[company()],
            projects=[project("100"), project("200"), project("300")])
    s.call("create_shipment", project_no="100", fields={"vendor_po_raw": "PO-1"})
    res = s.call("reassign_shipment", shipment_id="100-L1", new_project_no="100",
                 also_project_nos=["200", "300"])
    leg = s.read("shipments")[0]
    r.check("all three links are stored, primary first",
            res.get("ok") is True and leg["all_project_nos"] == ["100", "200", "300"],
            str(leg.get("all_project_nos")))
    r.check("the leg shows on a secondary project",
            len(s.call("get_project", project_no="200").get("shipments", [])) == 1)
    r.check("a junk entry is refused rather than silently dropped",
            s.call("reassign_shipment", shipment_id="100-L1", new_project_no="100",
                   also_project_nos=[None, "200"]).get("ok") is False)

    r.section("provenance cannot be forged")
    s.reset(companies=[company()])
    for bad in ("source", "payment_status_raw", "sheet_row"):
        r.check(f"a caller cannot set {bad} on create",
                s.call("create_invoice", company_id="acme",
                       fields={"invoice_no": "1", bad: "x"}).get("ok") is False)
    s.call("create_invoice", company_id="acme", fields={"invoice_no": "9001"})
    r.check("create_invoice stamps source='manual'",
            s.read("invoices")[0].get("source") == "manual")

    r.section("a multi-file write commits fully or not at all")
    # simulate the documented Windows failure: os.replace refusing one target
    import os as _os
    real_replace = _os.replace

    def _fail_on(name):
        def patched(src, dst):
            if str(dst).endswith(name):
                raise PermissionError(f"simulated lock on {name}")
            return real_replace(src, dst)
        return patched

    s.reset(companies=[company()], projects=[project("4521")],
            invoices=[invoice("9001", project_no="4521")],
            shipments=[shipment()])
    before = (s.raw("projects"), s.raw("invoices"), s.raw("shipments"))
    _os.replace = _fail_on("shipments.json")
    try:
        res = s.call("rename_project", old_project_no="4521", new_project_no="4600")
    finally:
        _os.replace = real_replace
    r.check("the failure is reported", res.get("ok") is False, str(res)[:80])
    after = (s.raw("projects"), s.raw("invoices"), s.raw("shipments"))
    r.check("NOTHING was committed -- the project was not renamed",
            after[0] == before[0],
            "projects.json committed while the cascade failed, so the invoice "
            "now points at a project number that no longer exists")
    r.check("and the invoice link is untouched", after[1] == before[1])
    r.check("the store is still readable after the failed write",
            s.call("get_project", project_no="4521").get("ok") is True)
    r.check("and the advised retry now works",
            s.call("rename_project", old_project_no="4521",
                   new_project_no="4600").get("ok") is True)

    r.section("create_vendor does not silently re-role an existing customer")
    # company_id must equal _slug(display_name), or create_vendor derives a
    # different id and never sees the existing customer at all
    s.reset(companies=[company("ace-manufacturing", "Ace Manufacturing")],
            invoices=[invoice("9001", "ace-manufacturing")])
    res = s.call("create_vendor", fields={"display_name": "Ace Manufacturing",
                                          "rep": "A Rep"})
    r.check("it refuses rather than reclassifying the customer",
            res.get("ok") is False, str(res)[:90])
    r.check("the company is still a customer",
            s.read("companies")[0]["role"] == "customer")
    r.check("and still appears in the customers list",
            s.call("list_companies", role="customer").get("count") == 1)

    return r

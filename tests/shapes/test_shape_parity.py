"""SHAPE 1 -- a guard applied to one entity and not its twin.

Nearly every serious defect in this system has this shape. The project side got
a liveness guard, an ambiguity guard and a falsy-key filter; the company side
got none. rename_invoice grew an empty-key guard; rename_project did not, and
the resulting cascade repointed every unlinked record in the store.
create_shipment was hardened so caller fields cannot override validated
identity; create_invoice already had it; reassign_shipment did not.

These tests do not check "does guard X exist". They assert that ANALOGOUS
OPERATIONS BEHAVE THE SAME WAY, so that adding a guard to one half of a pair
without the other fails here rather than in the operator's store.

When a new entity or a new guard is added, add the pair here.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice  # noqa: E402


def run(server):
    r = Result("SHAPE/parity", since="all")
    s = Store(server)

    # ---- pair: linking to a soft-deleted parent -----------------------------
    r.section("liveness: a link to an archived parent is refused, whichever parent")
    s.reset(companies=[company("ghost", "Ghost Co"), company()],
            projects=[project("9999", archived=True), project("4521")])
    s.call("archive_company", company_id="ghost")
    pairs = [
        ("archived PROJECT", s.call("create_invoice", company_id="acme",
                                    fields={"invoice_no": "1", "project_no": "9999"})),
        ("archived COMPANY", s.call("create_invoice", company_id="ghost",
                                    fields={"invoice_no": "2"})),
    ]
    verdicts = {label: res.get("ok") for label, res in pairs}
    r.check("both halves of the pair agree",
            len(set(verdicts.values())) == 1,
            f"{verdicts} -- one parent type is guarded and the other is not")
    r.check("and both refuse", all(v is False for v in verdicts.values()),
            str(verdicts))

    # ---- pair: falsy identifiers in an archived-key set ---------------------
    r.section("falsy keys: an archived record with an empty key hides nothing else")
    outcomes = {}
    s.reset(companies=[company(), company("beta", "Beta Ltd")],
            projects=[project(None, archived=True)],
            invoices=[invoice("B1", "beta", project_no=None)])
    outcomes["project side"] = s.call("list_invoices").get("count")
    s.reset(companies=[company(None, "Nameless", archived=True),
                       company("beta", "Beta Ltd")],
            invoices=[invoice("B1", "beta", project_no=None)])
    outcomes["company side"] = s.call("list_invoices").get("count")
    r.check("both halves of the pair agree",
            len(set(outcomes.values())) == 1,
            f"{outcomes} -- the falsy-key filter exists on one side only")
    r.check("and neither hides the unrelated receivable",
            all(v == 1 for v in outcomes.values()), str(outcomes))

    # ---- pair: empty lookup key on a cascading rename -----------------------
    r.section("empty lookup keys: every cascading rename refuses one")
    s.reset(companies=[company()], projects=[project(None)],
            invoices=[invoice("A1", project_no=None)])
    a = s.call("rename_project", old_project_no="", new_project_no="9999")
    s.reset(companies=[company()], invoices=[invoice(None)])
    b = s.call("rename_invoice", company_id="acme", old_invoice_no="",
               new_invoice_no="9999")
    r.check("rename_project and rename_invoice agree on an empty old key",
            a.get("ok") == b.get("ok"),
            f"project={a.get('ok')} invoice={b.get('ok')}")
    r.check("and both refuse",
            a.get("ok") is False and b.get("ok") is False)

    # ---- pair: ambiguous key on a cascading rename --------------------------
    r.section("ambiguity: a duplicated key is refused for both entities")
    s.reset(companies=[company()],
            projects=[project("4521", archived=True), project("4521")])
    a = s.call("rename_project", old_project_no="4521", new_project_no="9999")
    s.reset(companies=[company()],
            invoices=[invoice("7001", sheet_row=1), invoice("7001", sheet_row=2)])
    b = s.call("rename_invoice", company_id="acme", old_invoice_no="7001",
               new_invoice_no="7002")
    r.check("rename_project and rename_invoice agree on a duplicate",
            a.get("ok") == b.get("ok"),
            f"project={a.get('ok')} invoice={b.get('ok')}")
    r.check("and both refuse", a.get("ok") is False and b.get("ok") is False)

    # ---- pair: caller fields cannot override validated identity -------------
    r.section("identity: what a guard validated, caller fields cannot overwrite")
    s.reset(companies=[company(), company("beta", "Beta Ltd")],
            projects=[project("4521")])
    s.call("create_shipment", project_no="4521", fields={"company_id": "beta"})
    ship_ok = s.read("shipments")[0]["company_id"] == "acme"
    s.call("create_invoice", company_id="acme",
           fields={"invoice_no": "9001", "company_id": "beta"})
    inv = s.read("invoices")
    inv_ok = (not inv) or inv[0]["company_id"] == "acme"
    r.check("create_shipment and create_invoice agree",
            ship_ok == inv_ok, f"shipment_authoritative={ship_ok} invoice_authoritative={inv_ok}")
    r.check("and both keep identity authoritative", ship_ok and inv_ok)

    # ---- pair: boolean identifiers are refused everywhere -------------------
    r.section("type discipline: a bool identifier is refused by every create")
    s.reset(companies=[company()])
    got = {
        "create_project": s.call("create_project",
                                 fields={"company_id": "acme", "project_no": True,
                                         "status": "won"}).get("ok"),
        "create_invoice": s.call("create_invoice", company_id="acme",
                                 fields={"invoice_no": True}).get("ok"),
        "create_company": s.call("create_company",
                                 fields={"display_name": "X", "company_id": True}).get("ok"),
    }
    r.check("every create agrees on a boolean identifier",
            len(set(got.values())) == 1, str(got))
    r.check("and all refuse it", all(v is False for v in got.values()), str(got))

    # ---- pair: soft-delete writes the same shape wherever it is set ---------
    r.section("archive: the flag is a real boolean via every path that sets it")
    s.reset(companies=[company()])
    s.call("archive_company", company_id="acme")
    via_tool = s.read("companies")[0]["archived"]
    s.reset(companies=[company()])
    s.call("update_company", company_id="acme", fields={"archived": "no"})
    via_update = s.read("companies")[0]["archived"]
    r.check("archived is a bool no matter which path set it",
            isinstance(via_tool, bool) and isinstance(via_update, bool),
            f"archive_company -> {via_tool!r}, update_company -> {via_update!r}")

    return r

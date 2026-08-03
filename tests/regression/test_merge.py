"""Re-importing must not destroy operator work.

normalize.py rewrote all seven store files wholesale, and --force bypassed the
only guard -- so a re-import deleted every hand-entered invoice and reverted
every payment status, note and due-date override set since the last import. The
normal case, "keep using the tracker and pull a fresh import", had no supported
path at all.

The rule under test: a field is refreshed from the workbook UNLESS the operator
edited that exact field on that exact record (per changelog.jsonl), and NOTHING
is ever deleted.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402


def _load_merge(crm_dir):
    import importlib.util
    p = Path(crm_dir) / "pipeline" / "merge.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location("_merge_under_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(server, crm_dir=None):
    r = Result("merge", since="0.1.28")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    merge = _load_merge(crm)
    if merge is None:
        r.check("a re-import has a non-destructive path (pipeline/merge.py)",
                False,
                "no merge module -- re-importing rewrites the store wholesale "
                "and discards every hand-entered record and operator edit")
        return r

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="crmmerge-"))
    for e in ("companies", "contacts", "projects", "shipments",
              "vendors", "needs_review", "invoices"):
        (tmp / f"{e}.json").write_text("[]")
    (tmp / "companies.json").write_text(json.dumps(
        [{"company_id": "acme", "display_name": "Ace", "role": "customer",
          "archived": False}]))
    (tmp / "invoices.json").write_text(json.dumps([
        {"invoice_no": "7001", "company_id": "acme", "payment_status": "paid",
         "payment_notes": "check 8812", "due_on": "2026-05-01",
         "payment_status_raw": "Open", "sheet_row": 11},
        {"invoice_no": "9999", "company_id": "acme", "payment_status": "open",
         "source": "manual"}]))
    (tmp / "projects.json").write_text(json.dumps([
        {"project_no": "4521", "company_id": "acme", "status": "won",
         "revenue": 50000, "archived": False},
        {"project_no": "4530", "company_id": "acme", "status": "won",
         "archived": True}]))
    with open(tmp / "changelog.jsonl", "w") as f:
        f.write(json.dumps({"op": "update", "entity": "invoice",
                            "key": "acme:7001",
                            "fields": {"payment_status": "paid",
                                       "payment_notes": "check 8812",
                                       "due_on": "2026-05-01"}}) + "\n")
        f.write(json.dumps({"op": "create", "entity": "invoice",
                            "key": "acme:9999",
                            "fields": {"invoice_no": "9999"}}) + "\n")
        f.write(json.dumps({"op": "archive", "entity": "project", "key": "4530",
                            "fields": {"archived": True}}) + "\n")

    # the workbook still says 7001 is open, revenue moved, 4530 is gone
    fresh = {
        "companies.json": [{"company_id": "acme", "display_name": "Ace",
                            "role": "customer", "archived": False}],
        "contacts.json": [], "vendors.json": [], "shipments.json": [],
        "needs_review.json": [{"type": "fresh"}],
        "projects.json": [{"project_no": "4521", "company_id": "acme",
                           "status": "won", "revenue": 75000, "archived": False}],
        "invoices.json": [{"invoice_no": "7001", "company_id": "acme",
                           "payment_status": "open", "payment_notes": None,
                           "due_on": None, "payment_status_raw": "Open",
                           "sheet_row": 11}],
    }
    merged, report = merge.merge_all(fresh, str(tmp))
    inv = {i["invoice_no"]: i for i in merged["invoices.json"]}
    pr = {p["project_no"]: p for p in merged["projects.json"]}

    r.section("operator edits survive a re-import")
    r.check("a payment status the operator set is NOT reverted",
            inv["7001"]["payment_status"] == "paid",
            f"became {inv['7001']['payment_status']!r} -- the workbook overwrote "
            f"a collection the operator recorded")
    r.check("their payment note survives", inv["7001"]["payment_notes"] == "check 8812")
    r.check("their due-date override survives", inv["7001"]["due_on"] == "2026-05-01")

    r.section("untouched fields still refresh from the workbook")
    r.check("revenue the operator never edited is updated",
            pr["4521"]["revenue"] == 75000, str(pr["4521"]["revenue"]))
    r.check("needs_review is regenerated, not merged",
            merged["needs_review.json"] == [{"type": "fresh"}])

    r.section("nothing is ever deleted")
    r.check("a hand-entered invoice survives a re-import", "9999" in inv,
            "source=manual record deleted -- a receivable the operator typed in")
    r.check("an archived project survives, and stays archived",
            "4530" in pr and pr["4530"]["archived"] is True)
    r.check("both are reported rather than silently kept",
            len(report["kept"]) == 2, str(report["kept"]))
    r.check("and the preserved fields are named in the report",
            any(set(p["fields"]) >= {"payment_status"} for p in report["preserved"]),
            str(report["preserved"]))

    r.section("an edit follows its record through a rename")
    # An edit is logged under the key the record had AT THE TIME. A later rename
    # moves the record, and looking it up by its CURRENT key found nothing -- so
    # the workbook silently reverted a payment the operator had recorded. The
    # suite passed over this until it was tested directly.
    from lib.harness import Store as _S, company as _co, invoice as _inv
    for label, ops, wb_no, want in (
            ("edit, then renumber",
             [("update", "9001", {"payment_status": "paid"}), ("rename", "9001", "9002")],
             "9002", "paid"),
            ("edit, then renumber twice",
             [("update", "9001", {"payment_status": "paid"}), ("rename", "9001", "9002"),
              ("rename", "9002", "9003")], "9003", "paid"),
            ("renumber, undo it, then edit",
             [("rename", "9001", "9002"), ("rename", "9002", "9001"),
              ("update", "9001", {"payment_status": "paid"})], "9001", "paid"),
            ("no edit at all -- the workbook must win",
             [("rename", "9001", "9002")], "9002", "open")):
        st = _S(server).reset(companies=[_co()],
                              invoices=[_inv("9001", payment_status_raw="Open",
                                             sheet_row=11)])
        for op, key, arg in ops:
            if op == "update":
                st.call("update_invoice", company_id="acme", invoice_no=key, fields=arg)
            else:
                st.call("rename_invoice", company_id="acme", old_invoice_no=key,
                        new_invoice_no=arg)
        wb = {"companies.json": [_co()], "contacts.json": [], "vendors.json": [],
              "projects.json": [], "shipments.json": [], "needs_review.json": [],
              "invoices.json": [{"invoice_no": wb_no, "company_id": "acme",
                                 "payment_status": "open", "payment_notes": None,
                                 "payment_status_raw": "Open", "sheet_row": 11}]}
        got = merge.merge_all(wb, str(st.path))[0]["invoices.json"][0]
        r.check(f"{label}: status is {want!r} after the merge",
                got["payment_status"] == want,
                f"got {got['payment_status']!r}")

    r.section("it refuses when it cannot know what to protect")
    (tmp / "changelog.jsonl").unlink()
    try:
        merge.merge_all(fresh, str(tmp))
        r.check("a live store with no changelog is refused", False,
                "merged anyway -- without the changelog an operator edit is "
                "indistinguishable from an import artefact")
    except Exception as e:                              # noqa: BLE001
        r.check("a live store with no changelog is refused", True)
        r.check("and the refusal explains what to do",
                "backup" in str(e).lower() or "back the store up" in str(e).lower(),
                str(e)[:90])

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return r

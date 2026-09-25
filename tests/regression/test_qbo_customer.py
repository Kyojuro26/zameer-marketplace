"""A QuickBooks match must agree on the customer (0.1.44 H3).

qbo_match paired a CRM invoice with a QuickBooks row by (Invoice, number) and
nothing else. qbo_match_shared caught two CRM invoices claiming one number,
but ONE wrong CRM invoice claiming another customer's QuickBooks number was
priced silently. Now, once the number matches:

  * the company is TIED to a QuickBooks name -- its qbo_name, or its display
    name matching (normalised) a customer the snapshot names -- and the row
    names someone else: not priced, excluded as qbo_customer_mismatch, both
    names carried where the invoice is shown;
  * the row names the company (qbo_name exactly, or display name normalised):
    priced, silently;
  * the company is tied to nothing (no qbo_name -- blank counts as none -- and
    a display name QuickBooks never uses), or the row names nobody: priced as
    before, and counted in the basis as "customer not verified: N". Excluding
    these would silently shrink the tile for every unlinked customer.

The shape invariants (counted + excluded == population, the closed
vocabulary) hold throughout. Fixture names are invented.
"""
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness import Result, Store, company, invoice, project  # noqa: E402


def run(server, crm_dir=None):
    r = Result("qbo-customer", since="0.1.44")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    srv._today = lambda: date(2026, 9, 1)
    r.check("the vocabulary has qbo_customer_mismatch",
            "qbo_customer_mismatch" in getattr(srv, "EXCLUSION_REASONS", ()))
    # a server from before QuickBooks snapshots (0.1.38) has no join to check:
    # that is the defect, named, not a crash the runner cannot score
    if not r.check("the server can hold a QuickBooks snapshot", callable(getattr(srv, "_save_qbo_snapshot", None))):
        return r
    import test_metrics as TM
    tmp = Path(tempfile.mkdtemp(prefix="crm-qcust-"))
    s = Store(srv, tmp / "store")
    s.reset(companies=[company("acme", "Ace Manufacturing", qbo_name="Ace Mfg"),
                       company("beta", "Beta Works"),
                       company("gamma", "Gamma Tooling"),
                       company("delta", "Delta Parts", qbo_name="")],
            projects=[project(str(n), c, revenue=100) for n, c in
                      ((4001, "acme"), (4002, "acme"), (4003, "beta"), (4004, "beta"),
                       (4005, "gamma"), (4006, "delta"), (4007, "acme"))],
            invoices=[invoice(str(9000 + n), c, project_no=str(4000 + n), invoice_date="2026-06-01")
                      for n, c in ((1, "acme"), (2, "acme"), (3, "beta"), (4, "beta"),
                                   (5, "gamma"), (6, "delta"), (7, "acme"))])
    row = lambda num, name, o: {"type": "Invoice", "num": num, "name": name,
                                "amount_cents": 50000, "open_cents": o}
    srv._save_qbo_snapshot("invoices", "export", "2026-08-30", "2026-01-01", "2026-08-30", [
        row("9001", "Ace Mfg", 1000),            # acme's qbo_name: agrees
        row("9002", "Beta Works", 2000),         # acme is tied (qbo_name), row names beta: mismatch
        row("9003", "  beta   WORKS ", 3000),    # beta tied by display name, normalised: agrees
        row("9004", "Ace Mfg", 4000),            # beta is tied, row names acme: mismatch
        row("9005", "Somebody Else", 5000),      # gamma is tied to nothing: unverified
        row("9006", "Whoever", 6000),            # delta: qbo_name blank, display unused: unverified
        row("9007", None, 7000)])                # acme is tied, but the row names nobody: unverified
    s.rebind()
    res = s.call("list_companies")
    co = {c["company_id"]: c for c in res.get("companies", [])}

    def qopen(cid):
        return (co.get(cid, {}).get("metrics") or {}).get("qbo_open_receivable_usd") or {}

    def per(cid, no):
        m = (co.get(cid, {}).get("metrics") or {}).get("qbo_invoices") or {}
        return m.get(no) or {}

    a, b, g, d = qopen("acme"), qopen("beta"), qopen("gamma"), qopen("delta")
    r.check("a mismatched customer is not priced, excluded as qbo_customer_mismatch",
            a.get("value_cents") == 1000 + 7000 and a.get("excluded") == {"qbo_customer_mismatch": 1}
            and b.get("value_cents") == 3000 and b.get("excluded") == {"qbo_customer_mismatch": 1},
            json.dumps([a, b])[:300])
    mm = per("acme", "9002")
    r.check("... and the invoice carries both customers' names",
            (mm.get("qbo_customer_mismatch") or {}) == {"crm": "Ace Manufacturing", "qbo": "Beta Works"},
            json.dumps(mm)[:300])
    mm = per("beta", "9004")
    r.check("... the same when the company is tied by its display name",
            (mm.get("qbo_customer_mismatch") or {}) == {"crm": "Beta Works", "qbo": "Ace Mfg"},
            json.dumps(mm)[:300])
    r.check("a correctly linked customer prices silently",
            per("acme", "9001").get("qbo_open_usd", {}).get("value_cents") == 1000
            and "not verified" not in b.get("basis", ""), json.dumps(b)[:300])
    r.check("an unlinked customer still prices, and is counted as not verified",
            g.get("value_cents") == 5000 and not g.get("excluded")
            and "customer not verified: 1" in g.get("basis", ""), json.dumps(g)[:300])
    r.check("a blank qbo_name is no tie: unverified, priced",
            d.get("value_cents") == 6000 and "customer not verified: 1" in d.get("basis", ""), json.dumps(d)[:300])
    r.check("a QuickBooks row that names nobody is unverified, not a mismatch",
            per("acme", "9007").get("qbo_open_usd", {}).get("value_cents") == 7000
            and "customer not verified: 1" in a.get("basis", ""), json.dumps(a)[:300])
    r.check("the shape carries how many priced invoices are not verified, for the screen",
            g.get("customer_not_verified") == 1 and a.get("customer_not_verified") == 1
            and not b.get("customer_not_verified"), json.dumps([g, a, b])[:300])
    for label, resp in (("list_companies", res), ("get_company", s.call("get_company", ref="acme")),
                        ("crm_metrics", s.call("crm_metrics"))):
        TM.check_invariants(r, f"qbo-customer {label}", resp)
    _review(r, srv, tmp, TM)
    shutil.rmtree(tmp, ignore_errors=True)
    return r


def _review(r, srv, tmp, TM):
    """Review of 0.1.44: the new reason must be handled by every consumer of a
    QuickBooks match, and names compared the way QuickBooks compares them."""
    s = Store(srv, tmp / "review" / "store")
    s.reset(companies=[company("acme", "Ace Manufacturing", qbo_name="ACE MFG."),
                       company("beta", "Beta Works")],
            projects=[project("4100", "acme", revenue=10000, total_cost=6000, status="won"),
                      project("4200", "acme", revenue=5000, total_cost=1000, status="won")],
            invoices=[invoice("9101", "acme", project_no="4100", invoice_date="2026-06-01"),
                      invoice("9102", "acme", project_no="4100", invoice_date="2026-06-01"),
                      invoice("9201", "acme", project_no="4200", invoice_date="2026-06-01")])
    row = lambda num, name: {"type": "Invoice", "num": num, "name": name,
                             "amount_cents": 500000, "open_cents": 0}
    srv._save_qbo_snapshot("invoices", "export", "2026-08-30", "2026-01-01", "2026-08-30", [
        row("9101", "Ace Mfg"),                  # qbo_name "ACE MFG." -- case and punctuation only
        row("9102", "Beta Works"),               # the other half of 4100: another customer
        row("9201", "Beta Works")])              # 4200's only invoice: another customer
    s.rebind()
    co = {c["company_id"]: c for c in s.call("list_companies").get("companies", [])}
    per = ((co.get("acme") or {}).get("metrics") or {}).get("qbo_invoices") or {}
    r.check("a qbo_name differing only by case and punctuation agrees, as QuickBooks reads names",
            (per.get("9101") or {}).get("qbo_open_usd", {}).get("counted") == 1, json.dumps(per.get("9101"))[:200])
    cfo = ((s.call("crm_metrics", report="cfo").get("reports") or {}).get("cfo")) or {}
    jobs = {str((j.get("job") or {}).get("project_no")): j for j in (cfo.get("margin") or {}).get("jobs", [])}
    r.check("CFO: a job half-matched to another customer is not priced on its other half",
            "4100" in jobs and jobs["4100"]["invoiced_usd"].get("value_cents") is None, json.dumps(jobs.get("4100"))[:300])
    r.check("CFO: a job whose only invoice is another customer's stays, with its quoted margin",
            "4200" in jobs and jobs["4200"]["quoted_margin_usd"].get("counted") == 1, json.dumps(jobs.get("4200"))[:300])
    r.check("CFO: the job's invoiced figure says why -- a customer mismatch, as rankings says",
            (jobs.get("4200", {}).get("invoiced_usd", {}).get("excluded") or {}) == {"qbo_customer_mismatch": 1}
            and (jobs.get("4200", {}).get("realized_margin_usd", {}).get("excluded") or {}) == {"qbo_customer_mismatch": 1},
            json.dumps(jobs.get("4200"))[:300])
    drift = ((s.call("crm_metrics", report="qbo_drift").get("reports") or {}).get("qbo_drift")) or {}
    rows = {str(x.get("num")): x for x in drift.get("rows", [])}
    r.check("drift: a QuickBooks invoice the only CRM claimant is not the customer for is listed as uncarried",
            "9201" in rows and rows["9201"].get("company_id") == "beta", json.dumps(drift.get("rows"))[:300])
    # one rule for "this QuickBooks name is this company": the resolver the
    # drift report, the CFO list and the number lookup use agrees with the match
    srv._save_qbo_snapshot("invoices", "export", "2026-08-30", "2026-01-01", "2026-08-30", [
        row("9101", "Ace Mfg"), row("9102", "Beta Works"), row("9201", "Beta Works"),
        row("9301", "ace mfg")])                 # no CRM invoice: uncarried, and whose?
    s.rebind()
    drift = ((s.call("crm_metrics", report="qbo_drift").get("reports") or {}).get("qbo_drift")) or {}
    rows = {str(x.get("num")): x for x in drift.get("rows", [])}
    r.check("drift names the company a qbo_name matches by case alone, as the match does",
            (rows.get("9301") or {}).get("company_id") == "acme"
            and not any(u.get("name", "").lower() == "ace mfg" for u in drift.get("unmatched_names", [])),
            json.dumps([rows.get("9301"), drift.get("unmatched_names")])[:300])
    TM.check_invariants(r, "qbo-customer review cfo", {"cfo": cfo, "drift": drift})

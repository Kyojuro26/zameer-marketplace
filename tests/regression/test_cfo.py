"""The CFO report: cash, receivables, margin, expenses (0.1.40, Phase D).

crm_metrics(report="cfo") -- every figure a shape computed in server.py;
the view only renders it. Decisions asserted, each with an obvious wrong
version:

 1. CASH comes only from a cash_balances snapshot (the connector; no export
    exists). Banks and credit cards are totalled apart. With none loaded the
    section says what to load and every figure is null -- never $0.
    Expected-in is QuickBooks' OPEN balance by QuickBooks' due date, never
    CRM quoted revenue. Committed-out counts a PO only where the snapshot
    carries its open_status; an export carries none, so it reads "not
    computable" (po_status_unknown), never an estimate.
 2. RECEIVABLES are QuickBooks' open balance aged by QuickBooks' due date, a
    ranked who-owes-most by the QuickBooks customer name, and the drift list.
 3. MARGIN per invoiced job, three figures never merged:
      quoted_margin_usd     CRM revenue minus total cost (quoted)
      realized_margin_usd   QuickBooks invoiced minus attributed cost: bills by
                            linked_po, then expenses by customer_ref; a PO with
                            no bill is cost_not_billed_yet; from an EXPORT the
                            bills are a block, bills_not_linkable_from_export;
                            never vendor/date/amount inference
      po_costed_margin_usd  invoiced minus the QuickBooks POs joined to the
                            job's legs by the exact (PO, number) -- "PO-costed:
                            excludes costs paid directly as expenses, so it
                            overstates margin"
    A job is the leg's project when it has one, else its invoice on
    (number, company_id); a project's invoices roll up to it. The realized
    basis states jobs counted, the share of window COGS attributed and the
    unattributed dollars.
 4. EXPENSES from posting rows only (bill payments are not spend twice), by
    split account (a null split is its own line), by vendor AS EXPORTED --
    resolving a name to a CRM vendor adds vendor_id and never merges rows --
    and COGS vs overhead, for the window and its last 30 days.

Every shape obeys the suite's shape invariants. Names are invented.
"""
import datetime
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)

TODAY = datetime.date(2026, 4, 20)
COGS = "Cost of Goods Sold"


def seed_store(st):
    st.reset(
        companies=[company("acme", "Ace Manufacturing"),
                   company("beta", "Beta Works"),
                   company("cobalt", "Cobalt Freight", role="vendor"),
                   company("trueline", "Trueline Metals", role="vendor")],
        vendors=[{"company_id": "cobalt", "display_name": "Cobalt Freight", "archived": False},
                 {"company_id": "trueline", "display_name": "Trueline Metals",
                  "qbo_name": "Trueline Metals Inc", "archived": False}],
        projects=[project("4521", "acme", revenue=10000, total_cost=6000)],
        invoices=[invoice("7001", "acme", project_no="4521", invoice_date="2026-02-01"),
                  invoice("7002", "acme", project_no="4521", invoice_date="2026-02-10"),
                  invoice("7003", "beta", invoice_date="2026-03-01"),
                  invoice("7004", "beta", invoice_date="2026-03-05"),
                  invoice("7005", "beta", invoice_date="2026-03-06"),
                  invoice("7006", "beta", invoice_date="2026-03-08"),
                  invoice("6000", "beta", invoice_date="2025-06-01")],
        shipments=[shipment("4521-L1", "4521", "acme", vendor_po_raw="PO # 1101 (Cobalt)"),
                   shipment("4521-L2", "4521", "acme", vendor_po_raw="PO # 1102"),
                   shipment("inv7003-L1", None, "beta", all_project_nos=[],
                            invoice_no="7003", vendor_po_raw="PO # 1103"),
                   shipment("inv7004-L1", None, "beta", all_project_nos=[],
                            invoice_no="7004", vendor_po_raw="PO # 1104"),
                   shipment("inv7004-L2", None, "beta", all_project_nos=[],
                            invoice_no="7004", vendor_po_raw="PO # 9999")])


def qbo_invoices(server, as_of="2026-04-18"):
    row = lambda num, name, amt, opn, due: {  # noqa: E731
        "type": "Invoice", "num": num, "date": "2026-02-01", "due_date": due,
        "name": name, "amount_cents": amt, "open_cents": opn}
    server._save_qbo_snapshot("invoices", "export", as_of, "2026-01-01", "2026-03-31", [
        row("7001", "Ace Manufacturing", 600000, 0, "2026-03-01"),
        row("7002", "Ace Manufacturing", 400000, 100000, "2026-04-10"),   # 10 days late
        row("7003", "Beta Works", 300000, 300000, "2026-04-23"),          # in 3 days
        row("7004", "Beta Works", 200000, 0, "2026-04-04"),
        row("7005", "Beta Works", 50000, 50000, "2026-05-10"),            # in 20 days
        row("8000", "Zed Co", 70000, 70000, "2026-06-30")])               # later


def vendor_rows(connector):
    """The same spend, as the connector sends it (with linked_po, customer_ref,
    open_status) or as an export (without them). Amounts carry QuickBooks'
    signs as the Transaction List shows them -- measured on the real export: a
    bill is positive, an expense or check NEGATIVE (the payment account's view),
    a vendor credit negative (it reduces cost)."""
    def r(vendor, date, typ, num, amt, split=COGS, posting=True, **kw):
        row = {"vendor": vendor, "date": date, "type": typ, "num": num,
               "posting": posting, "account": "Checking", "split_account": split,
               "amount_cents": amt}
        if connector:
            row.update(kw)
        return row
    return [
        r("Cobalt Freight", "2026-01-10", "Purchase Order", "1101", 150000, posting=False,
          open_status="closed"),
        r("Cobalt Freight", "2026-01-12", "Purchase Order", "1102", 50000, posting=False,
          open_status="closed"),
        r("Trueline Metals", "2026-02-01", "Purchase Order", "1103", 100000, posting=False,
          open_status="open"),
        r("Trueline Metals", "2026-02-03", "Purchase Order", "1104", 30000, posting=False,
          open_status="open"),
        r("Cobalt Freight", "2026-01-20", "Bill", "C-1", 150000, linked_po="1101"),
        r("Cobalt Freight", "2026-02-10", "Bill", "C-2", 50000, linked_po="1102"),
        r("Cobalt Freight", "2026-02-02", "Bill Payment (Check)", "3301", -150000,
          split="Accounts Payable"),
        r("Trueline Metals", "2026-03-10", "Expense", None, -10000, customer_ref="Ace Manufacturing"),
        r("Trueline Metals", "2026-03-15", "Expense", None, -20000, customer_ref="Beta Works"),
        r("Trueline Metals Inc", "2026-03-12", "Expense", None, -1000),
        r("Keystone Fasteners", "2026-02-20", "Check", "5501", -25000),
        r("Keystone Fasteners", "2026-03-25", "Expense", None, -7000, split=None),
        r("Paperline Office", "2026-03-20", "Expense", None, -5000, split="Office Supplies"),
        r("Cobalt Freight", "2026-03-28", "Vendor Credit", "VC-1", -2000),
        r("Cobalt Freight", "2026-03-29", "Credit Card Credit", "CC-9", -300),
        # paying down balances, not operating spend (invented account names)
        r("Harbor Lending", "2026-03-05", "Check", "5502", -8000, split="Note: Truck Loan"),
        r("Bluefin Card Services", "2026-03-06", "Expense", None, -4000,
          split="Company Card Payable"),
        r("State Revenue Office", "2026-03-07", "Tax Payment", None, -600,
          split="Sales Tax Payable"),
        r("Paperline Office", "2026-03-04", "Journal Entry", "JE-7", None),
    ]


def load_vendor(server, connector, as_of="2026-04-18"):
    server._save_qbo_snapshot("vendor_transactions", "connector" if connector else "export",
                              as_of, "2026-01-01", "2026-03-31", vendor_rows(connector))


def load_cash(server, as_of="2026-04-18"):
    server._save_qbo_snapshot("cash_balances", "connector", as_of, "2026-04-18", "2026-04-18", [
        {"account": "Operating Checking", "account_type": "Bank", "balance_cents": 5012345},
        {"account": "Savings", "account_type": "Bank", "balance_cents": 100000},
        {"account": "Company Card", "account_type": "Credit Card", "balance_cents": -120000},
        {"account": "Undeposited Funds", "balance_cents": 5000}])


def cfo(st):
    got = st.call("crm_metrics", report="cfo")
    return (got.get("reports") or {}).get("cfo") or {}, got


def run(server, crm_dir=None):
    r = Result("cfo", since="0.1.40")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    # a build with no clock hook still runs: its report is then asked for,
    # and fails on what it RETURNS rather than on a missing hook
    hooked = callable(getattr(server, "_today", None))
    tmp = Path(tempfile.mkdtemp(prefix="crmcfo-"))
    real_today = getattr(server, "_today", None)
    if hooked:
        server._today = lambda: TODAY
    try:
        _body(r, server, tmp)
    finally:
        if hooked:
            server._today = real_today
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _v(sh):
    return (sh or {}).get("value_cents")


def _body(r, server, tmp):
    st = Store(server, tmp / "m" / "store")
    seed_store(st)

    # ---- nothing loaded -------------------------------------------------------
    r.section("no snapshot at all")
    c, got = cfo(st)
    if not r.check("crm_metrics(report='cfo') answers", got.get("ok") is True and bool(c), got):
        return
    cash = c.get("cash") or {}
    r.check("with no cash snapshot the cash section says what to load",
            cash.get("loaded") is False and "connector" in str(cash.get("load"))
            and "Balance Sheet" in str(cash.get("load")), cash)
    r.check("... and the bank total is null, not $0",
            (cash.get("bank_total_usd") or {}).get("value") is None, cash.get("bank_total_usd"))
    r.check("the margin and expense sections say what to load too",
            (c.get("margin") or {}).get("loaded") is False
            and (c.get("expenses") or {}).get("loaded") is False, (c.get("margin"), c.get("expenses")))
    r.check("every tile is null with nothing loaded",
            all((t or {}).get("value") is None for t in (c.get("tiles") or {}).values())
            and len(c.get("tiles") or {}) == 4, c.get("tiles"))
    if not callable(getattr(server, "_save_qbo_snapshot", None)):
        return

    # ---- the connector path: everything -------------------------------------
    qbo_invoices(server)
    load_vendor(server, connector=True)
    load_cash(server)
    c, _ = cfo(st)

    r.section("cash")
    cash = c.get("cash") or {}
    r.check("banks total 5,012,345 + 100,000 cents", _v(cash.get("bank_total_usd")) == 5112345
            and (cash.get("bank_total_usd") or {}).get("counted") == 2, cash.get("bank_total_usd"))
    r.check("credit cards are totalled apart: -120,000", _v(cash.get("card_total_usd")) == -120000,
            cash.get("card_total_usd"))
    r.check("an account with no type is listed, not guessed into either total",
            [a.get("account") for a in cash.get("unclassified_accounts") or []] == ["Undeposited Funds"],
            cash.get("unclassified_accounts"))
    ei = cash.get("expected_in") or {}
    r.check("expected in: QuickBooks open by due date -- overdue 100,000",
            _v(ei.get("overdue_usd")) == 100000, ei.get("overdue_usd"))
    r.check("... next 7 days 300,000", _v(ei.get("next_7_days_usd")) == 300000, ei.get("next_7_days_usd"))
    r.check("... 8 to 30 days 50,000", _v(ei.get("next_8_to_30_days_usd")) == 50000,
            ei.get("next_8_to_30_days_usd"))
    co = cash.get("committed_out_usd") or {}
    r.check("committed out: the two OPEN POs, 130,000, over the four with a status",
            _v(co) == 130000 and co.get("counted") == 4 and not co.get("excluded"), co)

    r.section("receivables")
    rec = c.get("receivables") or {}
    r.check("QuickBooks open balance 520,000 over 4 open invoices",
            _v(rec.get("open_usd")) == 520000 and (rec.get("open_usd") or {}).get("counted") == 4,
            rec.get("open_usd"))
    b = rec.get("buckets") or {}
    r.check("aged by QuickBooks' due date: 100,000 at 0-30, 420,000 not yet due",
            _v(b.get("0-30")) == 100000 and _v(b.get("not_yet_due")) == 420000
            and _v(b.get("90+")) is None, {k: _v(v) for k, v in b.items()})
    who = rec.get("who_owes_most") or []
    r.check("who owes the most, ranked: Beta 350,000, Ace 100,000, Zed 70,000",
            [(w.get("name"), _v(w.get("open_usd"))) for w in who]
            == [("Beta Works", 350000), ("Ace Manufacturing", 100000), ("Zed Co", 70000)],
            [(w.get("name"), _v(w.get("open_usd"))) for w in who])
    r.check("... each row carries the CRM company where the name resolves",
            [w.get("company_id") for w in who] == ["beta", "acme", None], who)
    r.check("the drift list is in the section",
            (rec.get("drift") or {}).get("count") == 1, rec.get("drift"))

    r.section("margin")
    m = c.get("margin") or {}
    jobs = {(j.get("job") or {}).get("key"): j for j in m.get("jobs") or []}
    r.check("five invoiced jobs in the window: project 4521 and invoices 7003-7006 "
            "(6000 is outside it)",
            sorted(jobs) == ["invoice:7003:beta", "invoice:7004:beta", "invoice:7005:beta",
                             "invoice:7006:beta", "project:4521:acme"], sorted(jobs))
    p = jobs.get("project:4521:acme") or {}
    r.check("project 4521 rolls up its two invoices: realized 1,000,000 - 200,000 bills "
            "- 10,000 expense = 790,000", _v(p.get("realized_margin_usd")) == 790000,
            p.get("realized_margin_usd"))
    r.check("... PO-costed 1,000,000 - 200,000 = 800,000", _v(p.get("po_costed_margin_usd")) == 800000,
            p.get("po_costed_margin_usd"))
    r.check("... quoted 4,000 (CRM revenue - cost), named quoted",
            (p.get("quoted_margin_usd") or {}).get("value") == 4000
            and "quoted" in str((p.get("quoted_margin_usd") or {}).get("basis")), p.get("quoted_margin_usd"))
    reasons = {k: (j.get("realized_margin_usd") or {}).get("excluded") for k, j in jobs.items()}
    r.check("realized: a PO with no bill is cost_not_billed_yet (7003, 7004)",
            reasons.get("invoice:7003:beta") == {"cost_not_billed_yet": 1}
            and reasons.get("invoice:7004:beta") == {"cost_not_billed_yet": 1}, reasons)
    r.check("... a job with no legs is cost_incomplete (7005), never 100% margin",
            reasons.get("invoice:7005:beta") == {"cost_incomplete": 1}, reasons)
    r.check("... a job QuickBooks has not invoiced is no_qbo_invoice (7006)",
            reasons.get("invoice:7006:beta") == {"no_qbo_invoice": 1}, reasons)
    pc = {k: (j.get("po_costed_margin_usd") or {}) for k, j in jobs.items()}
    r.check("PO-costed 7003: 300,000 - PO 1103's 100,000 = 200,000",
            _v(pc.get("invoice:7003:beta")) == 200000, pc.get("invoice:7003:beta"))
    r.check("... 7004: a leg's PO (9999) is not a QuickBooks PO -> po_not_resolved",
            pc.get("invoice:7004:beta", {}).get("excluded") == {"po_not_resolved": 1},
            pc.get("invoice:7004:beta"))
    r.check("... 7005: no leg carries a PO -> no_po_on_job",
            pc.get("invoice:7005:beta", {}).get("excluded") == {"no_po_on_job": 1},
            pc.get("invoice:7005:beta"))
    tot = m.get("realized_margin_usd") or {}
    r.check("the realized total: 790,000 over 1 of 5 jobs", _v(tot) == 790000
            and tot.get("counted") == 1 and tot.get("population") == 5, tot)
    basis = str(tot.get("basis"))
    r.check("the realized basis states jobs counted, the share of COGS attributed and "
            "the unattributed dollars",
            "1 of 5 jobs" in basis and "82.7%" in basis and "$440.00" in basis, basis)
    at = m.get("cogs_attribution") or {}
    r.check("window COGS 254,000 (a bill counts as its positive Amount, an expense or "
            "check as its negative one, a vendor credit takes 2,000 off): attributed "
            "210,000 (two bills + one expense), unattributed 44,000",
            _v(at.get("cogs_usd")) == 254000 and _v(at.get("attributed_usd")) == 210000
            and _v(at.get("unattributed_usd")) == 44000, at)
    pt = m.get("po_costed_margin_usd") or {}
    r.check("the PO-costed total: 1,000,000 over 2 of 5 jobs, and it says so in its basis",
            _v(pt) == 1000000 and pt.get("counted") == 2
            and "PO-costed: excludes costs paid directly as expenses, so it overstates margin"
            in str(pt.get("basis")), pt)
    r.check("the three margins are separate figures, never one",
            {"quoted_margin_usd", "realized_margin_usd", "po_costed_margin_usd"} <= set(m))

    r.section("expenses")
    e = c.get("expenses") or {}
    w, l30 = e.get("window") or {}, e.get("last_30_days") or {}
    r.check("window: COGS 254,000, overhead 5,000, split across accounts 7,000 -- all "
            "as positive costs, whatever sign the export gave the row",
            (_v(w.get("cogs_usd")), _v(w.get("overhead_usd")), _v(w.get("split_usd")))
            == (254000, 5000, 7000), (w.get("cogs_usd"), w.get("overhead_usd"), w.get("split_usd")))
    r.check("... a bill payment is not spend a second time",
            _v(w.get("total_usd")) == 266000, w.get("total_usd"))
    pd = w.get("paydowns_usd") or {}
    r.check("debt, card and tax payments are their own line: 12,600 over 3 rows",
            _v(pd) == 12600 and pd.get("counted") == 3, pd)
    r.check("... excluded from operating spend and COGS (the totals above are unchanged)",
            _v(w.get("total_usd")) == 266000 and _v(w.get("cogs_usd")) == 254000)
    r.check("... and the rule is written in the basis, not applied silently",
            "Payable" in str(pd.get("basis")) and "Note" in str(pd.get("basis"))
            and "Tax Payment" in str(pd.get("basis"))
            and "Debt, card and tax payments" in str((w.get("total_usd") or {}).get("basis")), pd)
    r.check("... a paydown vendor is not an operating vendor row",
            not any(x.get("vendor") in ("Harbor Lending", "Bluefin Card Services",
                                        "State Revenue Office") for x in w.get("by_vendor") or []),
            [x.get("vendor") for x in w.get("by_vendor") or []])
    r.check("... its accounts are listed under the paydown line",
            sorted(x.get("account") for x in w.get("paydowns_by_account") or [])
            == ["Company Card Payable", "Note: Truck Loan", "Sales Tax Payable"],
            w.get("paydowns_by_account"))
    r.check("a transaction type with no known sign is left out of spend and named, "
            "never guessed", (e.get("other_types") or {}) == {"Credit Card Credit": 1},
            e.get("other_types"))
    by_split = {x.get("account"): _v(x.get("amount_usd")) for x in w.get("by_split_account") or []}
    r.check("by split account, a null split its own labelled line",
            by_split == {COGS: 254000, "Office Supplies": 5000, None: 7000}, by_split)
    vend = [(x.get("vendor"), x.get("vendor_id"), _v(x.get("amount_usd"))) for x in w.get("by_vendor") or []]
    r.check("by vendor AS EXPORTED: two QuickBooks names for one CRM vendor stay two rows",
            ("Trueline Metals", "trueline", 30000) in vend
            and ("Trueline Metals Inc", "trueline", 1000) in vend, vend)
    r.check("... a vendor with no CRM record keeps its row, vendor_id null",
            ("Keystone Fasteners", None, 32000) in vend, vend)
    r.check("... ranked, largest first", [v[2] for v in vend] == sorted((v[2] for v in vend), reverse=True),
            vend)
    r.check("last 30 days (2026-03-02..03-31): COGS 29,000 (the vendor credit is in it), "
            "overhead 5,000, split 7,000",
            (_v(l30.get("cogs_usd")), _v(l30.get("overhead_usd")), _v(l30.get("split_usd")))
            == (29000, 5000, 7000), l30)

    r.section("tiles")
    t = c.get("tiles") or {}
    r.check("tiles: cash = the bank total, open receivable = QuickBooks open, "
            "realized coverage = 1 of 5, window spend = the window total",
            _v(t.get("cash_usd")) == 5112345 and _v(t.get("open_receivable_usd")) == 520000
            and (t.get("realized_margin_coverage") or {}).get("counted") == 1
            and (t.get("realized_margin_coverage") or {}).get("population") == 5
            and _v(t.get("window_spend_usd")) == 266000, t)

    # ---- the export path ----------------------------------------------------
    r.section("from exports")
    load_vendor(server, connector=False)
    c, _ = cfo(st)
    m = c.get("margin") or {}
    tot = m.get("realized_margin_usd") or {}
    r.check("from an export no job has a realized figure: the bills are a block",
            tot.get("counted") == 0 and tot.get("value") is None
            and (tot.get("excluded") or {}).get("bills_not_linkable_from_export") == 4, tot)
    r.check("... counted, not matched by vendor, date or amount: attributed 0",
            _v((m.get("cogs_attribution") or {}).get("attributed_usd")) == 0, m.get("cogs_attribution"))
    r.check("... the basis still says all three: 0 of 5 jobs, 0.0%, $2,540.00 unattributed",
            "0 of 5 jobs" in str(tot.get("basis")) and "0.0%" in str(tot.get("basis"))
            and "$2,540.00" in str(tot.get("basis")), tot.get("basis"))
    r.check("PO-costed still reads from an export: 2 jobs",
            (m.get("po_costed_margin_usd") or {}).get("counted") == 2, m.get("po_costed_margin_usd"))
    co = (c.get("cash") or {}).get("committed_out_usd") or {}
    r.check("committed out from an export is not computable: po_status_unknown, never an estimate",
            co.get("value") is None and co.get("excluded") == {"po_status_unknown": 4}, co)

    # ---- partial and stale --------------------------------------------------
    r.section("partial and stale")
    (st.path.parent / "qbo-snapshots" / "cash_balances.json").unlink()
    c, _ = cfo(st)
    r.check("invoices but no cash: cash says what to load, receivables still read",
            (c.get("cash") or {}).get("loaded") is False
            and _v((c.get("receivables") or {}).get("open_usd")) == 520000, c.get("cash"))
    qbo_invoices(server, as_of="2026-04-01")
    c, _ = cfo(st)
    r.check("a snapshot 19 days old is marked stale in the section that reads it",
            (c.get("receivables") or {}).get("stale") is True
            and (c.get("receivables") or {}).get("snapshot_as_of") == "2026-04-01",
            {k: (c.get("receivables") or {}).get(k) for k in ("stale", "snapshot_as_of", "age_days")})

    # ---- the shapes obey the suite's invariants -------------------------------
    import test_metrics as TM
    TM_TODAY = TM.TODAY
    TM.TODAY = TODAY
    try:
        TM.check_invariants(r, "cfo", st.call("crm_metrics", report="cfo"))
    finally:
        TM.TODAY = TM_TODAY
    stored = {n: st.raw(n) for n in ("companies", "projects", "invoices", "shipments", "vendors")}
    st.call("crm_metrics", report="cfo")
    r.check("the report writes nothing",
            {n: st.raw(n) for n in stored} == stored)

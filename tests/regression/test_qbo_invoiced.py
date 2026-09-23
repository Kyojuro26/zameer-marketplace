"""Invoiced amounts from the QuickBooks snapshot, joined at read time (0.1.38, B3).

Decisions asserted, each with an obvious wrong version:

 1. THE KEY IS (Invoice, number) THROUGH _key(). A composite CRM number
    "1342 (INV 7002-100%-PAID)" is invoice 7002 -- the leading 1342 is the
    quote number, and a QuickBooks invoice 1342 is a decoy that must NOT be
    matched. A Credit Memo sharing a number is not an invoice. The customer
    name is never the key.
 2. NEVER PICK ONE. Two snapshot invoices with one number exclude the CRM
    invoice as ambiguous_qbo_match.
 3. ABSENT IS NOT MISSING. An invoice dated outside the snapshot window is
    outside_snapshot_window, never not_in_qbo_snapshot; one with no date is
    no_date; with nothing loaded every invoice is no_qbo_snapshot.
 4. QUOTED AND REALIZED NEVER BLEND. invoiced_usd and qbo_open_receivable_usd
    sit beside exposure_open_receivable_usd, which reads exactly the same
    with or without a snapshot. Split-billed jobs price here, because each
    invoice carries its own QuickBooks amount, while the CRM-basis shape
    still excludes them.
 5. QUICKBOOKS OPEN BALANCE WINS for qbo_open_receivable_usd, even on an
    invoice the CRM calls paid.
 6. THE DRIFT LIST IS TWO-WAY: QuickBooks invoices no CRM invoice carries,
    and CRM invoices in the window QuickBooks does not have, with counts and
    dollars.
 7. ONE INV RULE. The server reads the invoice number after the INV token
    exactly as pipeline/normalize.py's INV_RE does, on every sample.

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
                         project)

QROWS = [
    # num, amount_cents, open_cents, type
    ("7001", 1250000, 0, "Invoice"),
    ("7002", 250000, 100050, "Invoice"),
    ("7003", 300000, 50000, "Invoice"),
    ("7004", 10000, 10000, "Invoice"),
    ("7004", 20000, 0, "Invoice"),          # the same Num twice: never pick one
    ("1342", 999900, 999900, "Invoice"),    # the quote-number decoy
    ("7099", 4200042, 4200042, "Invoice"),  # in QuickBooks, not in the CRM
    ("7010", 55500, 0, "Credit Memo"),      # not an invoice: never the key
]


def _snapshot(server, as_of="2026-04-07"):
    rows = [{"type": t, "num": n, "date": "2026-02-01", "due_date": None,
             "name": "Someone", "memo": None, "amount_cents": a, "open_cents": o}
            for n, a, o, t in QROWS]
    server._save_qbo_snapshot("invoices", "export", as_of, "2026-01-01",
                              "2026-03-31", rows)


def _store(st):
    st.reset(
        companies=[company("acme", "Ace Manufacturing"),
                   company("beta", "Beta Works")],
        projects=[project("4521", "acme", revenue=10000),
                  project("4600", "beta", revenue=3000),
                  project("4601", "beta", revenue=8000)],
        invoices=[
            invoice("7001", "acme", project_no="4521", invoice_date="2026-01-05"),
            invoice("1342 (INV 7002-100%-PAID)", "acme", project_no="4521",
                    invoice_date="2026-02-10"),
            invoice("6900", "acme", invoice_date="2025-11-15"),
            invoice("7004", "acme", invoice_date="2026-02-20"),
            invoice("7005", "acme"),
            invoice("INV 7003", "beta", project_no="4600",
                    invoice_date="2026-03-31", payment_status="paid"),
            invoice("7010", "beta", project_no="4601", invoice_date="2026-03-01"),
        ])


def run(server, crm_dir=None):
    r = Result("qbo-invoiced", since="0.1.38")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    if not r.check("server can write a snapshot",
                   callable(getattr(server, "_save_qbo_snapshot", None))):
        return r
    tmp = Path(tempfile.mkdtemp(prefix="qboinv-"))
    real_today = server._today
    server._today = lambda: datetime.date(2026, 4, 20)
    try:
        _body(r, server, crm, tmp)
    finally:
        server._today = real_today
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _metrics(st, cid):
    got = st.call("get_company", ref=cid)
    return (got.get("company") or {}).get("metrics") or {}, got


def _body(r, server, crm, tmp):
    st = Store(server, tmp / "m" / "store")
    _store(st)

    # ---- 3. nothing loaded -------------------------------------------------
    r.section("no snapshot")
    m0, _ = _metrics(st, "acme")
    inv0 = m0.get("invoiced_usd") or {}
    r.check("with nothing loaded, invoiced_usd is null over no_qbo_snapshot",
            inv0.get("value") is None and inv0.get("counted") == 0
            and inv0.get("excluded") == {"no_qbo_snapshot": 5}, inv0)
    exposure_before = {c: _metrics(st, c)[0].get("exposure_open_receivable_usd")
                       for c in ("acme", "beta")}

    _snapshot(server)

    # ---- 1-2, 4-5. per company -----------------------------------------------
    r.section("the join")
    m, got = _metrics(st, "acme")
    inv = m.get("invoiced_usd") or {}
    r.check("acme invoiced: 7001 and INV 7002 -> 1,500,000 cents",
            inv.get("value_cents") == 1500000 and inv.get("counted") == 2,
            inv)
    r.check("... and not the decoy: 1342 is the quote number, not the invoice",
            inv.get("value_cents") != 1500000 + 999900 - 250000, inv)
    r.check("acme exclusions: one outside the window, one ambiguous, one undated",
            inv.get("excluded") == {"outside_snapshot_window": 1,
                                    "ambiguous_qbo_match": 1, "no_date": 1},
            inv.get("excluded"))
    r.check("counted + excluded == population (5)", inv.get("population") == 5, inv)
    r.check("the dollar value is the cents over 100", inv.get("value") == 15000.0,
            inv.get("value"))
    op = m.get("qbo_open_receivable_usd") or {}
    r.check("acme QuickBooks open: 0 + 100,050 cents", op.get("value_cents") == 100050
            and op.get("counted") == 2, op)
    r.check("the shape carries the snapshot's as_of and window",
            op.get("snapshot_as_of") == "2026-04-07"
            and op.get("window_start") == "2026-01-01"
            and op.get("window_end") == "2026-03-31", op)
    r.check("13 days old on 2026-04-20: stale", op.get("stale") is True
            and op.get("age_days") == 13, op)
    r.check("the basis names QuickBooks and says realized, not quoted",
            "QuickBooks" in str(inv.get("basis")) and "quoted" not in
            str(inv.get("basis")).replace("not quoted", ""), inv.get("basis"))

    ex = m.get("exposure_open_receivable_usd") or {}
    r.check("the CRM-basis exposure still excludes the split-billed pair",
            (ex.get("excluded") or {}).get("multiple_invoices_on_project") == 2, ex)
    r.check("... and reads exactly as it did with no snapshot (never blended)",
            {c: _metrics(st, c)[0].get("exposure_open_receivable_usd")
             for c in ("acme", "beta")} == exposure_before)

    mb, _ = _metrics(st, "beta")
    ob = mb.get("qbo_open_receivable_usd") or {}
    r.check("beta: the CRM calls INV 7003 paid; QuickBooks says 50,000 open, and wins",
            ob.get("value_cents") == 50000, ob)
    ib = mb.get("invoiced_usd") or {}
    r.check("beta 7010 is in the window and not in QuickBooks (the Credit Memo "
            "sharing its number is not an invoice)",
            ib.get("excluded") == {"not_in_qbo_snapshot": 1}, ib)

    # ---- per invoice ---------------------------------------------------------
    r.section("per invoice, in responses only")
    rows = {i.get("invoice_no"): i for i in
            (st.call("list_invoices", company="acme").get("invoices") or [])}
    q = rows.get("1342 (INV 7002-100%-PAID)") or {}
    r.check("a composite invoice carries qbo_amount_usd 250,000 cents",
            (q.get("qbo_amount_usd") or {}).get("value_cents") == 250000, q)
    r.check("... and qbo_open_usd 100,050 cents",
            (q.get("qbo_open_usd") or {}).get("value_cents") == 100050, q)
    a = (rows.get("7004") or {}).get("qbo_amount_usd") or {}
    r.check("the ambiguous invoice is null and says why",
            a.get("value") is None and a.get("excluded") == {"ambiguous_qbo_match": 1}, a)
    per = (m.get("qbo_invoices") or {}).get("7001") or {}
    r.check("company metrics carry the same per-invoice shapes, for the view",
            (per.get("qbo_amount_usd") or {}).get("value_cents") == 1250000, per)
    stored = json.loads((st.path / "invoices.json").read_text())
    r.check("nothing QuickBooks is persisted on an invoice",
            not any(k.startswith("qbo") for i in stored for k in i), stored[0])
    got = st.call("update_invoice", company_id="acme", invoice_no="7001",
                  fields={"qbo_amount_usd": 1})
    r.check("... and it cannot be written", got.get("ok") is False, got)

    # ---- aggregate, for chat and the header ---------------------------------
    rep = (st.call("crm_metrics", report="qbo_drift").get("reports") or {}) \
        .get("qbo_drift") or {}
    agg = rep.get("qbo_open_receivable_usd") or {}
    r.check("the store-wide QuickBooks open equals the sum of the companies",
            agg.get("value_cents") == 100050 + 50000 and agg.get("population") == 7,
            agg)

    # ---- 6. drift ------------------------------------------------------------
    r.section("the two-way drift list")
    d = (st.call("crm_metrics", report="qbo_drift").get("reports") or {}) \
        .get("qbo_drift") or {}
    w = d
    r.check("QuickBooks invoices no CRM invoice carries: 1342 and 7099",
            sorted(x.get("num") for x in w.get("rows") or []) == ["1342", "7099"]
            and w.get("count") == 2, w)
    r.check("... with their dollars: 5,199,942 cents invoiced, 5,199,942 open",
            w.get("value_cents") == 999900 + 4200042
            and (w.get("open_usd") or {}).get("value_cents") == 999900 + 4200042, w)
    r.check("... out of 7 QuickBooks invoices (the Credit Memo is not one)",
            w.get("counted") == 7, {k: w.get(k) for k in ("counted", "population")})
    c = d.get("crm_invoices_not_in_qbo") or {}
    r.check("CRM invoices in the window QuickBooks lacks: 7010 only "
            "(6900 is outside the window, 7005 undated)",
            [x.get("invoice_no") for x in c.get("rows") or []] == ["7010"]
            and c.get("count") == 1, c)
    r.check("... priced at the CRM's QUOTED figure, named as quoted",
            (c.get("quoted_usd") or {}).get("value") == 8000
            and "quoted" in str((c.get("quoted_usd") or {}).get("basis")), c)
    r.check("the ambiguous QuickBooks number is listed",
            d.get("ambiguous_qbo_numbers") == [{"num": "7004", "rows": 2}],
            d.get("ambiguous_qbo_numbers"))
    stored_after = json.loads((st.path / "invoices.json").read_text())
    r.check("the drift report writes nothing", stored_after == stored)

    # ---- a snapshot that cannot be read --------------------------------------
    snap = st.path.parent / "qbo-snapshots" / "invoices.json"
    snap.write_text("{ not json")
    m2, got = _metrics(st, "acme")
    r.check("a corrupt snapshot does not take get_company down", got.get("ok") is True, got)
    i2 = m2.get("invoiced_usd") or {}
    r.check("... every invoice reads no_qbo_snapshot, and the shape says why",
            i2.get("excluded") == {"no_qbo_snapshot": 5} and i2.get("snapshot_error"), i2)

    doc = {"kind": "invoices", "source": "export", "as_of": "2026-04-07",
           "window_start": "2026-03-31", "window_end": "2026-01-01",
           "loaded_at": "x", "rows": []}
    snap.write_text(json.dumps(doc))
    i3 = _metrics(st, "acme")[0].get("invoiced_usd") or {}
    r.check("a snapshot whose window ends before it starts is unreadable, not "
            "'every invoice outside the window'",
            i3.get("excluded") == {"no_qbo_snapshot": 5} and i3.get("snapshot_error"), i3)

    # ---- one QuickBooks invoice, two CRM invoices (found on the real data) ---
    r.section("a QuickBooks invoice claimed by two CRM invoices counts for neither")
    st.reset(companies=[company("acme", "Ace Manufacturing"),
                        company("beta", "Beta Works")],
             invoices=[invoice("7001", "acme", invoice_date="2026-01-05"),
                       invoice("7001", "beta", invoice_date="2026-01-06"),
                       invoice("7003", "beta", invoice_date="2026-03-31")])
    _snapshot(server)
    ma, mb = _metrics(st, "acme")[0], _metrics(st, "beta")[0]
    r.check("both claimants are excluded as qbo_match_shared -- the customer "
            "name is never the key, so nothing can say which one it is",
            (ma.get("invoiced_usd") or {}).get("excluded") == {"qbo_match_shared": 1}
            and (mb.get("invoiced_usd") or {}).get("excluded") == {"qbo_match_shared": 1},
            (ma.get("invoiced_usd"), mb.get("invoiced_usd")))
    tot = (st.call("crm_metrics", report="qbo_drift").get("reports") or {}) \
        .get("qbo_drift", {}).get("invoiced_usd") or {}
    r.check("store-wide, QuickBooks invoice 7001 is not counted twice: 7003 only",
            tot.get("value_cents") == 300000 and tot.get("counted") == 1, tot)

    # ---- a CRM invoice that names two invoices ("A and B") -------------------
    r.section("a pair: both must match, and it prices their sum")
    pair_rows = [("7101", 100000, 40000), ("7102", 20000, 5000),
                 ("7103", 30000, 30000), ("7105", 1000, 1000), ("7106", 2000, 0),
                 ("7107", 500, 500), ("7108", 700, 700)]
    server._save_qbo_snapshot("invoices", "export", "2026-04-07", "2026-01-01",
                              "2026-03-31",
                              [{"type": "Invoice", "num": n, "amount_cents": a,
                                "open_cents": o} for n, a, o in pair_rows])
    st.reset(companies=[company("acme", "Ace Manufacturing"),
                        company("beta", "Beta Works")],
             invoices=[invoice("7101 and 7102", "acme", invoice_date="2026-02-01"),
                       invoice("7103 & 7104", "acme", invoice_date="2026-02-01"),
                       invoice("7105 and 7106", "beta", invoice_date="2026-02-01"),
                       invoice("7105", "acme", invoice_date="2026-02-01"),
                       invoice("7107, 7108", "beta", invoice_date="2026-02-01"),
                       invoice("7107 and 7108 and 7109", "beta",
                               invoice_date="2026-02-01")])
    rows_ = {i.get("invoice_no"): i for i in
             (st.call("list_invoices").get("invoices") or [])}
    pa = rows_.get("7101 and 7102") or {}
    r.check("'7101 and 7102' names both: amount 100,000 + 20,000 cents",
            (pa.get("qbo_amount_usd") or {}).get("value_cents") == 120000, pa)
    r.check("... and open 40,000 + 5,000 cents",
            (pa.get("qbo_open_usd") or {}).get("value_cents") == 45000, pa)
    pb = (rows_.get("7103 & 7104") or {}).get("qbo_amount_usd") or {}
    r.check("'7103 & 7104' with only 7103 in QuickBooks prices nothing: "
            "partial_qbo_match, never half",
            pb.get("value") is None and pb.get("excluded") == {"partial_qbo_match": 1}, pb)
    for n in ("7105 and 7106", "7105"):
        sh = (rows_.get(n) or {}).get("qbo_amount_usd") or {}
        r.check(f"{n!r}: a pair's number counts toward qbo_match_shared like any other",
                sh.get("excluded") == {"qbo_match_shared": 1}, sh)
    for n in ("7107, 7108", "7107 and 7108 and 7109"):
        sh = (rows_.get(n) or {}).get("qbo_amount_usd") or {}
        r.check(f"{n!r} is not a pair: read as one number, as before",
                sh.get("excluded") == {"not_in_qbo_snapshot": 1}, sh)
    d2 = (st.call("crm_metrics", report="qbo_drift").get("reports") or {}) \
        .get("qbo_drift") or {}
    r.check("the drift list counts the pair's invoices as carried by the CRM "
            "(7107 and 7108 stay drift: nothing names them as a pair)",
            sorted(x.get("num") for x in d2.get("rows") or []) == ["7107", "7108"],
            [x.get("num") for x in d2.get("rows") or []])
    stored = json.loads((st.path / "invoices.json").read_text())
    r.check("the pair rule writes nothing",
            [i.get("invoice_no") for i in stored][0] == "7101 and 7102"
            and not any(k.startswith("qbo") for i in stored for k in i))

    # ---- 7. one INV rule ---------------------------------------------------
    r.section("the INV token, as the importer reads it")
    if not r.check("the server has one invoice-number reader",
                   callable(getattr(server, "_qbo_invoice_key", None))):
        return
    import importlib.util
    p = crm / "pipeline" / "normalize.py"
    spec = importlib.util.spec_from_file_location("_nrm_inv", p)
    nrm = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(p.parent))
    try:
        spec.loader.exec_module(nrm)
    finally:
        sys.path.remove(str(p.parent))
    samples = ["1342 (INV 1191-100%-PAID)", "INV 7003", "4521 (INV-9001)",
               "4522 (inv#9002-50%)", "4523 (INV 9003-PAID)", "7001", " 7001 ",
               "4530 and 4531", "Check", "", "INVOICE 12", "INV", "5 (INV 12) (INV 34)"]
    bad = []
    for s in samples:
        m_ = nrm.INV_RE.search(s)
        want = server._key(m_.group(1) if m_ else s)
        if server._qbo_invoice_key(s) != want:
            bad.append((s, server._qbo_invoice_key(s), want))
    r.check("the server's invoice number equals the importer's INV_RE reading "
            "on every sample", not bad, bad)

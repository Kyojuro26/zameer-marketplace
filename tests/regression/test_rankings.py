"""Rankings: what drives the business, as a ranked table (0.1.42, Phase F).

crm_metrics(report="rankings", metric, group_by, status, year, limit). Decisions
asserted, each with an obvious wrong version:

 1. SIX METRICS: quoted_revenue, quoted_gross_profit, quoted_margin_pct,
    qbo_invoiced (needs a snapshot), po_costed_margin_pct (needs snapshots;
    carries the "overstates margin" warning), project_count. Money in cents.
 2. quoted_margin_pct is computed only where revenue > 0 (else
    no_revenue_on_project), says "quoted" in name and basis, and a GROUP's
    margin is total gross profit over total revenue -- never an average of
    project percentages.
 3. FOUR GROUPINGS: project, customer, year, owner. Every group row carries its
    value as a shape: how many projects fed it, how many were excluded and why.
    Owner rows group a project under its owners as stored (initials), a
    project with several under their combination so nothing counts twice; the
    report says how many projects have an owner at all.
 4. FILTERS: status won (default) | pending | lost | all; year one or all.
 5. CONCENTRATION: the top 5 and top 10 rows' share of the counted total, for
    the additive metrics; for a percentage it is null and says why.

Names are invented.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)


def P(no, cid, status, year, rev, cost, owner=None):
    return project(no, cid, status=status, year=year, revenue=rev, total_cost=cost,
                   owner=owner or [], description=f"job {no}")


def seed(st):
    st.reset(
        companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works"),
                   company("gamma", "Gamma Tooling")],
        projects=[
            P("4521", "acme", "won", 2026, 10000, 6000, ["AB"]),
            P("4522", "acme", "won", 2025, 5000, 4500),
            P("4600", "beta", "won", 2026, 20000, 12000, ["CD"]),
            P("4601", "beta", "won", 2026, 0, 100),          # revenue 0: no margin
            P("4602", "beta", "won", 2026, 3000, None),      # no cost: no GP
            P("4700", "gamma", "won", 2026, None, 500),      # no revenue
            P("4701", "gamma", "pending", 2026, 7000, 5000),
            P("4702", "gamma", "lost", 2025, 9000, 8000),
            P("4800", "gamma", "won", 2026, 1000, 200, ["AB", "CD"]),
            P("4803", "gamma", "won", 2026, 500, 100)],
        invoices=[invoice("7001", "acme", project_no="4521", invoice_date="2026-02-01"),
                  invoice("7002", "beta", project_no="4600", invoice_date="2026-02-02"),
                  invoice("7003", "beta", project_no="4602", invoice_date="2026-02-03"),
                  invoice("7004", "gamma", project_no="4800", invoice_date="2026-02-04")],
        shipments=[shipment("4521-L1", "4521", "acme", vendor_po_raw="PO # 1101"),
                   shipment("4600-L1", "4600", "beta", vendor_po_raw="PO # 1102"),
                   shipment("4800-L1", "4800", "gamma", vendor_po_raw="no PO yet")])


def snapshots(server):
    inv = lambda num, amt: {"type": "Invoice", "num": num, "date": "2026-02-01",  # noqa: E731
                            "due_date": None, "name": "x", "amount_cents": amt,
                            "open_cents": 0}
    server._save_qbo_snapshot("invoices", "export", "2026-04-18", "2026-01-01",
                              "2026-03-31", [inv("7001", 600000), inv("7002", 1800000),
                                             inv("7004", 90000)])
    po = lambda num, amt: {"vendor": "Cobalt Freight", "date": "2026-01-10",  # noqa: E731
                           "type": "Purchase Order", "num": num, "posting": False,
                           "account": None, "split_account": None, "amount_cents": amt}
    server._save_qbo_snapshot("vendor_transactions", "export", "2026-04-18", "2026-01-01",
                              "2026-03-31", [po("1101", 350000), po("1102", 1250000)])


def rank(st, **kw):
    got = st.call("crm_metrics", report="rankings", **kw)
    return (got.get("reports") or {}).get("rankings") or {}, got


def run(server, crm_dir=None):
    r = Result("rankings", since="0.1.42")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    tmp = Path(tempfile.mkdtemp(prefix="crmrank-"))
    try:
        _body(r, server, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _v(sh):
    return (sh or {}).get("value_cents") if "value_cents" in (sh or {}) else (sh or {}).get("value")


def _rows(rk, metric):
    return [(x.get("key"), _v(x.get(metric))) for x in rk.get("rows") or []]


def _body(r, server, tmp):
    st = Store(server, tmp / "m" / "store")
    seed(st)

    r.section("defaults: won, by customer")
    rk, got = rank(st, metric="quoted_revenue", group_by="customer")
    if not r.check("crm_metrics(report='rankings') answers", got.get("ok") is True and bool(rk), got):
        return
    r.check("won by default; customers ranked by quoted revenue: beta 23,000, acme 15,000, "
            "gamma 1,500 (in cents)",
            _rows(rk, "quoted_revenue") == [("beta", 2300000), ("acme", 1500000), ("gamma", 150000)],
            _rows(rk, "quoted_revenue"))
    g = next((x for x in rk.get("rows") or [] if x.get("key") == "gamma"), {})
    sh = g.get("quoted_revenue") or {}
    r.check("a customer row says how many projects fed it and how many were excluded, and why",
            sh.get("counted") == 2 and sh.get("excluded") == {"no_revenue_on_project": 1}, sh)
    tot = rk.get("quoted_revenue") or {}
    r.check("the total: 39,500 over 7 of 8 won projects", _v(tot) == 3950000
            and tot.get("counted") == 7 and tot.get("population") == 8, tot)
    c = rk.get("concentration") or {}
    r.check("concentration by customer: 3 rows, so top 5 and top 10 are all of it",
            c.get("top5_share") == 1.0 and c.get("top10_share") == 1.0, c)

    r.section("by project, and the concentration line")
    rk, _ = rank(st, metric="quoted_revenue", group_by="project")
    r.check("projects ranked, largest first", [k for k, _v_ in _rows(rk, "quoted_revenue")][:3]
            == ["4600|beta", "4521|acme", "4522|acme"], _rows(rk, "quoted_revenue"))
    c = rk.get("concentration") or {}
    r.check("top 5 of 7 projects = 39,000 / 39,500; top 10 = all",
            abs((c.get("top5_share") or 0) - 39000 / 39500) < 1e-9 and c.get("top10_share") == 1.0, c)
    r.check("... and the line says what it is a share of",
            "counted total" in str(c.get("basis")), c.get("basis"))

    r.section("quoted margin")
    rk, _ = rank(st, metric="quoted_margin_pct", group_by="customer")
    m = {x.get("key"): x.get("quoted_margin_pct") for x in rk.get("rows") or []}
    r.check("a customer's margin is total GP over total revenue: acme 4,500 / 15,000 = 30%, "
            "not the 25% average of 40% and 10%",
            abs(((m.get("acme") or {}).get("value") or 0) - 0.30) < 1e-9, m.get("acme"))
    r.check("revenue 0 is excluded as no_revenue_on_project, no cost as no_cost_on_project",
            (m.get("beta") or {}).get("excluded") == {"no_revenue_on_project": 1, "no_cost_on_project": 1}
            and abs(((m.get("beta") or {}).get("value") or 0) - 0.40) < 1e-9, m.get("beta"))
    r.check("the margin says quoted in its name and its basis",
            "quoted" in str((rk.get("quoted_margin_pct") or {}).get("basis")))
    r.check("a percentage has no concentration line, and says why",
            (rk.get("concentration") or {}).get("top5_share") is None
            and "not additive" in str((rk.get("concentration") or {}).get("basis")),
            rk.get("concentration"))
    rk, _ = rank(st, metric="quoted_gross_profit", group_by="year")
    r.check("gross profit by year: 2026 = 4,000 + 8,000 + (-100) + 800 + 400; 2025 = 500",
            _rows(rk, "quoted_gross_profit") == [("2026", 1310000), ("2025", 50000)],
            _rows(rk, "quoted_gross_profit"))

    r.section("owner")
    rk, _ = rank(st, metric="quoted_revenue", group_by="owner")
    r.check("owners as stored; several owners are one combined row, never counted twice",
            _rows(rk, "quoted_revenue") == [("CD", 2000000), ("AB", 1000000), ("AB + CD", 100000)],
            _rows(rk, "quoted_revenue"))
    r.check("projects with no owner are excluded as no_owner",
            ((rk.get("quoted_revenue") or {}).get("excluded") or {}).get("no_owner") == 5,
            rk.get("quoted_revenue"))
    r.check("the report says how many projects have an owner at all",
            "3 of 10 projects have an owner" in str(rk.get("owner_coverage")), rk.get("owner_coverage"))

    r.section("filters")
    rk, _ = rank(st, metric="project_count", group_by="customer", status="all")
    r.check("status all: every project counts -- gamma 5, beta 3, acme 2",
            _rows(rk, "project_count") == [("gamma", 5), ("beta", 3), ("acme", 2)],
            _rows(rk, "project_count"))
    rk, _ = rank(st, metric="quoted_revenue", group_by="project", status="pending")
    r.check("status pending: only the pending project", _rows(rk, "quoted_revenue")
            == [("4701|gamma", 700000)], _rows(rk, "quoted_revenue"))
    rk, _ = rank(st, metric="quoted_revenue", group_by="project", year=2025)
    r.check("year 2025, won: only 4522", _rows(rk, "quoted_revenue") == [("4522|acme", 500000)],
            _rows(rk, "quoted_revenue"))
    rk, _ = rank(st, metric="quoted_revenue", group_by="project", limit=2)
    r.check("limit 2: two rows, and the report says how many there were",
            len(rk.get("rows") or []) == 2 and rk.get("rows_total") == 8, rk.get("rows_total"))
    rk, _ = rank(st, metric="quoted_revenue", group_by="project")
    r.check("a project with no value is still a row, null and last, saying why",
            (rk.get("rows") or [{}])[-1].get("key") == "4700|gamma"
            and ((rk.get("rows") or [{}])[-1].get("quoted_revenue") or {}).get("excluded")
            == {"no_revenue_on_project": 1}, (rk.get("rows") or [{}])[-1])
    for label, kw in (("an unknown metric", {"metric": "vibes"}),
                      ("an unknown grouping", {"metric": "quoted_revenue", "group_by": "rep"}),
                      ("an unknown status", {"metric": "quoted_revenue", "status": "open"})):
        got = st.call("crm_metrics", report="rankings", **kw)
        r.check(f"refused: {label}", got.get("ok") is False and "_raised" not in got, got)

    r.section("QuickBooks metrics")
    rk, _ = rank(st, metric="qbo_invoiced", group_by="project")
    r.check("with nothing loaded, qbo_invoiced reads null over no_qbo_snapshot",
            (rk.get("qbo_invoiced") or {}).get("value") is None
            and set(((rk.get("qbo_invoiced") or {}).get("excluded") or {})) == {"no_qbo_snapshot"},
            rk.get("qbo_invoiced"))
    if not callable(getattr(server, "_save_qbo_snapshot", None)):
        return
    snapshots(server)
    rk, _ = rank(st, metric="qbo_invoiced", group_by="project")
    r.check("invoiced by project: 4600 18,000, 4521 6,000, 4800 900",
            [(k, v) for k, v in _rows(rk, "qbo_invoiced") if v is not None]
            == [("4600|beta", 1800000), ("4521|acme", 600000), ("4800|gamma", 90000)],
            _rows(rk, "qbo_invoiced"))
    r.check("... a project with no invoice is no_qbo_invoice; one whose invoice QuickBooks "
            "lacks says so",
            (rk.get("qbo_invoiced") or {}).get("excluded")
            == {"no_qbo_invoice": 4, "not_in_qbo_snapshot": 1},
            rk.get("qbo_invoiced"))
    rk, _ = rank(st, metric="po_costed_margin_pct", group_by="project")
    pm = {x.get("key"): x.get("po_costed_margin_pct") for x in rk.get("rows") or []}
    r.check("PO-costed margin: 4521 (6,000 - 3,500) / 6,000; 4600 (18,000 - 12,500) / 18,000",
            abs(((pm.get("4521|acme") or {}).get("value") or 0) - 2500 / 6000) < 1e-9
            and abs(((pm.get("4600|beta") or {}).get("value") or 0) - 5500 / 18000) < 1e-9, pm)
    r.check("... a job whose legs carry no PO is no_po_on_job, as in the CFO report",
            (pm.get("4800|gamma") or {}).get("excluded") == {"no_po_on_job": 1}, pm.get("4800|gamma"))
    r.check("... and it carries its warning",
            "PO-costed: excludes costs paid directly as expenses, so it overstates margin"
            in str((rk.get("po_costed_margin_pct") or {}).get("basis")))

    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("_metrics_invariants",
                                         Path(__file__).resolve().parent / "test_metrics.py")
    TM = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(TM)
    for kw in ({"metric": "quoted_margin_pct", "group_by": "customer"},
               {"metric": "po_costed_margin_pct", "group_by": "owner"},
               {"metric": "qbo_invoiced", "group_by": "year", "status": "all"}):
        TM.check_invariants(r, f"rankings {kw}", st.call("crm_metrics", report="rankings", **kw))
    before = st.raw("projects")
    rank(st, metric="quoted_revenue")
    r.check("rankings write nothing", st.raw("projects") == before)

    r.section("projects with no number are still separate projects")
    nn = Store(server, tmp / "nn" / "store")
    nn.reset(companies=[company("acme", "Ace Manufacturing")],
             projects=[P("", "acme", "won", 2026, 1000, 500), P(None, "acme", "won", 2026, 3000, 1000),
                       P("4521", "acme", "won", 2026, 2000, 1500)])
    rk, _ = rank(nn, metric="quoted_revenue", group_by="project")
    r.check("two numberless projects of one customer are two rows, not one merged row",
            [v for _k, v in _rows(rk, "quoted_revenue")] == [300000, 200000, 100000]
            and len({k for k, _v in _rows(rk, "quoted_revenue")}) == 3, _rows(rk, "quoted_revenue"))
    r.check("... and a numberless row says it has no number",
            all("no number" in str(x.get("label")) for x in rk.get("rows") or []
                if not x.get("project_no")), [x.get("label") for x in rk.get("rows") or []])

    r.section("the built page embeds the default ranking")
    import subprocess
    crm = Path(server.__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, str(crm / "view" / "build_view.py"),
                          "--store", str(st.path), "--out", str(tmp / "page.html")],
                         capture_output=True, text=True)
    html = (tmp / "page.html").read_text() if (tmp / "page.html").exists() else ""
    r.check("won quoted revenue by customer, as the server ranks it",
            '"rankings": {"metric": "quoted_revenue", "group_by": "customer", "status": "won"' in html
            and '"rows": [{"key": "beta"' in html, (out.stdout + out.stderr)[-300:])

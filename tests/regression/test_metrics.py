"""Derived metrics: every number carries its own denominator.

Found in 0.1.35. The app's "Open receivables" tile summed 8 projects out of
261 and the Receivables total priced 1 invoice out of 140, and both looked
authoritative. Neither figure said what it had counted, what it had left out,
or why. The fix is not a better number; it is a SHAPE that cannot be built
without saying so:

    {"value": ..., "unit": ..., "counted": n, "population": N,
     "excluded": {reason: k, ...}, "basis": "...", "as_of": "YYYY-MM-DD"?}

Invariants, asserted on every shape in every response here:
  * counted + sum(excluded) == population   (each record excluded ONCE)
  * value is None  <=>  counted == 0        (the zero-population rule)
  * every exclusion reason is in the closed vocabulary
  * basis is non-empty; anything profit-shaped says "quoted"
  * as_of is present exactly on the metrics that depend on today (the
    walker knows which: oldest_overdue_days and everything under
    receivables_ageing)

The clock is frozen at 2026-09-01. Expected numbers below are hand-derived
from the fixture and would drift with the wall clock otherwise.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)

TODAY = date(2026, 9, 1)

VOCAB = {
    # money
    "no_project_link", "no_revenue_on_project", "no_cost_on_project", "paid",
    "not_won", "no_won_revenue", "multiple_invoices_on_project",
    # dates
    "no_date", "unparseable_date", "ship_before_project_date",
    # legs
    "no_shipment", "no_shipped_leg", "ship_date_is_estimate", "not_yet_shipped",
    "cancelled", "no_vendor_on_leg", "no_eta",
    # QuickBooks snapshot joins (0.1.38)
    "no_qbo_snapshot", "ambiguous_qbo_match", "outside_snapshot_window",
    "not_in_qbo_snapshot", "qbo_match_shared", "partial_qbo_match",
}

REPORTS = ("customer_concentration", "receivables_ageing", "vendor_on_time",
           "qbo_drift")


# ------------------------------------------------------------- fixture A ---
# Generic names only: this repo is public and swept for identifying content.

def fixture_a():
    companies = [
        company("acme", "Ace Manufacturing"),
        company("beta", "Beta Ltd"),
        company("gamma", "Gamma Works"),                 # no projects, no invoices
        company("vend1", "Vendor One", role="vendor"),
        company("lead1", "Lead One", role="lead"),
        company("ghost", "Ghost Co", archived=True),     # archived customer
    ]
    projects = [
        project("4521", "acme", status="won", revenue=100000, total_cost=60000,
                date="2026-01-10 00:00:00", year=2026),
        project("4522", "acme", status="won", revenue=50000, total_cost=None,
                date="2026-03-01 00:00:00", year=2026),
        project("4523", "beta", status="won", revenue=30000, total_cost=20000,
                date=None, year=2025),
        project("4524", "beta", status="pending", revenue=20000, total_cost=15000,
                date="2026-02-01 00:00:00", year=2026),
        project("4525", "acme", status="won", revenue=None, total_cost=None,
                date="2026-02-01 00:00:00", year=2026),
        project("4526", "beta", status="won", revenue=10000, total_cost=4000,
                date="bad date", year="2026"),           # a TEXT year, as chat writes them
        # never in any population
        project("9001", "ghost", status="won", revenue=999999, year=2026),
        project("4599", "acme", status="won", revenue=777777, year=2026,
                archived=True),
    ]
    def leg(sid, pno, cid, **kw):
        return shipment(sid, pno, cid, **kw)
    shipments = [
        # 4521 -- four judged legs, one no-vendor, one on hold
        leg("4521-L1", "4521", "acme", vendor_id="v1", eta="2026-02-01",
            ship_date="2026-01-30 00:00:00", stage="Shipped"),        # early 2
        leg("4521-L2", "4521", "acme", vendor_id="v1", eta="2026-02-10",
            ship_date="2026-02-15 00:00:00", stage="Shipped"),        # late 5
        leg("4521-L3", "4521", "acme", vendor_id=None,
            ship_date="2026-01-20 00:00:00", stage="Shipped"),        # no vendor; EARLIEST
        leg("4521-L4", "4521", "acme", vendor_id="v1", eta="2026-01-01",
            stage="On Hold"),                                         # not yet shipped
        leg("4521-L5", "4521", "acme", vendor_id="v3", eta="2026-02-20",
            ship_date="2026-02-20 00:00:00", stage="Shipped"),        # on time, equal
        leg("4521-L6", "4521", "acme", vendor_id="v3", eta="2026-04-01",
            ship_date="2026-04-10 00:00:00", stage="Delivered"),      # late 9
        # 4522 -- its only leg carries an estimate
        leg("4522-L1", "4522", "acme", vendor_id="v3", eta="2026-04-01",
            ship_date="EST 4/01/26", stage="Shipped"),                # estimate
        # 4523 -- ordered past its ETA, an unreadable ETA, a shipped leg with no date
        leg("4523-L1", "4523", "beta", vendor_id="v2", eta="2026-05-01",
            stage="Ordered"),
        leg("4523-L2", "4523", "beta", vendor_id="v2", eta="garbage",
            ship_date="2026-04-01 00:00:00", stage="Shipped"),
        leg("4523-L3", "4523", "beta", vendor_id="v2", eta="2026-05-01",
            ship_date=None, stage="Shipped"),
        # 4525 -- shipped BEFORE the project's date
        leg("4525-L1", "4525", "acme", vendor_id="v1", eta="2026-01-20",
            ship_date="2026-01-15 00:00:00", stage="Shipped"),
        # 4526 -- a cancelled leg with late-looking dates, and a leg with no ETA
        leg("4526-L1", "4526", "beta", vendor_id="v2", eta="2026-01-01",
            ship_date="2026-06-01 00:00:00", stage="Cancelled"),
        leg("4526-L2", "4526", "beta", vendor_id="v3", eta=None,
            ship_date="2026-03-05 00:00:00", stage="Shipped"),
        # never in the population
        leg("9001-L1", "9001", "ghost", vendor_id="v1", eta="2026-01-01",
            ship_date="2026-06-01 00:00:00", stage="Shipped"),
        leg("4599-L1", "4599", "acme", vendor_id="v1", eta="2026-01-01",
            ship_date="2026-06-01 00:00:00", stage="Shipped"),
    ]
    invoices = [
        invoice("7001", "acme", project_no="4521", payment_status="open",
                invoice_date="2026-06-01 00:00:00"),           # due 07-01, 62 late
        invoice("7002", "acme", project_no="4521", payment_status="partial:30%",
                due_on="2026-08-20"),                          # 12 late, 70000
        invoice("7003", "acme", project_no="4522", payment_status="open",
                invoice_date="2026-08-25"),                    # due 09-24, not yet
        invoice("7004", "acme", project_no="4525", payment_status="open",
                invoice_date="2026-01-01"),                    # 213 late, unpriced
        invoice("7005", "acme", project_no=None, payment_status="open",
                invoice_date="2026-07-01"),                    # 32 late, unlinked
        invoice("7006", "acme", project_no="4521", payment_status="paid",
                invoice_date="2026-01-01"),
        invoice("7007", "acme", project_no=None, payment_status="open",
                invoice_date="not a date"),                    # no due date
        invoice("7008", "acme", project_no="4521", payment_status="open",
                due_on="someday"),                             # unreadable due
        invoice("7009", "acme", project_no="4521", payment_status="open",
                due_on="2026-09-01"),                          # due TODAY: 0 late
        invoice("8001", "beta", project_no="4523", payment_status="open",
                invoice_date="2026-08-31"),                    # not yet due
        invoice("8002", "beta", project_no="4526", payment_status="partial:50%",
                invoice_date="2026-05-01"),                    # 93 late, 5000
        invoice("8003", "beta", project_no="4523", payment_status="paid"),
        invoice("8004", "beta", project_no=None, payment_status="open",
                invoice_date="2026-08-01"),                    # 1 late, unlinked
        invoice("8005", "beta", project_no="4521", payment_status="open",
                invoice_date="2026-08-01"),                    # ANOTHER company's project
        invoice("8006", "beta", project_no="4526", payment_status="open",
                invoice_date="2026-06-03"),                    # due 07-03: exactly 60 late
        # never in the population
        invoice("9101", "ghost", project_no="9001", payment_status="open",
                invoice_date="2026-01-01"),
        invoice("7099", "acme", project_no="4599", payment_status="open",
                invoice_date="2026-01-01"),
    ]
    vendors = [
        {"company_id": "v1", "display_name": "Vendor One"},
        {"company_id": "v2", "display_name": "Vendor Two"},
        {"company_id": "v3", "display_name": "Vendor Three"},
    ]
    return dict(companies=companies, projects=projects, shipments=shipments,
                invoices=invoices, vendors=vendors)


# ------------------------------------------------------------ the walker ---

def shapes_in(obj, path="$"):
    """Every dict carrying a `population` key, with its path."""
    out = []
    if isinstance(obj, dict):
        if "population" in obj:
            out.append((path, obj))
        for k, v in obj.items():
            out.extend(shapes_in(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(shapes_in(v, f"{path}[{i}]"))
    return out


def check_invariants(r, label, response):
    found = shapes_in(response)
    r.check(f"{label}: carries at least one shape", bool(found),
            str(response)[:160])
    for path, sh in found:
        exc = sh.get("excluded")
        ok_keys = {"value", "unit", "counted", "population", "excluded", "basis"} <= set(sh)
        r.check(f"{label} {path}: has every shape key", ok_keys, str(sorted(sh)))
        if not ok_keys or not isinstance(exc, dict):
            continue
        tally = sh["counted"] + sum(exc.values())
        r.check(f"{label} {path}: counted + excluded == population",
                tally == sh["population"],
                f"{sh['counted']} + {exc} != {sh['population']}")
        r.check(f"{label} {path}: value is null iff counted == 0",
                (sh["value"] is None) == (sh["counted"] == 0),
                f"value={sh['value']!r} counted={sh['counted']}")
        r.check(f"{label} {path}: every exclusion reason is in the vocabulary",
                set(exc) <= VOCAB, str(sorted(set(exc) - VOCAB)))
        r.check(f"{label} {path}: no zero-count exclusion is listed",
                all(v > 0 for v in exc.values()), str(exc))
        r.check(f"{label} {path}: basis is a non-empty string",
                isinstance(sh["basis"], str) and sh["basis"].strip() != "")
        r.check(f"{label} {path}: unit is a non-empty string",
                isinstance(sh["unit"], str) and sh["unit"] != "")
        leaf = path.rsplit(".", 1)[-1]
        if "profit" in leaf or "margin" in leaf:
            r.check(f"{label} {path}: a profit figure says it is quoted, in name and basis",
                    "quoted" in leaf and "quoted" in sh["basis"].lower(),
                    f"name={leaf} basis={sh['basis']!r}")
        dated = leaf == "oldest_overdue_days" or ".receivables_ageing" in path
        r.check(f"{label} {path}: as_of {'present' if dated else 'absent'}",
                ("as_of" in sh) == dated
                and (not dated or sh["as_of"] == TODAY.isoformat()),
                f"as_of={sh.get('as_of')!r} -- only metrics that depend on today carry it")
        if sh["value"] is not None:
            r.check(f"{label} {path}: value is numeric",
                    isinstance(sh["value"], (int, float))
                    and not isinstance(sh["value"], bool),
                    repr(sh["value"]))
    return found


def _m(res, *keys):
    """Dig into a response without raising -- against the baseline these
    tools do not exist and the response is an error dict."""
    cur = res
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int) and k < len(cur):
            cur = cur[k]
        else:
            return None
    return cur


def _by(rows, key, val):
    for row in rows or []:
        if isinstance(row, dict) and row.get(key) == val:
            return row
    return None


# ----------------------------------------------------------------- run ----

def run(server, crm_dir=None):
    r = Result("metrics", since="0.1.35")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:                      # the mutation runner passes None
        try:
            srv = load_server(str(crm))
        except Exception as exc:                                  # noqa: BLE001
            r.check("the server module imports", False, f"{type(exc).__name__}: {exc}")
            return r

    # ---- the clock ----------------------------------------------------------
    r.section("the clock is a hook the test can freeze")
    if not r.check("server exposes _today()", callable(getattr(srv, "_today", None)),
                   "no _today hook -- every date-relative check below would drift "
                   "with the wall clock"):
        return r
    srv._today = lambda: TODAY

    s = Store(srv)
    s.reset(**fixture_a())

    # ---- shape invariants on every response ---------------------------------
    r.section("every shape in every response obeys the invariants")
    responses = {
        "get_project(4521)": s.call("get_project", project_no="4521"),
        "list_projects": s.call("list_projects"),
        "get_company(acme)": s.call("get_company", ref="acme"),
        "get_company(gamma)": s.call("get_company", ref="gamma"),
        "list_companies": s.call("list_companies"),
        "crm_metrics": s.call("crm_metrics"),
        "crm_metrics(year=2026)": s.call("crm_metrics", year=2026),
    }
    for label, res in responses.items():
        r.check(f"{label}: ok", res.get("ok") is True, str(res)[:160])
        check_invariants(r, label, res)

    # ---- per-record: cycle time ---------------------------------------------
    r.section("project.metrics.cycle_time_days")
    lp = responses["list_projects"]
    plist = _m(lp, "projects") or []
    r.check("list_projects excludes archived projects and archived companies",
            {p.get("project_no") for p in plist} ==
            {"4521", "4522", "4523", "4524", "4525", "4526"},
            str(sorted(p.get("project_no") for p in plist)))
    cyc = {p.get("project_no"): _m(p, "metrics", "cycle_time_days") for p in plist}
    expect = {
        "4521": (10, {}),                                 # earliest leg, not latest
        "4522": (None, {"no_shipped_leg": 1}),            # only an EST date
        "4523": (None, {"no_date": 1}),
        "4524": (None, {"no_shipment": 1}),
        "4525": (None, {"ship_before_project_date": 1}),
        "4526": (None, {"unparseable_date": 1}),
    }
    for pno, (val, exc) in expect.items():
        sh = cyc.get(pno) or {}
        r.check(f"{pno} cycle_time value == {val!r}", sh.get("value") == val,
                f"got {sh.get('value')!r} excluded={sh.get('excluded')}")
        r.check(f"{pno} cycle_time excluded == {exc}", sh.get("excluded") == exc,
                f"got {sh.get('excluded')!r}")
        r.check(f"{pno} cycle_time is a population of one",
                sh.get("population") == 1, f"got {sh.get('population')!r}")
        r.check(f"{pno} cycle_time has unit days and no as_of",
                sh.get("unit") == "days" and "as_of" not in sh, str(sh)[:120])
    gp = _m(responses["get_project(4521)"], "project", "metrics")
    r.check("get_project and list_projects give the SAME metrics for 4521",
            gp == _m(_by(plist, "project_no", "4521"), "metrics"),
            f"get={gp} list={_m(_by(plist, 'project_no', '4521'), 'metrics')}")
    zc = Store(srv)
    zc.reset(companies=[company()],
             projects=[project("77", date="2026-01-01", status="won")],
             shipments=[shipment("77-L1", "77", stage="Cancelled",
                                 ship_date="2026-02-01 00:00:00"),
                        shipment("77-L2", "77", stage="Ordered",
                                 ship_date="2026-03-01 00:00:00")])
    zsh = _m(zc.call("get_project", project_no="77"), "project", "metrics",
             "cycle_time_days") or {}
    r.check("a cancelled leg, or an Ordered leg with a planned date, never supplies "
            "the ship date: legs exist but none has shipped",
            zsh.get("value") is None and zsh.get("excluded") == {"no_shipped_leg": 1},
            str(zsh)[:200])
    # Two customers can share a project number. A leg belongs to ONE of them.
    zc.reset(companies=[company(), company("beta", "Beta Ltd")],
             projects=[project("900", "beta", date="2026-01-01"),
                       project("900", "acme", date="2026-06-01")],
             shipments=[shipment("900-L1", "900", "beta", stage="Shipped",
                                 ship_date="2026-01-15 00:00:00")])
    zl = {p.get("company_id"): _m(p, "metrics", "cycle_time_days")
          for p in (_m(zc.call("list_projects"), "projects") or [])}
    r.check("a leg on beta's 900 is not lent to acme's 900",
            _m(zl, "beta", "value") == 14
            and _m(zl, "acme", "excluded") == {"no_shipment": 1},
            str(zl)[:240])
    # EST spellings, and an ETA in ISO-T form
    zc.reset(companies=[company()],
             projects=[project("1", date="2026-01-01")],
             shipments=[shipment("1-L1", "1", stage="Shipped", vendor_id="v",
                                 eta="2026-04-01T00:00:00", ship_date="Est. 4/01/26"),
                        shipment("1-L2", "1", stage="Shipped", vendor_id="v",
                                 eta="2026-04-01T00:00:00", ship_date="EST4/02/26"),
                        shipment("1-L3", "1", stage="Shipped", vendor_id="v",
                                 eta="2026-04-01T00:00:00", ship_date="EST"),
                        shipment("1-L4", "1", stage="Shipped", vendor_id="v",
                                 eta="2026-04-01T00:00:00", ship_date="2026-04-01T00:00:00")])
    zv = _m(zc.call("crm_metrics", report="vendor_on_time"), "reports", "vendor_on_time") or {}
    r.check("'Est. d' and 'ESTd' are estimates; a bare 'EST' is an unreadable date; "
            "an ISO-T ETA and ship date parse",
            zv.get("excluded") == {"ship_date_is_estimate": 2, "unparseable_date": 1}
            and zv.get("counted") == 1 and zv.get("value") == 1.0, str(zv)[:240])
    s.rebind()          # a scratch Store rebinds the server; point it back

    # ---- per-record: company money --------------------------------------------
    r.section("company.metrics: revenue, quoted gross profit, exposure, oldest overdue")
    gc = responses["get_company(acme)"]
    cm = _m(gc, "company", "metrics") or {}
    rev = cm.get("revenue_won_usd") or {}
    r.check("acme revenue_won_usd == 150000 over 2 of 3 projects",
            rev.get("value") == 150000 and rev.get("counted") == 2
            and rev.get("population") == 3
            and rev.get("excluded") == {"no_revenue_on_project": 1},
            str(rev)[:200])
    r.check("revenue is all-time and carries no as_of", "as_of" not in rev, str(rev)[:120])
    gpr = cm.get("quoted_gross_profit_usd") or {}
    r.check("acme quoted_gross_profit_usd == 40000 over 1 of 3",
            gpr.get("value") == 40000 and gpr.get("counted") == 1
            and gpr.get("excluded") == {"no_revenue_on_project": 1, "no_cost_on_project": 1},
            str(gpr)[:200])
    r.check("there is no computed per-project margin twin",
            all("metrics" not in p or not any("margin" in k or "profit" in k
                                              for k in p["metrics"])
                for p in plist),
            "a second margin definition invites the two-definitions defect")
    exp = cm.get("exposure_open_receivable_usd") or {}
    # 4521 carries five invoices (7001, 7002, 7006, 7008, 7009); before 0.1.37
    # each open one was priced at the project's full $100,000 and the four of
    # them read 370,000 -- the figure here was 420000 over 6. 4522's single
    # invoice prices; the paid 7006 is a real 0.
    r.check("acme exposure == 50000: 2 of 9 invoices, four excluded as split-billed, "
            "paid counted as 0",
            exp.get("value") == 50000 and exp.get("counted") == 2
            and exp.get("population") == 9
            and exp.get("excluded") == {"no_project_link": 2, "no_revenue_on_project": 1,
                                        "multiple_invoices_on_project": 4},
            str(exp)[:260])
    r.check("exposure basis says quoted and net of part-payments",
            "quoted" in str(exp.get("basis", "")).lower()
            and "part" in str(exp.get("basis", "")).lower(), str(exp.get("basis")))
    r.check("exposure carries no as_of", "as_of" not in exp)
    old = cm.get("oldest_overdue_days") or {}
    r.check("acme oldest_overdue_days == 213 over 6 of 9, as_of frozen today",
            old.get("value") == 213 and old.get("counted") == 6
            and old.get("excluded") == {"paid": 1, "no_date": 1, "unparseable_date": 1}
            and old.get("as_of") == "2026-09-01",
            str(old)[:220])
    bc = _m(s.call("get_company", ref="beta"), "company", "metrics") or {}
    r.check("beta revenue_won_usd == 40000, pending excluded as not_won",
            _m(bc, "revenue_won_usd", "value") == 40000
            and _m(bc, "revenue_won_usd", "excluded") == {"not_won": 1},
            str(bc.get("revenue_won_usd"))[:200])
    r.check("beta quoted_gross_profit_usd == 16000",
            _m(bc, "quoted_gross_profit_usd", "value") == 16000,
            str(bc.get("quoted_gross_profit_usd"))[:200])
    # 4523 carries 8001 and the paid 8003; 4526 carries 8002 and 8006. Only the
    # paid one prices, as 0. (Was 45000 over 4 before 0.1.37; the part-payment
    # arithmetic that figure carried is asserted on a one-invoice project below.)
    r.check("beta exposure == 0 over 1 of 6: a link to ANOTHER customer's project is "
            "no link, and both split-billed projects are excluded",
            _m(bc, "exposure_open_receivable_usd", "value") == 0
            and _m(bc, "exposure_open_receivable_usd", "counted") == 1
            and _m(bc, "exposure_open_receivable_usd", "excluded")
                == {"no_project_link": 2, "multiple_invoices_on_project": 3},
            str(bc.get("exposure_open_receivable_usd"))[:240])
    r.check("beta oldest_overdue_days == 93",
            _m(bc, "oldest_overdue_days", "value") == 93,
            str(bc.get("oldest_overdue_days"))[:200])
    lc = _m(responses["list_companies"], "companies") or []
    r.check("list_companies and get_company give the SAME metrics for acme",
            _m(_by(lc, "company_id", "acme"), "metrics") == cm and bool(cm))
    r.check("a vendor and a lead carry metrics too (populations of their own)",
            all(isinstance(_m(_by(lc, "company_id", cid), "metrics"), dict)
                for cid in ("vend1", "lead1")))

    # ---- zero population ----------------------------------------------------
    r.section("zero population: null, never zero -- and a real zero is zero")
    gm = _m(responses["get_company(gamma)"], "company", "metrics") or {}
    for k in ("revenue_won_usd", "quoted_gross_profit_usd",
              "exposure_open_receivable_usd", "oldest_overdue_days"):
        sh = gm.get(k) or {}
        r.check(f"gamma {k}: population 0 -> value null",
                sh.get("population") == 0 and sh.get("value") is None
                and sh.get("counted") == 0 and sh.get("excluded") == {},
                str(sh)[:160])
    z = Store(srv)
    z.reset(companies=[company("paidco", "Paid Co")],
            projects=[project("1", "paidco", revenue=5000, status="won")],
            invoices=[invoice("1", "paidco", project_no="1", payment_status="paid"),
                      invoice("2", "paidco", project_no="1", payment_status="paid")])
    pm = _m(z.call("get_company", ref="paidco"), "company", "metrics") or {}
    r.check("a fully paid customer's exposure is 0 with counted 2, not null",
            _m(pm, "exposure_open_receivable_usd", "value") == 0
            and _m(pm, "exposure_open_receivable_usd", "counted") == 2,
            str(pm.get("exposure_open_receivable_usd"))[:200])
    r.check("...and their oldest_overdue is null: nothing is overdue-able",
            _m(pm, "oldest_overdue_days", "value") is None
            and _m(pm, "oldest_overdue_days", "excluded") == {"paid": 2},
            str(pm.get("oldest_overdue_days"))[:200])
    z.reset(companies=[company("fresh", "Fresh Co")],
            projects=[project("1", "fresh", revenue=5000, status="won")],
            invoices=[invoice("1", "fresh", project_no="1", payment_status="open",
                              invoice_date="2026-08-30")])
    fm = _m(z.call("get_company", ref="fresh"), "company", "metrics") or {}
    r.check("an open invoice not yet due gives oldest_overdue 0, not null and not negative",
            _m(fm, "oldest_overdue_days", "value") == 0
            and _m(fm, "oldest_overdue_days", "counted") == 1,
            str(fm.get("oldest_overdue_days"))[:200])
    z.reset()
    empty = z.call("crm_metrics")
    r.check("empty store: crm_metrics ok", empty.get("ok") is True, str(empty)[:160])
    for rep in REPORTS:
        sh = _m(empty, "reports", rep) or {}
        r.check(f"empty store: {rep} value null, population 0",
                sh.get("value") is None and sh.get("population") == 0
                and sh.get("counted") == 0, str(sh)[:160])
        if rep != "receivables_ageing":
            r.check(f"empty store: {rep} rows == []", sh.get("rows") == [],
                    str(sh.get("rows"))[:80])
    for b in ("not_yet_due", "0-30", "31-60", "61-90", "90+"):
        bk = _m(empty, "reports", "receivables_ageing", "buckets", b) or {}
        r.check(f"empty store: bucket {b} count 0 and amount null",
                bk.get("count") == 0 and _m(bk, "amount_usd", "value") is None
                and _m(bk, "amount_usd", "population") == 0, str(bk)[:160])
    r.check("empty store: multiple_invoices == []",
            _m(empty, "reports", "receivables_ageing", "multiple_invoices") == [])
    check_invariants(r, "crm_metrics(empty)", empty)
    s.rebind()

    # ---- aggregate: customer concentration ----------------------------------
    r.section("crm_metrics: customer_concentration")
    cm_all = responses["crm_metrics"]
    conc = _m(cm_all, "reports", "customer_concentration") or {}
    r.check("total == 190000 over 2 of 3 customers; vendors, leads, archived not in population",
            conc.get("value") == 190000 and conc.get("counted") == 2
            and conc.get("population") == 3
            and conc.get("excluded") == {"no_won_revenue": 1}, str(conc)[:240])
    rows = conc.get("rows") or []
    r.check("rows ranked by revenue, largest first",
            [x.get("company_id") for x in rows] == ["acme", "beta"],
            str([x.get("company_id") for x in rows]))
    r.check("shares are of the counted total and sum to 1",
            rows and abs(sum(x.get("share", 0) for x in rows) - 1.0) < 1e-9
            and abs(rows[0].get("share", 0) - 150000 / 190000) < 1e-9,
            str([(x.get("company_id"), x.get("share")) for x in rows]))
    r.check("each row carries its revenue", rows and rows[0].get("revenue_won_usd") == 150000)
    r.check("concentration carries no as_of", "as_of" not in conc)
    c26 = _m(responses["crm_metrics(year=2026)"], "reports", "customer_concentration") or {}
    r.check("year=2026 -> 160000 (beta's 2025 project drops out)",
            c26.get("value") == 160000, str(c26)[:200])
    c25 = _m(s.call("crm_metrics", year=2025), "reports", "customer_concentration") or {}
    r.check("year=2025 -> 30000 over 1 of 3, acme now excluded no_won_revenue",
            c25.get("value") == 30000 and c25.get("counted") == 1
            and c25.get("excluded") == {"no_won_revenue": 2}, str(c25)[:200])
    r.check("year is compared as text, like list_projects",
            _m(s.call("crm_metrics", year="2026"), "reports",
               "customer_concentration", "value") == 160000)

    # ---- aggregate: receivables ageing --------------------------------------
    r.section("crm_metrics: receivables_ageing")
    age = _m(cm_all, "reports", "receivables_ageing") or {}
    r.check("15 live invoices; 11 aged; paid 2, no_date 1, unparseable_date 1",
            age.get("population") == 15 and age.get("counted") == 11
            and age.get("excluded") == {"paid": 2, "no_date": 1, "unparseable_date": 1}
            and age.get("as_of") == "2026-09-01", str(age)[:260])
    # Bucket COUNTS are invoice counts and did not move in 0.1.37. The amounts
    # did: every invoice on 4521, 4523 and 4526 is on a split-billed project.
    # Only 7003 (4522, not yet due) prices.
    bexp = {
        "not_yet_due": (2, 50000, 1, {"multiple_invoices_on_project": 1}),
        "0-30": (4, None, 0, {"no_project_link": 2,
                              "multiple_invoices_on_project": 2}),   # incl. due TODAY
        "31-60": (2, None, 0, {"no_project_link": 1,
                               "multiple_invoices_on_project": 1}),  # incl. exactly 60
        "61-90": (1, None, 0, {"multiple_invoices_on_project": 1}),
        "90+": (2, None, 0, {"no_revenue_on_project": 1,
                             "multiple_invoices_on_project": 1}),
    }
    for b, (cnt, amt, counted, exc) in bexp.items():
        bk = _m(age, "buckets", b) or {}
        a = bk.get("amount_usd") or {}
        r.check(f"bucket {b}: count {cnt}", bk.get("count") == cnt, str(bk)[:200])
        r.check(f"bucket {b}: amount {amt!r} over {counted} of {cnt}",
                a.get("value") == amt and a.get("counted") == counted
                and a.get("population") == cnt and a.get("excluded") == exc,
                str(a)[:220])
    r.check("bucket counts add up to the counted total",
            sum((_m(age, "buckets", b) or {}).get("count", -99) for b in bexp) == 11)
    r.check("the top-level ageing value is the count aged (unit invoices)",
            age.get("value") == 11 and age.get("unit") == "invoices", str(age)[:120])
    r.check("receivables_ageing lists the split-billed projects, per customer, and not "
            "beta's dangling 4521",
            age.get("multiple_invoices") == [
                {"project_no": "4521", "company_id": "acme", "invoices": 5},
                {"project_no": "4523", "company_id": "beta", "invoices": 2},
                {"project_no": "4526", "company_id": "beta", "invoices": 2}],
            str(age.get("multiple_invoices")))

    # ---- aggregate: vendor on-time ------------------------------------------
    r.section("crm_metrics: vendor_on_time")
    von = _m(cm_all, "reports", "vendor_on_time") or {}
    r.check("13 live legs, 5 judged, on-time rate 0.6",
            von.get("population") == 13 and von.get("counted") == 5
            and von.get("value") == 0.6 and von.get("unit") == "ratio",
            str({k: von.get(k) for k in ("population", "counted", "value", "unit")}))
    r.check("exclusions: cancelled 1, no_vendor 1, not_yet_shipped 2, no_eta 1, "
            "unparseable 1, no_date 1, estimate 1",
            von.get("excluded") == {"cancelled": 1, "no_vendor_on_leg": 1,
                                    "not_yet_shipped": 2, "no_eta": 1,
                                    "unparseable_date": 1, "no_date": 1,
                                    "ship_date_is_estimate": 1},
            str(von.get("excluded")))
    r.check("on-time depends on no clock: no as_of", "as_of" not in von)
    vrows = von.get("rows") or []
    v1 = _by(vrows, "vendor_id", "v1") or {}
    v2 = _by(vrows, "vendor_id", "v2") or {}
    v3 = _by(vrows, "vendor_id", "v3") or {}
    r.check("v1: 4 legs, 3 judged, 2/3 on time, mean 1.7 days late",
            v1.get("population") == 4 and v1.get("counted") == 3
            and abs((v1.get("value") or 0) - 2 / 3) < 1e-3
            and v1.get("mean_days_late") == 1.7
            and v1.get("excluded") == {"not_yet_shipped": 1}, str(v1)[:260])
    r.check("v2: 4 legs, none judged -> null rate, and it is still a row",
            v2.get("population") == 4 and v2.get("counted") == 0
            and v2.get("value") is None and v2.get("mean_days_late") is None
            and v2.get("excluded") == {"cancelled": 1, "not_yet_shipped": 1,
                                       "unparseable_date": 1, "no_date": 1},
            str(v2)[:260])
    r.check("v3: 4 legs, 2 judged, 0.5, mean 4.5; Delivered counts as shipped",
            v3.get("population") == 4 and v3.get("counted") == 2
            and v3.get("value") == 0.5 and v3.get("mean_days_late") == 4.5
            and v3.get("excluded") == {"ship_date_is_estimate": 1, "no_eta": 1},
            str(v3)[:260])
    r.check("rows carry the vendor's display name",
            v1.get("display_name") == "Vendor One", str(v1.get("display_name")))
    r.check("rows are ordered worst rate first, unjudged last",
            [x.get("vendor_id") for x in vrows] == ["v3", "v1", "v2"],
            str([x.get("vendor_id") for x in vrows]))

    # ---- report selection ---------------------------------------------------
    r.section("crm_metrics(report=...)")
    one = s.call("crm_metrics", report="vendor_on_time")
    r.check("naming a report returns only that report",
            one.get("ok") is True and set(_m(one, "reports") or {}) == {"vendor_on_time"},
            str(one)[:160])
    bad = s.call("crm_metrics", report="margins")
    r.check("an unknown report is refused with ok:false, not a raw exception",
            bad.get("ok") is False and "_raised" not in bad, str(bad)[:160])
    r.check("every report is present when none is named",
            set(_m(cm_all, "reports") or {}) == set(REPORTS))
    r.check("the response says when it was computed",
            _m(cm_all, "as_of") == "2026-09-01", str(_m(cm_all, "as_of")))

    # ---- never persisted ----------------------------------------------------
    r.section("metrics are computed on the way out and never written")
    s.reset(**fixture_a())
    before = {e: s.raw(e) for e in ("companies", "projects", "shipments",
                                    "invoices", "vendors")}
    for tool, args in (("get_project", {"project_no": "4521"}), ("list_projects", {}),
                       ("get_company", {"ref": "acme"}), ("list_companies", {}),
                       ("crm_metrics", {}), ("crm_metrics", {"year": 2026})):
        s.call(tool, **args)
    after = {e: s.raw(e) for e in before}
    r.check("every entity file is byte-identical after reading every metric",
            before == after,
            str([e for e in before if before[e] != after[e]]))
    r.check("no entity file contains a metrics key",
            all('"metrics"' not in (after[e] or "") for e in after))
    for name in ("normalize.py", "merge.py"):
        src = (crm / "pipeline" / name).read_text()
        r.check(f"pipeline/{name} never emits a metrics key",
                '"metrics"' not in src and "'metrics'" not in src)
    for fs in ("PROJECT_FIELDS", "COMPANY_FIELDS", "SHIPMENT_FIELDS",
               "INVOICE_FIELDS", "VENDOR_FIELDS", "CONTACT_FIELDS"):
        r.check(f"'metrics' is not in {fs}",
                "metrics" not in (getattr(srv, fs, None) or set()))

    # ---- one malformed record must not take every read tool down ------------
    r.section("a malformed record yields {ok:false} or a valid answer, never a raw exception")
    bad = Store(srv)
    cases = {
        "invoice company_id is a list": dict(invoices=[invoice("1", ["acme"], project_no="4521")]),
        "shipment company_id is a dict": dict(shipments=[shipment("4521-L1", "4521", {"x": 1})]),
        "project company_id is a list": dict(projects=[project("4521"), project("2", ["acme"])]),
        "vendor company_id is a list": dict(vendors=[{"company_id": ["v1"], "display_name": "V"}]),
        "shipment vendor_id is a list": dict(shipments=[shipment("4521-L1", "4521", vendor_id=["v1"],
                                                                stage="Shipped", eta="2026-01-01",
                                                                ship_date="2026-01-02")]),
        "company company_id is a list": dict(companies=[company(), company(["x"], "Listy")]),
        "revenue is Infinity": dict(projects=[project("4521", revenue=float("inf"), total_cost=1)],
                                    invoices=[invoice("1", project_no="4521")]),
        "due_on override is a list": dict(invoices=[invoice("1", project_no="4521", due_on=["x"])]),
        "all_project_nos is an int": dict(shipments=[shipment("4521-L1", "4521", all_project_nos=4521)]),
    }
    for label, files in cases.items():
        base = dict(companies=[company()], projects=[project("4521", revenue=1000, date="2026-01-01")])
        base.update(files)
        bad.reset(**base)
        for tool, args in (("get_project", {"project_no": "4521"}), ("list_projects", {}),
                           ("get_company", {"ref": "acme"}), ("list_companies", {}),
                           ("crm_metrics", {})):
            res = bad.call(tool, **args)
            r.check(f"{label}: {tool} does not raise",
                    "_raised" not in res, str(res.get("_raised"))[:120])
    s.rebind()

    # ---- a view BUILD reads the store and never writes it ---------------------
    r.section("embedding shapes at build time writes nothing into the store")
    import subprocess, tempfile, os as _os
    bdir = Path(tempfile.mkdtemp(prefix="crmbuild-"))
    (bdir / "companies.json").write_text(json.dumps([company()]))
    (bdir / "projects.json").write_text(json.dumps([project("1", revenue=100)]))
    # deliberately NO invoices.json / shipments.json / vendors.json: the case
    # where a OneDrive file has not synced down yet
    before_files = sorted(_os.listdir(bdir))
    out_html = bdir.parent / (bdir.name + ".html")
    pr = subprocess.run([sys.executable, str(crm / "view" / "build_view.py"),
                         "--store", str(bdir), "--out", str(out_html)],
                        capture_output=True, text=True)
    after_files = sorted(_os.listdir(bdir))
    r.check("the build succeeds on a store with files missing", pr.returncode == 0,
            (pr.stderr or "")[-200:])
    r.check("and creates NO file in the store directory -- no entity file, no manifest",
            before_files == after_files,
            f"new files: {sorted(set(after_files) - set(before_files))} -- an empty "
            f"invoices.json written here replicates over the real one on OneDrive")
    r.check("yet the page carries the server's shapes",
            out_html.exists() and '"exposure_open_receivable_usd"' in out_html.read_text(),
            "shapes must come from the server's builder without constructing its Store")
    import shutil as _sh
    _sh.rmtree(bdir, ignore_errors=True)
    if out_html.exists():
        out_html.unlink()

    # ---- parity: the four twins reject a metrics write identically ----------
    r.section("parity: metrics is refused by every create and update, alike")
    s.reset(companies=[company()], projects=[project("4521")])
    got = {
        "update_project": s.call("update_project", project_no="4521",
                                 fields={"metrics": {}}).get("ok"),
        "update_company": s.call("update_company", company_id="acme",
                                 fields={"metrics": {}}).get("ok"),
        "create_project": s.call("create_project",
                                 fields={"company_id": "acme", "project_no": "1",
                                         "status": "won", "metrics": {}}).get("ok"),
        "create_company": s.call("create_company",
                                 fields={"display_name": "New Co",
                                         "metrics": {}}).get("ok"),
    }
    r.check("all four twins agree", len(set(got.values())) == 1, str(got))
    r.check("and all four refuse", all(v is False for v in got.values()), str(got))
    r.check("nothing was written by the refused calls",
            len(s.read("projects")) == 1 and len(s.read("companies")) == 1
            and "metrics" not in s.read("projects")[0])

    # ---- split-billed projects ---------------------------------------------
    #
    # An invoice carries no amount; invoice_amount() reads the linked project's
    # revenue. A project can carry more than one invoice -- create_invoice is
    # unique on (company, invoice_no), and update_invoice accepts project_no --
    # and then every shape that sums outstanding() over invoices priced the
    # project ONCE PER INVOICE. Reproduced on a constructed store, 2026-09-22:
    # one won project at $10,000 with two open invoices read as exposure
    # $20,000 over counted 2. The store holds no per-invoice amount and the
    # split is never guessed: each such invoice is excluded, by name.
    r.section("a project with more than one invoice is never priced once per invoice")
    sp = Store(srv)
    sp.reset(companies=[company("split", "Split Co")],
             projects=[project("5001", "split", status="won", revenue=10000,
                               total_cost=6000)],
             invoices=[invoice("6001", "split", project_no="5001", payment_status="open",
                               invoice_date="2026-06-01"),           # due 07-01: 62 late
                       invoice("6002", "split", project_no="5001", payment_status="open",
                               invoice_date="2026-06-01")])
    sp_co = sp.call("get_company", ref="split")
    sp_age = sp.call("crm_metrics", report="receivables_ageing")
    split_responses = [sp_co, sp_age]
    spm = _m(sp_co, "company", "metrics") or {}
    spx = spm.get("exposure_open_receivable_usd") or {}
    r.check("two open invoices on one $10,000 project: exposure is NOT $20,000",
            spx.get("value") != 20000,
            f"value={spx.get('value')!r} counted={spx.get('counted')!r} -- the "
            f"project's revenue was counted once per invoice")
    r.check("...nothing is priced: value null, counted 0, both excluded "
            "multiple_invoices_on_project",
            spx.get("value") is None and spx.get("counted") == 0
            and spx.get("excluded") == {"multiple_invoices_on_project": 2},
            f"value={spx.get('value')!r} counted={spx.get('counted')!r} "
            f"excluded={spx.get('excluded')!r}")
    r.check("the exposure basis names the exclusion",
            "more than one invoice" in str(spx.get("basis", "")).lower(),
            str(spx.get("basis")))
    r.check("revenue_won_usd 10000 and quoted_gross_profit_usd 4000 are untouched: "
            "they sum by project",
            _m(spm, "revenue_won_usd", "value") == 10000
            and _m(spm, "revenue_won_usd", "counted") == 1
            and _m(spm, "quoted_gross_profit_usd", "value") == 4000,
            f"rev={spm.get('revenue_won_usd')} gp={spm.get('quoted_gross_profit_usd')}")
    r.check("oldest_overdue_days still reads 62 over 2: lateness needs no price",
            _m(spm, "oldest_overdue_days", "value") == 62
            and _m(spm, "oldest_overdue_days", "counted") == 2,
            str(spm.get("oldest_overdue_days"))[:200])
    bk = _m(sp_age, "reports", "receivables_ageing", "buckets", "61-90") or {}
    r.check("the 61-90 bucket holds both invoices: count 2 (an invoice count, unchanged)",
            bk.get("count") == 2, str(bk)[:200])
    r.check("...and its amount_usd is not $20,000: value null, counted 0, "
            "excluded {multiple_invoices_on_project: 2}",
            _m(bk, "amount_usd", "value") is None and _m(bk, "amount_usd", "counted") == 0
            and _m(bk, "amount_usd", "excluded") == {"multiple_invoices_on_project": 2},
            str(bk.get("amount_usd"))[:220])
    r.check("the bucket basis names the exclusion",
            "more than one invoice" in str(_m(bk, "amount_usd", "basis") or "").lower(),
            str(_m(bk, "amount_usd", "basis")))
    check_invariants(r, "get_company(split)", sp_co)
    check_invariants(r, "crm_metrics(split ageing)", sp_age)
    r.check("receivables_ageing names the project: multiple_invoices == [5001 @ split, 2]",
            _m(sp_age, "reports", "receivables_ageing", "multiple_invoices")
            == [{"project_no": "5001", "company_id": "split", "invoices": 2}],
            str(_m(sp_age, "reports", "receivables_ageing", "multiple_invoices")))

    def expo(store, cid):
        return _m(store.call("get_company", ref=cid), "company", "metrics",
                  "exposure_open_receivable_usd") or {}
    def is_(sh, value, counted, excluded):
        return (sh.get("value") == value and sh.get("counted") == counted
                and sh.get("excluded") == excluded)
    P = lambda **kw: project("5001", "split", status="won", revenue=10000, **kw)  # noqa: E731
    I = lambda no, **kw: invoice(no, "split", project_no="5001", invoice_date="2026-06-01", **kw)  # noqa: E731

    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="open")])
    r.check("one project, one invoice: priced at 10000, counted 1 (unchanged)",
            is_(expo(sp, "split"), 10000, 1, {}), str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="partial:30%")])
    r.check("one project, one invoice at partial:30%: 30% RECEIVED, 7000 outstanding",
            is_(expo(sp, "split"), 7000, 1, {}), str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="paid"), I("6002", payment_status="paid")])
    r.check("two invoices, both PAID: value 0, counted 2, no exclusion (the zero rule; "
            "the check must run AFTER paid)",
            is_(expo(sp, "split"), 0, 2, {}), str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="paid"), I("6002", payment_status="open")])
    r.check("one paid, one open: the paid one counts as 0 (counted 1), the open one "
            "is excluded multiple_invoices_on_project",
            is_(expo(sp, "split"), 0, 1, {"multiple_invoices_on_project": 1}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="open"), I("6002", payment_status="open"),
                       I("6003", payment_status="open")])
    r.check("three open invoices on one project: all three excluded (more than one, not "
            "more than two)",
            is_(expo(sp, "split"), None, 0, {"multiple_invoices_on_project": 3}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[I("6001", payment_status="partial:50%"), I("6002", payment_status="open")])
    r.check("partial:50% on one of two: it is not paid, so it is excluded like the other",
            is_(expo(sp, "split"), None, 0, {"multiple_invoices_on_project": 2}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co"), company("other", "Other Co")],
             projects=[P(), project("5001", "other", status="won", revenue=2000)],
             invoices=[I("6001", payment_status="open"),
                       invoice("6002", "other", project_no="5001", payment_status="open",
                               invoice_date="2026-06-01")])
    r.check("same project_no at two DIFFERENT companies, one invoice each: neither excluded "
            "(grouping is per company)",
            is_(expo(sp, "split"), 10000, 1, {}) and is_(expo(sp, "other"), 2000, 1, {}),
            f"split={expo(sp, 'split')} other={expo(sp, 'other')}"[:300])
    sp.reset(companies=[company("split", "Split Co"), company("other", "Other Co")],
             projects=[P(), project("5001", "other", status="won", revenue=2000)],
             invoices=[I("6001", payment_status="open"),
                       invoice("6001", "other", project_no="5001", payment_status="open",
                               invoice_date="2026-06-01")])
    r.check("same invoice_no at two companies on the same project_no string: neither excluded",
            is_(expo(sp, "split"), 10000, 1, {}) and is_(expo(sp, "other"), 2000, 1, {}),
            f"split={expo(sp, 'split')} other={expo(sp, 'other')}"[:300])
    # _key() folds a FLOAT 1234.0 to "1234" (an integer emitted as a float by a
    # JSON-RPC caller); the STRING "1234.0" is a different key by design
    # (0.1.28: folding both sides merged an archived twin into a live one).
    sp.reset(companies=[company("split", "Split Co")],
             projects=[project("1234", "split", status="won", revenue=10000)],
             invoices=[invoice("6001", "split", project_no=1234.0, payment_status="open",
                               invoice_date="2026-06-01"),
                       invoice("6002", "split", project_no="1234", payment_status="open",
                               invoice_date="2026-06-01")])
    r.check("project_no 1234.0 (float) on one invoice and \"1234\" on the other: the same "
            "project, BOTH excluded",
            is_(expo(sp, "split"), None, 0, {"multiple_invoices_on_project": 2}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")],
             projects=[project("1234", "split", status="won", revenue=10000)],
             invoices=[invoice("6001", "split", project_no="1234.0", payment_status="open",
                               invoice_date="2026-06-01"),
                       invoice("6002", "split", project_no="1234", payment_status="open",
                               invoice_date="2026-06-01")])
    r.check("the STRING \"1234.0\" is not \"1234\": that invoice is no_project_link and the "
            "other prices alone (0.1.28's asymmetry, kept)",
            is_(expo(sp, "split"), 10000, 1, {"no_project_link": 1}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")],
             projects=[P()],
             invoices=[invoice("6001", "split", project_no=" 5001 ", payment_status="open",
                               invoice_date="2026-06-01"),
                       I("6002", payment_status="open")])
    r.check("a whitespace-padded \" 5001 \" is the same project: both excluded",
            is_(expo(sp, "split"), None, 0, {"multiple_invoices_on_project": 2}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")], projects=[P()],
             invoices=[invoice("6001", "split", project_no=["5001"], payment_status="open",
                               invoice_date="2026-06-01"),
                       invoice("6002", "split", project_no={"n": "5001"}, payment_status="open",
                               invoice_date="2026-06-01"),
                       I("6003", payment_status="open")])
    r.check("a list or dict project_no is no_project_link, never split, and nothing raises",
            is_(expo(sp, "split"), 10000, 1, {"no_project_link": 2}),
            str(expo(sp, "split"))[:200])
    sp.reset(companies=[company("split", "Split Co")],
             projects=[project("5001", "split", status="won", revenue=10000, archived=True)],
             invoices=[I("6001", payment_status="open"), I("6002", payment_status="open")])
    arch_co = sp.call("get_company", ref="split")
    arch_age = sp.call("crm_metrics", report="receivables_ageing")
    r.check("an archived project with two invoices: absent from every shape, no crash",
            arch_co.get("ok") is True and arch_age.get("ok") is True
            and is_(_m(arch_co, "company", "metrics", "exposure_open_receivable_usd") or {},
                    None, 0, {})
            and _m(arch_age, "reports", "receivables_ageing", "population") == 0
            and _m(arch_age, "reports", "receivables_ageing", "multiple_invoices") == [],
            f"co={_m(arch_co, 'company', 'metrics', 'exposure_open_receivable_usd')} "
            f"age={str(_m(arch_age, 'reports', 'receivables_ageing'))[:120]}")
    # A vendor PO number typed into project_no. PO and project numbers share
    # one numeric range, so a mistyped PO can resolve to a real, unrelated
    # project and make it look split-billed. It fails safe: excluded, not
    # doubled, and the other project's own invoice is excluded with it.
    sp.reset(companies=[company("split", "Split Co")],
             projects=[P(), project("7770", "split", status="won", revenue=50000)],
             shipments=[shipment("5001-L1", "5001", "split", vendor_po_raw="7770")],
             invoices=[I("6001", payment_status="open"),
                       invoice("6002", "split", project_no="7770", payment_status="open",
                               invoice_date="2026-06-01"),
                       invoice("6003", "split", project_no="7770", payment_status="open",
                               invoice_date="2026-06-01")])
    r.check("a vendor PO number typed as project_no resolves to the unrelated project 7770: "
            "both its invoices are excluded, not priced at 50000 each",
            is_(expo(sp, "split"), 10000, 1, {"multiple_invoices_on_project": 2}),
            str(expo(sp, "split"))[:200])
    s.rebind()

    # ---- the QuickBooks join's reasons (0.1.38) --------------------------------
    # A store with a snapshot BESIDE it, in its own temp dir: the harness's
    # default store sits directly in the system temp dir, whose sibling
    # qbo-snapshots would be shared by every test. One invoice matches twice,
    # one is dated inside the window and missing, one is dated before it.
    import shutil as _sh
    import tempfile as _tf
    qdir = Path(_tf.mkdtemp(prefix="crmqbo-"))
    qs = Store(srv, qdir / "store")
    qs.reset(companies=[company("acme", "Ace Manufacturing"),
                        company("beta", "Beta Works")],
             invoices=[invoice("8001", "acme", invoice_date="2026-02-01"),
                       invoice("8002", "acme", invoice_date="2026-03-01"),
                       invoice("8003", "acme", invoice_date="2025-06-01"),
                       # one QuickBooks invoice, a CRM invoice at each customer
                       invoice("8004", "acme", invoice_date="2026-02-01"),
                       invoice("8004", "beta", invoice_date="2026-02-01"),
                       # a pair with only one of its two invoices in QuickBooks
                       invoice("8005 and 8006", "acme", invoice_date="2026-02-01")])
    srv._save_qbo_snapshot("invoices", "export", "2026-08-30", "2026-01-01",
                           "2026-08-30",
                           [{"type": "Invoice", "num": "8001", "amount_cents": 100,
                             "open_cents": 0}] * 2
                           + [{"type": "Invoice", "num": n, "amount_cents": 100,
                               "open_cents": 0} for n in ("8004", "8005")])
    qbo_responses = [qs.call("get_company", ref="acme"), qs.call("crm_metrics")]
    for i, res in enumerate(qbo_responses):
        check_invariants(r, f"qbo[{i}]", res)
    _sh.rmtree(qdir, ignore_errors=True)
    s.rebind()

    # ---- the vocabulary is closed and exported --------------------------------
    r.section("the exclusion vocabulary is a closed, exported constant")
    vocab = getattr(srv, "EXCLUSION_REASONS", None)
    r.check("server exports EXCLUSION_REASONS", vocab is not None)
    r.check("and it is exactly the twenty-three reasons this suite knows",
            vocab is not None and set(vocab) == VOCAB and len(vocab) == 23,
            f"server={sorted(vocab or [])}")
    seen = set()
    for res in list(responses.values()) + [empty, c25] + split_responses + qbo_responses:
        for _p, sh in shapes_in(res):
            seen |= set((sh.get("excluded") or {}).keys())
    r.check("the fixture exercises every reason in the vocabulary",
            seen == VOCAB, f"never produced: {sorted(VOCAB - seen)}")
    # The builder is the one place the vocabulary is enforced, and no tool
    # path can reach a reason outside it -- which is the point. A direct call
    # is the only way to show the guard is real rather than decorative.
    build = getattr(srv, "_shape", None)
    try:
        build(1, "usd", 1, {"bogus_reason": 1}, "b")
        rejected = False
    except Exception:                                             # noqa: BLE001
        rejected = True
    r.check("the builder refuses a reason outside the vocabulary",
            callable(build) and rejected)

    # ---- the tool is documented ---------------------------------------------
    r.section("crm_metrics is in the interface doc")
    doc = (crm / "references" / "interface-v0.1.md").read_text()
    r.check("interface-v0.1.md has a crm_metrics row", "| `crm_metrics`" in doc)
    r.check("and the row names the population/excluded contract",
            "population" in doc and "excluded" in doc)

    return r

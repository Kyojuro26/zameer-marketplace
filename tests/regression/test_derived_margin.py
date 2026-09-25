"""Profit and margin follow revenue and cost (0.1.44 H4).

Editing a project's revenue or total_cost left its stored gross_profit and
margin as they were, so three live projects showed profit that no longer
matched their own figures. On any server write that CHANGES revenue or
total_cost, the server now recomputes:

    gross_profit = revenue - total_cost        (to the cent)
    margin       = gross_profit / revenue      (a fraction)

both null when either input is missing, and margin null when revenue is zero
or negative. A gross_profit or margin passed in the same write that disagrees
with the recomputed value by more than a cent (0.0001 for margin) is refused,
naming both values; a consistent one is allowed. A write that does not carry
revenue or cost leaves them alone (the importer is out of scope).

H4b: a write that CARRIES revenue or total_cost, changed or not, recomputes
when both are present -- the drawer re-sends them on every save, and re-saving
revenue is how a stale project is corrected. With an input missing, a change
nulls them and an unchanged resend leaves a hand-entered profit alone.

crm_info's read-only check lists the projects whose stored profit or margin
disagrees with their revenue and cost, and writes nothing. Fixture names are
invented.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project  # noqa: E402


def run(server, crm_dir=None):
    r = Result("derived-margin", since="0.1.44")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    s = Store(srv)
    s.reset(companies=[company("acme", "Ace Manufacturing")],
            projects=[project("4521", "acme", revenue=1000, total_cost=600, gross_profit=400, margin=0.4),
                      project("4600", "acme", revenue=1000, total_cost=600, gross_profit=999, margin=0.4),
                      project("4601", "acme", revenue=2000, total_cost=500, gross_profit=1500, margin=0.1),
                      project("4602", "acme", revenue=1000, total_cost=250, gross_profit=750, margin=0.75),
                      project("4603", "acme", gross_profit=50),
                      project("4604", "acme", revenue=1000, total_cost=600, gross_profit=1, margin=0.9,
                              archived=True)])

    def rec(pno):
        return next((p for p in s.read("projects") if str(p["project_no"]) == pno), {})

    def fresh(pno):
        """projects.json re-read by a separate process."""
        code = ("import json,sys; ps=json.load(open(sys.argv[1]));"
                "p=[x for x in ps if str(x['project_no'])==sys.argv[2]][0];"
                "print(json.dumps([p.get('gross_profit'), p.get('margin')]))")
        out = subprocess.run([sys.executable, "-c", code, str(s.path / "projects.json"), pno],
                             capture_output=True, text=True)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def up(pno, **fields):
        return s.call("update_project", project_no=pno, company_id="acme", fields=fields)

    r.section("revenue, then cost, then both")
    res = up("4521", revenue=2000)
    r.check("a revenue edit recomputes profit and margin", res.get("ok") is True and fresh("4521") == [1400, 0.7],
            json.dumps([res.get("error"), fresh("4521")]))
    up("4521", total_cost=1200)
    r.check("a cost edit recomputes them", fresh("4521") == [800, 0.4], json.dumps(fresh("4521")))
    up("4521", revenue=500, total_cost=250)
    r.check("an edit to both recomputes them", fresh("4521") == [250, 0.5], json.dumps(fresh("4521")))
    log = [json.loads(l) for l in (s.path / "changelog.jsonl").read_text().splitlines() if l.strip()]
    r.check("the changelog records the derived values with the edit",
            (log[-1].get("fields") or {}).get("gross_profit") == 250
            and (log[-1].get("fields") or {}).get("margin") == 0.5, json.dumps(log[-1])[:200])

    r.section("a disagreeing value is refused; a consistent one is allowed")
    before = json.dumps(rec("4521"), sort_keys=True)
    res = up("4521", revenue=3000, gross_profit=100)
    err = str(res.get("error"))
    r.check("a gross_profit that disagrees is refused, naming both values",
            res.get("ok") is False and "100" in err and "2750" in err, err[:200])
    res = up("4521", revenue=3000, margin=0.5)
    err = str(res.get("error"))
    r.check("a margin that disagrees is refused, naming both values",
            res.get("ok") is False and "0.5" in err and "0.9167" in err, err[:200])
    r.check("... and nothing changed", json.dumps(rec("4521"), sort_keys=True) == before)
    res = up("4521", revenue=3000, gross_profit=2750.004, margin=0.91668)
    r.check("values within a cent and 0.0001 are allowed, and the recomputed ones stored",
            res.get("ok") is True and fresh("4521") == [2750, 0.916667], json.dumps([res.get("error"), fresh("4521")]))

    r.section("odd inputs")
    for label, rev, want in (("an empty revenue", "", [None, None]),
                             ("a revenue of '0'", "0", [-250, None]),
                             ("a string revenue", "1500", [1250, 0.833333]),
                             ("a negative revenue", -100, [-350, None])):
        res = up("4521", revenue=rev)
        r.check(f"{label}: profit {want[0]}, margin {want[1]}",
                res.get("ok") is True and fresh("4521") == want, json.dumps([res.get("error"), fresh("4521")]))
    up("4521", revenue=1000, total_cost=600)
    stale = rec("4600")
    res = up("4600", notes="unrelated")
    r.check("a write that does not change revenue or cost leaves profit alone",
            res.get("ok") is True and rec("4600").get("gross_profit") == stale.get("gross_profit"), json.dumps(rec("4600"))[:160])
    # H4b: the drawer re-sends revenue and cost on every save, and re-saving
    # revenue is the operator's fix for a stale project -- so a resend with
    # both inputs present recomputes, changed or not
    s.write("projects", s.read("projects") + [
        project("4607", "acme", revenue=1000, total_cost=600, gross_profit=999, margin=0.9),
        project("4608", "acme", revenue=500, gross_profit=120, margin=0.24)])
    res = up("4607", revenue=1000, total_cost=600)
    r.check("re-sending the same revenue and cost, as the drawer does, corrects a stale profit and margin",
            res.get("ok") is True and fresh("4607") == [400, 0.4], json.dumps([res.get("error"), fresh("4607")]))
    res = up("4608", revenue=500, total_cost=None)
    r.check("... but a resend on a project with no cost leaves its hand-entered profit and margin alone",
            res.get("ok") is True and fresh("4608") == [120, 0.24], json.dumps([res.get("error"), fresh("4608")]))
    # review of 0.1.44: a write that sends profit or margin is judged whether or
    # not it changes revenue or cost -- {"margin": 40} was stored as 4000%
    for label, fields in (("a profit alone", {"gross_profit": 999}),
                          ("a margin sent as a percent", {"margin": 40}),
                          ("the same revenue re-sent with a stale profit", {"revenue": 1000, "gross_profit": 999})):
        res = up("4600", **fields)
        r.check(f"{label} is refused when revenue and cost give another value",
                res.get("ok") is False and "disagrees" in str(res.get("error")), json.dumps(res)[:200])
    res = up("4600", gross_profit=400)
    r.check("a consistent profit alone is accepted, and corrects the stored one",
            res.get("ok") is True and fresh("4600") == [400, 0.4], json.dumps([res.get("error"), fresh("4600")]))
    # review round 2: one rule for create and update -- with nothing to work it
    # out from, a sent profit or margin is refused unless null
    res = up("4603", gross_profit=75)
    r.check("with no revenue or cost to work it out from, a sent profit is refused",
            res.get("ok") is False and "null" in str(res.get("error")), json.dumps(res)[:200])
    s.write("projects", s.read("projects") + [project("4605", "acme", revenue=100)])
    res = up("4605", margin=40)
    r.check("... and a margin sent on a project with revenue but no cost (it was stored as 4000%)",
            res.get("ok") is False and rec("4605").get("margin") is None, json.dumps(res)[:200])
    res = s.call("create_project", fields={"project_no": "4606", "company_id": "acme",
                                           "revenue": 100, "gross_profit": 40})
    r.check("... the same as create_project", res.get("ok") is False, json.dumps(res)[:200])
    res = up("4605", gross_profit=None, margin=None)
    r.check("... while null is accepted", res.get("ok") is True, json.dumps(res)[:200])
    import inspect
    r.check("update_project's description says profit and margin are worked out",
            "worked out" in (inspect.getdoc(getattr(srv, "update_project", None)) or ""))
    res = s.call("create_project", fields={"project_no": "4700", "company_id": "acme",
                                           "revenue": 800, "total_cost": 200})
    r.check("create_project derives them too", res.get("ok") is True and fresh("4700") == [600, 0.75],
            json.dumps([res.get("error"), fresh("4700")]))

    r.section("the read-only check")
    s.write("projects", [p for p in s.read("projects") if str(p["project_no"]) not in ("4700", "4607")])
    digest = lambda: {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(s.path.iterdir()) if p.is_file()}
    before = digest()
    res = s.call("crm_info")
    dm = res.get("derived_mismatch") or {}
    got = sorted(str(p.get("project_no")) for p in dm.get("projects", []))
    r.check("crm_info lists exactly the projects whose stored profit or margin disagree",
            got == ["4601"], json.dumps(dm)[:300])
    r.check("... with how many it checked", dm.get("checked") == 4, json.dumps(dm)[:200])
    r.check("... and each listing carries the stored and the derived values",
            any(p.get("project_no") == "4601" and p.get("margin") == 0.1
                and p.get("derived_margin") == 0.75 for p in dm.get("projects", [])), json.dumps(dm)[:300])
    r.check("the check writes nothing", digest() == before)
    ps = s.read("projects")
    ps += [project(str(5000 + n), "acme", revenue=100, total_cost=50, gross_profit=1, margin=0.5) for n in range(60)]
    s.write("projects", ps)
    dm = s.call("crm_info").get("derived_mismatch") or {}
    r.check("the list is bounded: 50 shown, the count says 61",
            len(dm.get("projects", [])) == 50 and dm.get("count") == 61, json.dumps({k: dm.get(k) for k in ("count", "checked")}))

    r.section("zero or negative revenue (H4b)")
    # no margin can be worked out; the workbook stores 0 there, which is not stale
    s.write("projects", [project("4800", "acme", revenue=0, total_cost=100, gross_profit=-100, margin=0),
                         project("4801", "acme", revenue=-50, total_cost=0, gross_profit=-50, margin=0),
                         project("4802", "acme", revenue=0, total_cost=100, gross_profit=-100, margin=0.25),
                         project("4803", "acme", revenue=0, total_cost=100, gross_profit=5, margin=0)])
    dm = s.call("crm_info").get("derived_mismatch") or {}
    got = sorted(str(p.get("project_no")) for p in dm.get("projects", []))
    r.check("a stored margin of 0 on zero or negative revenue is not a mismatch",
            "4800" not in got and "4801" not in got, json.dumps(got))
    r.check("... but any other margin there is, and so is a wrong profit",
            got == ["4802", "4803"] and dm.get("checked") == 4, json.dumps([got, dm.get("checked")]))
    return r

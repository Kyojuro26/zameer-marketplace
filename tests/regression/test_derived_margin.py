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
naming both values; a consistent one is allowed. A write that does not change
revenue or cost leaves them alone (the importer is out of scope).

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
    res = up("4600", revenue=1000, gross_profit=999)
    r.check("re-sending the same revenue changes nothing, so its profit is not judged",
            res.get("ok") is True and rec("4600").get("gross_profit") == 999, json.dumps(res)[:200])
    res = s.call("create_project", fields={"project_no": "4700", "company_id": "acme",
                                           "revenue": 800, "total_cost": 200})
    r.check("create_project derives them too", res.get("ok") is True and fresh("4700") == [600, 0.75],
            json.dumps([res.get("error"), fresh("4700")]))

    r.section("the read-only check")
    s.write("projects", [p for p in s.read("projects") if str(p["project_no"]) != "4700"])
    digest = lambda: {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(s.path.iterdir()) if p.is_file()}
    before = digest()
    res = s.call("crm_info")
    dm = res.get("derived_mismatch") or {}
    got = sorted(str(p.get("project_no")) for p in dm.get("projects", []))
    r.check("crm_info lists exactly the projects whose stored profit or margin disagree",
            got == ["4600", "4601"], json.dumps(dm)[:300])
    r.check("... with how many it checked", dm.get("checked") == 4, json.dumps(dm)[:200])
    r.check("... and each listing carries the stored and the derived values",
            any(p.get("project_no") == "4600" and p.get("gross_profit") == 999
                and p.get("derived_gross_profit") == 400 for p in dm.get("projects", [])), json.dumps(dm)[:300])
    r.check("the check writes nothing", digest() == before)
    return r

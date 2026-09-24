"""create_project from anywhere (0.1.43 G3): who a project can belong to.

The "+ New project" button moves onto the Projects and Live tabs, with a
customer picker. The server is what decides, so the rules are asserted here:

 1. A VENDOR IS REFUSED, NAMING IT (named exception, 0.1.43). _require_company
    checks existence and liveness, never role, so a company whose role is
    vendor took a project and the job sat under a supplier. Leads stay allowed:
    a quote goes to a lead before it is a customer.
 2. A PROJECT NUMBER IS UNIQUE ACROSS THE BUSINESS. A new number is a
    QuickBooks estimate number, so any existing number is refused, at any
    customer, with the server's message naming it. Not loosened.
 3. Archived companies and vendor records (vendors.json) are refused as before.
 4. Company ids that are also built-in property names work.

Driven through server.mcp.call_tool. Fixture names are invented.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project  # noqa: E402


def run(server, crm_dir=None):
    r = Result("new-project", since="0.1.43")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    s = Store(srv)
    s.reset(companies=[company("acme", "Ace Manufacturing"),
                       company("beta", "Beta Works", role="lead"),
                       company("gamma", "Gamma Tooling", role="vendor"),
                       company("delta", "Delta Parts", archived=True),
                       company("constructor", "Constructor Co"),
                       company("__proto__", "Proto Works")],
            vendors=[{"company_id": "vend1", "display_name": "Vendor One"}],
            projects=[project("4521", "acme")])

    def create(cid, pno):
        return s.call("create_project", fields={"project_no": pno, "company_id": cid})

    def ids():
        return sorted((str(p["project_no"]), p["company_id"]) for p in s.read("projects"))

    r.section("who a project can belong to")
    before = ids()
    res = create("gamma", "5001")
    err = str(res.get("error"))
    r.check("a vendor-role company is refused", res.get("ok") is False, json.dumps(res)[:200])
    r.check("... naming the company and saying why", "gamma" in err and "Gamma Tooling" in err
            and "vendor" in err, err)
    r.check("... and nothing was written", ids() == before, json.dumps(ids()))
    res = create("beta", "5002")
    r.check("a lead is allowed", res.get("ok") is True and ("5002", "beta") in ids(),
            json.dumps(res)[:200])
    res = create("acme", "5003")
    r.check("a customer is allowed", res.get("ok") is True, json.dumps(res)[:200])
    res = create("delta", "5004")
    r.check("an archived company is still refused", res.get("ok") is False
            and "delta" in str(res.get("error")), json.dumps(res)[:200])
    res = create("vend1", "5005")
    r.check("a vendor record (vendors.json) is still refused", res.get("ok") is False,
            json.dumps(res)[:200])
    res = create("constructor", "5006")
    r.check("a company whose id is 'constructor' works", res.get("ok") is True
            and ("5006", "constructor") in ids(), json.dumps(res)[:200])
    res = create("__proto__", "5007")
    r.check("a company whose id is '__proto__' works", res.get("ok") is True
            and ("5007", "__proto__") in ids(), json.dumps(res)[:200])
    s.write("companies", [c if c["company_id"] != "gamma" else dict(c, role="customer")
                          for c in s.read("companies")])
    res = create("gamma", "5008")
    r.check("the same company, once its role is customer, is allowed", res.get("ok") is True,
            json.dumps(res)[:200])

    # review round 1: the rule is who a project belongs to, not how it got
    # there -- moving one under a vendor through update_project was allowed
    s.write("companies", [c if c["company_id"] != "gamma" else dict(c, role="vendor")
                          for c in s.read("companies")])
    before = ids()
    res = s.call("update_project", project_no="5003", company_id="acme",
                 fields={"company_id": "gamma"})
    err = str(res.get("error"))
    r.check("moving a project under a vendor is refused, naming it",
            res.get("ok") is False and "gamma" in err and "Gamma Tooling" in err and "vendor" in err, err[:200])
    r.check("... and nothing moved", ids() == before, json.dumps(ids()))
    res = s.call("update_project", project_no="5003", company_id="acme", fields={"company_id": "beta"})
    r.check("moving one under a lead is allowed", res.get("ok") is True and ("5003", "beta") in ids(),
            json.dumps(res)[:200])
    # round 2: re-sending a project's own company is not a move
    s.write("companies", [c if c["company_id"] != "beta" else dict(c, role="vendor")
                          for c in s.read("companies")])
    res = s.call("update_project", project_no="5003", company_id="beta",
                 fields={"company_id": "beta", "notes": "still here"})
    r.check("re-sending the project's current company is not a move, even once it is a vendor",
            res.get("ok") is True, json.dumps(res)[:200])
    s.write("companies", [c if c["company_id"] not in ("gamma", "beta") else
                          dict(c, role="customer" if c["company_id"] == "gamma" else "lead")
                          for c in s.read("companies")])

    r.section("a project number is unique across the business")
    before = ids()
    for cid, pno in (("beta", "4521"), ("acme", "4521"), ("gamma", " 4521 ")):
        res = create(cid, pno)
        r.check(f"{pno!r} for {cid} is refused: the number already exists",
                res.get("ok") is False and "project '4521' already exists" in str(res.get("error")),
                json.dumps(res)[:200])
    r.check("and nothing was written", ids() == before, json.dumps(ids()))
    return r

"""The chat flows for completed jobs and new projects (0.1.43 G4).

SKILL.md is what Claude reads to act in chat, so the four flows are asserted
on its text -- each names the tool and field that do the work -- and the server
behaviour each flow relies on is asserted beside it, so the page cannot tell
Claude to do something the server does not do:

  * "mark 4521 complete": update_project(completed_on=) with the customer; a
    shared number is refused without one, so the flow asks which customer;
  * "reopen 4521": completed_on null;
  * "what did we complete this month": a list from list_projects, whose rows
    carry completed_on -- not a metric, nothing totalled;
  * "add a project for Ace Manufacturing": create_project for a customer or
    lead; a vendor is refused; an existing number is refused.

Fixture names are invented.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project  # noqa: E402


def _section(text):
    """The Completed-jobs and Add-a-project blocks of SKILL.md, each from its
    bullet to the next top-level bullet."""
    out = []
    for head in (r"\*\*Completed jobs\*\*", r"\*\*Add a project\*\*"):
        m = re.search(r"^- " + head + r".*?(?=^- \*\*|\Z)", text, re.M | re.S)
        out.append(m.group(0) if m else "")
    return "\n".join(out) if all(out) else ""


def run(server, crm_dir=None):
    r = Result("completed-chat", since="0.1.43")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    sec = _section((crm / "SKILL.md").read_text()) if (crm / "SKILL.md").exists() else ""
    flat = " ".join(sec.split())

    r.section("SKILL.md states the four flows")
    r.check("SKILL.md has a Completed jobs section", bool(sec))
    r.check('"mark 4521 complete" sets completed_on through update_project',
            bool(re.search(r"mark \S+ complete", flat, re.I)) and "update_project" in flat
            and "completed_on" in flat, flat[:160])
    r.check("... looks the number up first and asks which customer when it is shared",
            "lookup_number" in flat and re.search(r"ask which customer", flat, re.I) is not None
            and "company_id" in flat, flat[:160])
    r.check("... says complete is not paid: collection status is left alone",
            re.search(r"not (the same as )?paid", flat, re.I) is not None and "collection" in flat, flat[:160])
    r.check("... passes on a warning and says why a date is refused",
            "warning" in flat and re.search(r"after today", flat) is not None, flat[:160])
    r.check('"reopen 4521" sets completed_on to null',
            re.search(r"reopen", flat, re.I) is not None
            and re.search(r'"completed_on": null', flat) is not None, flat[:160])
    r.check('"what did we complete this month" is a list from list_projects',
            re.search(r"complete this month", flat, re.I) is not None and "list_projects" in flat, flat[:160])
    r.check("... never a metric: no crm_metrics, nothing totalled",
            "crm_metrics" not in flat and re.search(r"do not total|never total|no totals", flat, re.I) is not None,
            flat[:160])
    r.check('"add a project for Ace Manufacturing" uses create_project',
            re.search(r"add a project for", flat, re.I) is not None and "create_project" in flat, flat[:160])
    r.check("... for a customer or a lead; a vendor is refused",
            re.search(r"customer or a lead", flat) is not None and re.search(r"vendor is refused", flat) is not None,
            flat[:160])
    r.check("... asks for the number, which is unique across the business",
            re.search(r"unique across the business", flat) is not None, flat[:160])

    r.section("the server does what the flows say")
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    # the clock the dates below are judged by -- never the wall clock, and
    # never whatever an earlier module in the same run froze it to
    srv._today = lambda: date(2026, 9, 15)
    s = Store(srv)
    s.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works"),
                       company("gamma", "Gamma Tooling", role="vendor")],
            projects=[project("4521", "acme"), project("4521", "beta"), project("4522", "acme")])
    res = s.call("update_project", project_no="4521", fields={"completed_on": "2026-09-01"})
    r.check("without a customer, a shared number is refused -- so the flow must ask",
            res.get("ok") is False, json.dumps(res)[:160])
    res = s.call("lookup_number", n="4521")
    holders = sorted({str(m.get("company_id")) for m in res.get("matches", []) if m.get("type") == "project"})
    r.check("lookup_number names both customers holding 4521", holders == ["acme", "beta"], json.dumps(res)[:200])
    res = s.call("update_project", project_no="4521", company_id="beta", fields={"completed_on": "2026-09-01"})
    r.check("with the customer, only that one is completed", res.get("ok") is True
            and [p.get("completed_on") for p in s.read("projects") if p["project_no"] == "4521"]
            == [None, "2026-09-01"], json.dumps(s.read("projects"))[:200])
    rows = s.call("list_projects").get("projects", [])
    r.check("list_projects rows carry completed_on, so the month's list can be read from them",
            any(p.get("company_id") == "beta" and p.get("completed_on") == "2026-09-01" for p in rows),
            json.dumps(rows)[:200])
    res = s.call("create_project", fields={"project_no": "5001", "company_id": "gamma"})
    r.check("create_project refuses a vendor", res.get("ok") is False, json.dumps(res)[:160])
    res = s.call("create_project", fields={"project_no": "4522", "company_id": "beta"})
    r.check("create_project refuses an existing number", res.get("ok") is False
            and "already exists" in str(res.get("error")), json.dumps(res)[:160])
    return r

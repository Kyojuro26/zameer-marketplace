"""Next action, with a date -- "whose court" gets a "by when".

The Live screen groups jobs by whose court they are in; nothing said when a
job was due back. The note carried it as prose. Two operator-owned fields now
carry it: next_action (text) and next_action_on (a date, stored as given).
Four decisions are asserted, each with an obvious wrong version:

 1. STORED AS GIVEN. An ISO date from the drawer and a tracker-style 9/12/26
    from chat are both kept verbatim; nothing canonicalises a date here, as
    nothing does for any other date in the store.
 2. A WRONG TYPE OR AN UNREADABLE DATE IS REFUSED, not stringified and not
    stored: a next_action_on no reader can parse would never come due, which
    is a silent wrong answer.
 3. DUE MEANS TODAY OR EARLIER, through the frozen clock: yesterday in, today
    in, tomorrow out; a lost project out; an archived project out even when
    archived projects are asked for.
 4. A RE-IMPORT NEVER OVERWRITES THEM. They are not the workbook's fields:
    with a changelog they survive through merge's touched rule, without one
    the add-only path leaves the record untouched.

Driven through server.mcp.call_tool. Fixture names are invented.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project  # noqa: E402

TODAY = date(2026, 8, 9)


def _load_merge(crm_dir):
    import importlib.util
    p = Path(crm_dir) / "pipeline" / "merge.py"
    spec = importlib.util.spec_from_file_location("_merge_under_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rec(s, pno):
    return next((p for p in s.read("projects") if str(p.get("project_no")) == pno), None)


def _f(s, pno, key):
    """A field of that record, or None when the record or the key is missing.
    A server that dropped the field, or refused the create, must read as a
    red check here -- not a KeyError the runner cannot score."""
    p = _rec(s, pno)
    return p.get(key) if p else None


def run(server, crm_dir=None):
    r = Result("next-action", since="0.1.37")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    if not r.check("server exposes _today()", callable(getattr(srv, "_today", None)),
                   "no _today hook -- every date-relative check below would drift"):
        return r
    srv._today = lambda: TODAY
    s = Store(srv)

    def seed():
        s.reset(companies=[company("acme", "Ace Manufacturing")],
                projects=[project("4521", "acme", description="won, yesterday"),
                          project("4522", "acme", status="lost"),
                          project("4523", "acme", archived=True),
                          project("4524", "acme"),
                          project("4525", "acme"),
                          project("4526", "acme")])

    # ---- 1. stored as given -----------------------------------------------------
    r.section("both fields round-trip, stored as given")
    seed()
    res = s.call("update_project", project_no="4521",
                 fields={"next_action": "Chase the revised PO", "next_action_on": "2026-08-08"},
                 company_id="acme")
    r.check("update_project accepts next_action and next_action_on",
            res.get("ok") and res.get("project", {}).get("next_action") == "Chase the revised PO"
            and res.get("project", {}).get("next_action_on") == "2026-08-08", json.dumps(res)[:200])
    res = s.call("get_project", project_no="4521", company_id="acme")
    r.check("and get_project reads them back",
            res.get("ok") and res.get("project", {}).get("next_action") == "Chase the revised PO"
            and res.get("project", {}).get("next_action_on") == "2026-08-08", json.dumps(res)[:200])
    r.check("the date is on disk exactly as given",
            _f(s, "4521", "next_action_on") == "2026-08-08", json.dumps(_rec(s, "4521"))[:200])
    res = s.call("update_project", project_no="4524", fields={"next_action_on": "9/12/26"},
                 company_id="acme")
    r.check("a tracker-style date is accepted and kept verbatim, not rewritten",
            res.get("ok") and _f(s, "4524", "next_action_on") == "9/12/26", json.dumps(res)[:200])
    res = s.call("create_project", fields={"project_no": "4530", "company_id": "acme",
                                           "next_action": "Send the quote",
                                           "next_action_on": "2026-08-10"})
    r.check("create_project carries both fields",
            res.get("ok") and res.get("project", {}).get("next_action") == "Send the quote"
            and res.get("project", {}).get("next_action_on") == "2026-08-10", json.dumps(res)[:200])
    res = s.call("update_project", project_no="4530",
                 fields={"next_action": None, "next_action_on": None}, company_id="acme")
    r.check("null clears both",
            res.get("ok") and _f(s, "4530", "next_action") is None
            and _f(s, "4530", "next_action_on") is None, json.dumps(res)[:200])

    # ---- 2. wrong type / unreadable date refused ---------------------------------
    r.section("a wrong type or an unreadable date is refused, and nothing changes")
    before = json.dumps(_rec(s, "4521"), sort_keys=True)
    for bad in ({"next_action": 5}, {"next_action": ["a"]}, {"next_action": True},
                {"next_action_on": 20260808}, {"next_action_on": ["2026-08-08"]},
                {"next_action_on": True}, {"next_action_on": "soon"},
                {"next_action_on": "2026-13-45"}):
        res = s.call("update_project", project_no="4521", fields=bad, company_id="acme")
        r.check(f"{json.dumps(bad)} is refused with a message naming the field",
                res.get("ok") is False and "next_action" in str(res.get("error")),
                json.dumps(res)[:160])
    r.check("and the record is byte-identical after every refusal",
            json.dumps(_rec(s, "4521"), sort_keys=True) == before)

    # ---- 3. what is due ----------------------------------------------------------
    r.section("next_action_due: today or earlier, never lost, never archived")
    seed()
    projects = s.read("projects")
    by = {str(p["project_no"]): p for p in projects}
    by["4521"]["next_action_on"] = "2026-08-08"     # yesterday
    by["4524"]["next_action_on"] = "2026-08-09"     # today
    by["4525"]["next_action_on"] = "2026-08-10"     # tomorrow
    by["4522"]["next_action_on"] = "2026-08-01"     # lost
    by["4523"]["next_action_on"] = "2026-08-01"     # archived
    by["4526"]["next_action_on"] = "8/1/26"         # tracker-style, past
    s.write("projects", projects)
    res = s.call("list_projects", next_action_due=True)
    nos = sorted(str(p["project_no"]) for p in res.get("projects", []))
    r.check("yesterday and today are due; tomorrow, lost and archived are not; a tracker-style past date is due",
            res.get("ok") and nos == ["4521", "4524", "4526"], json.dumps(nos))
    res = s.call("list_projects", next_action_due=True, include_archived=True)
    nos = sorted(str(p["project_no"]) for p in res.get("projects", []))
    r.check("an archived project is not due even when archived projects are included",
            res.get("ok") and nos == ["4521", "4524", "4526"], json.dumps(nos))
    res = s.call("list_projects")
    r.check("without the flag the list is as before",
            res.get("ok") and res["count"] == 5, json.dumps(res.get("count")))
    res = s.call("list_projects", next_action_due=True, status="won")
    nos = sorted(str(p["project_no"]) for p in res.get("projects", []))
    r.check("it stacks with the other filters",
            res.get("ok") and nos == ["4521", "4524", "4526"], json.dumps(nos))

    # ---- 4. a re-import leaves them alone ----------------------------------------
    r.section("a re-import never overwrites the operator's next action")
    seed()
    s.call("update_project", project_no="4521",
           fields={"next_action": "Chase the revised PO", "next_action_on": "2026-08-08"},
           company_id="acme")
    merge = _load_merge(crm)

    def fresh(proj):
        return {"companies.json": [company("acme", "Ace Manufacturing")],
                "contacts.json": [], "vendors.json": [], "shipments.json": [],
                "invoices.json": [], "needs_review.json": [],
                "projects.json": [proj]}
    merged, rep = merge.merge_all(fresh(project("4521", "acme", revenue=75000)), str(s.path))
    pr = {str(p["project_no"]): p for p in merged["projects.json"]}
    r.check("with a changelog, the workbook record without the fields leaves them in place",
            pr["4521"].get("next_action") == "Chase the revised PO"
            and pr["4521"].get("next_action_on") == "2026-08-08", json.dumps(pr["4521"])[:200])
    r.check("while a field the operator never edited still refreshes",
            pr["4521"].get("revenue") == 75000)
    merged, rep = merge.merge_all(
        fresh(project("4521", "acme", next_action=None, next_action_on=None)), str(s.path))
    pr = {str(p["project_no"]): p for p in merged["projects.json"]}
    r.check("a workbook record carrying the keys as null does not clear them either",
            pr["4521"].get("next_action") == "Chase the revised PO"
            and pr["4521"].get("next_action_on") == "2026-08-08", json.dumps(pr["4521"])[:200])
    # missing_ok: a server that refused the update never wrote a changelog,
    # and that must read as red checks below, not a FileNotFoundError
    (s.path / "changelog.jsonl").unlink(missing_ok=True)
    merged, rep = merge.merge_all(fresh(project("4521", "acme", revenue=75000)), str(s.path))
    pr = {str(p["project_no"]): p for p in merged["projects.json"]}
    r.check("without a changelog (add-only), the record is left untouched, fields included",
            pr["4521"].get("next_action") == "Chase the revised PO"
            and pr["4521"].get("next_action_on") == "2026-08-08", json.dumps(pr["4521"])[:200])
    return r

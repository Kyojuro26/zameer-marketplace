#!/usr/bin/env python3
"""Mutation-test the rankings (0.1.42, Phase F): tests/regression/
test_rankings.py against mcp/server.py and view/build_view.py's embed, and
tests/regression/test_rankings_view.js (a live local_server.py in headless
Chromium) against view/build_view.py.

Every mutant is the tempting shortcut: average the projects' margins, take a
margin where there is no revenue, count a missing cost as zero, default to
every status, ignore the status or year filter, merge numberless projects,
credit a shared project to its first owner, lump the ownerless into a row,
rank smallest first or nulls first, widen the top 5, let a percentage claim a concentration line, skip an
unmatched invoice, divide PO-costed margin by quoted revenue, drop the
"overstates margin" warning, drop the grouping's exclusions from the total,
ignore the limit, or embed nothing -- and in the view: never re-ask the
server, drop the year, show dollars as cents, leave a customer click on the
rankings page, or print the top 5 as the top 10.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("a group's margin is the average of its projects' margins",
  '            g["num"] += num; g["den"] += den; g["n"] += 1',
  '            g["num"] += num / den if den else num; g["den"] += 1 if den else 0; g["n"] += 1'),
 ("a margin is taken where revenue is zero",
  '            if (_num(p.get("revenue")) or 0) <= 0:\n                return None, 0, "no_revenue_on_project"',
  '            if _num(p.get("revenue")) is None:\n                return None, 0, "no_revenue_on_project"'),
 ("a missing cost counts as zero",
  '            if _num(p.get("total_cost")) is None:\n                return None, 0, "no_cost_on_project"\n            return cents(p["revenue"]) - cents(p["total_cost"]), 0, None',
  '            return cents(p["revenue"]) - round((_num(p.get("total_cost")) or 0) * 100), 0, None'),
 ("the default status is all, not won",
  '        status = status or "won"', '        status = status or "all"'),
 ("the status filter is ignored",
  '        pop = [p for p in self.projects if status == "all" or p.get("status") == status]',
  '        pop = list(self.projects)'),
 ("the year filter is ignored",
  "        if year is not None:\n            pop = [p for p in pop if _key(p.get(\"year\")) == _key(year)]",
  "        if False:\n            pop = [p for p in pop if _key(p.get(\"year\")) == _key(year)]"),
 ("a project with several owners is credited to the first",
  '        k = " + ".join(owners)', '        k = owners[0]'),
 ("projects with no owner are lumped into a row of their own",
  '        if not owners:\n            return None, None, "no_owner"',
  '        if not owners:\n            return "(none)", "(none)", None'),
 ("rows are ranked smallest first",
  '                                  -(r_[metric]["value"] or 0), str(r_["key"])))',
  '                                  (r_[metric]["value"] or 0), str(r_["key"])))'),
 ("a row with nothing counted ranks first",
  '        rows.sort(key=lambda r_: (r_[metric]["value"] is None,',
  '        rows.sort(key=lambda r_: (r_[metric]["value"] is not None,'),
 ("the top 5 is six rows",
  '        return {"top5_share": sum(vals[:5]) / tot,', '        return {"top5_share": sum(vals[:6]) / tot,'),
 ("a percentage gets a concentration line",
  "        if metric in RANKING_RATIOS:\n            return {\"top5_share\": None,",
  "        if False:\n            return {\"top5_share\": None,"),
 ("an invoice QuickBooks lacks is skipped, not reported",
  '            if why:\n                return None, 0, why\n            total += m["amount_cents"]',
  '            if why:\n                continue\n            total += m["amount_cents"]'),
 ("PO-costed margin is divided by quoted revenue",
  '            return job["value_cents"], inv, None',
  '            return job["value_cents"], cents(p["revenue"]), None'),
 ("PO-costed margin loses its warning",
  '    "po_costed_margin_pct": PO_COSTED_WORDS + ". QuickBooks invoiced minus the "',
  '    "po_costed_margin_pct": "PO-costed. QuickBooks invoiced minus the "'),
 ("the total forgets the projects the grouping excluded",
  "                                 _tally(top_exc + [w for g in groups.values()",
  "                                 _tally([w for g in groups.values()"),
 ("numberless projects of one customer merge into one row",
  '            if not pno:\n                return f"#{i}|{cid}", f"(no number) {name}", None',
  '            if False:\n                return f"#{i}|{cid}", f"(no number) {name}", None'),
 ("the limit is ignored",
  '               "rows": rows[:limit] if limit else rows,', '               "rows": rows,'),
]
BUILD = [
 ("the built page embeds no ranking",
  '                           ("rankings", lambda: ctx.rankings(\n                               "quoted_revenue", "customer", "won", None, None))):',
  '                           ("rankings", lambda: None)):'),
]
VIEW = [
 ("a toggle re-renders the old answer instead of asking the server",
  "function rkSet(k, v){ RK[k] = v; return loadRankings(); }",
  "function rkSet(k, v){ RK[k] = v; if(filter === 'rankings') renderMain(); }"),
 ("the year is not sent",
  "  if(RK.year) args.year = Number(RK.year);", ""),
 ("a dollar value is shown as dollars where cents are meant",
  "        const raw = sh.value == null ? '' : (sh.unit === 'usd' ? sh.value_cents : sh.value);",
  "        const raw = sh.value == null ? '' : sh.value;"),
 ("a customer click stays on the rankings page",
  "  if(filter === 'project' || filter === 'receivable' || filter === 'live' || filter === 'rankings'){",
  "  if(filter === 'project' || filter === 'receivable' || filter === 'live'){"),
 ("the top 5 is printed as the top 10",
  "data-top10=\"${c.top10_share == null ? '' : c.top10_share}\"",
  "data-top10=\"${c.top5_share == null ? '' : c.top5_share}\""),
]


def main():
    worst = 0
    for title, target, test, mutants in (
            ("SERVER -- mcp/server.py", "mcp/server.py", "./tests/regression/test_rankings.py", SERVER),
            ("BUILD -- view/build_view.py", "view/build_view.py", "./tests/regression/test_rankings.py", BUILD),
            ("VIEW -- view/build_view.py", "view/build_view.py", "./tests/regression/test_rankings_view.js", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

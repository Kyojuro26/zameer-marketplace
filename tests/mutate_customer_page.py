#!/usr/bin/env python3
"""Mutation-test G5 (0.1.43) in view/build_view.py, graded by
tests/regression/test_customer_page_view.js through the real click path on a
live server: the customer page's Won / Pending / Lost footer, and the Add-lead
form's matches that turn into a new project for an existing company.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_customer_page_view.js"

VIEW = [
 ("every status is folded into each total",
  "    .map(s=>[s, prs.filter(p=>sv(p.status).trim()===s).reduce((a,p)=>a+numv(p.revenue),0)])\n",
  "    .map(s=>[s, prs.reduce((a,p)=>a+numv(p.revenue),0)])\n"),
 ("a status is compared raw, so 'Won ' is left out",
  "    .map(s=>[s, prs.filter(p=>sv(p.status).trim()===s).reduce((a,p)=>a+numv(p.revenue),0)])\n",
  "    .map(s=>[s, prs.filter(p=>p.status===s).reduce((a,p)=>a+numv(p.revenue),0)])\n"),
 ("a zero total is shown",
  "    .filter(([, t])=>t !== 0);\n", "    ;\n"),
 ("lost revenue is not shown",
  "  const rows = ['won', 'pending', 'lost']\n", "  const rows = ['won', 'pending']\n"),
 ("the old single Total comes back",
  "    `</tbody>${statusTotals(prs)}</table>`",
  "    `</tbody><tfoot><tr><td colspan=\"4\">Total</td><td class=\"num\">${money(prs.reduce((a,p)=>a+numv(p.revenue),0))}</td></tr></tfoot></table>`"),
 ("a match is case-sensitive",
  "function nameKey(v){ return st(v).trim().replace(/\\s+/g, ' ').toLowerCase(); }",
  "function nameKey(v){ return st(v).trim().replace(/\\s+/g, ' '); }"),
 ("spacing inside a name is not collapsed",
  "function nameKey(v){ return st(v).trim().replace(/\\s+/g, ' ').toLowerCase(); }",
  "function nameKey(v){ return st(v).trim().toLowerCase(); }"),
 ("vendors and archived companies are offered",
  "  const hits = q ? projectOwners().filter(",
  "  const hits = q ? (DATA.companies||[]).filter("),
 ("the lead form offers no matches",
  "<input id=\"c_name\"${role==='lead'?' oninput=\"leadMatches()\"':''}/>",
  "<input id=\"c_name\"/>"),
 ("choosing a match creates a company as well",
  "  openNewProject(cid);                       // no company is created\n",
  "  CRM.call('create_company', {fields: {display_name: 'Copy of ' + cid, role: 'lead'}});\n"
  "  openNewProject(cid);                       // no company is created\n"),
 ("choosing a match opens the picker form instead of that company's",
  "  openNewProject(cid);                       // no company is created\n",
  "  openNewProject(null, {});                       // no company is created\n"),
]
# Not mutated: leadToProject's `n_status = 'pending'`. openNewProject's status
# select already lists pending first, so dropping the preset is equivalent;
# the check "status preset to pending" holds either way.

sys.exit(mutate(SRC, TEST, "view/build_view.py", VIEW))

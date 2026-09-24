#!/usr/bin/env python3
"""Mutation-test "+ New project" from anywhere (0.1.43 G3).

SERVER mutants in mcp/server.py are graded by tests/regression/test_new_project.py:
a vendor is refused naming it (the named exception), a lead is not, and a
project number stays unique across the business.

VIEW mutants in view/build_view.py are graded by
tests/regression/test_new_project_view.js through the real click path on a live
server: the picker's contents and order, typing to narrow it, the bucket from
the Live tab, the message saying where the job appears, the add row staying
hidden, and the company header keeping its own form.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
T_SERVER = "./tests/regression/test_new_project.py"
T_VIEW = "./tests/regression/test_new_project_view.js"

SERVER = [
 ("a vendor takes a project again",
  '            if str(co.get("role") or "").strip().lower() == "vendor":\n',
  "            if False:\n"),
 ("a lead is refused as well",
  '            if str(co.get("role") or "").strip().lower() == "vendor":\n',
  '            if str(co.get("role") or "").strip().lower() in ("vendor", "lead"):\n'),
 ("the refusal does not name the company",
  "                    f\"company '{fields['company_id']}' ({co.get('display_name') or 'no name'}) \"\n",
  "                    f\"that company \"\n"),
 ("a number is unique per customer, not across the business",
  "            if any(_key(p.get(\"project_no\")) == pn for p in projects):\n"
  "                raise StoreError(f\"project '{pn}' already exists\")",
  "            if any(_key(p.get(\"project_no\")) == pn and p.get(\"company_id\") == fields[\"company_id\"]\n"
  "                   for p in projects):\n"
  "                raise StoreError(f\"project '{pn}' already exists\")"),
]

VIEW = [
 ("the picker lists vendors",
  "    .filter(c=>c && !c.archived && (c.role==='customer' || c.role==='lead'))\n",
  "    .filter(c=>c && !c.archived)\n"),
 # DECLARED EQUIVALENT, retired rather than deleted:
 #   "the picker lists archived companies" -- dropping `!c.archived` from
 #   projectOwners().
 # Proof: no archived company can be in DATA.companies -- list_companies drops
 # them (the page's refresh passes no include_archived), build_view.py drops
 # them from the embedded build, and deleteCompany removes the record from
 # DATA on archiving -- so the filter is a guard with nothing reachable to
 # grade, and the test's archived fixture is absent from the picker either way.
 ("the picker lists leads no more",
  "    .filter(c=>c && !c.archived && (c.role==='customer' || c.role==='lead'))\n",
  "    .filter(c=>c && !c.archived && c.role==='customer')\n"),
 ("the picker is not sorted by name",
  "    .sort((a,b)=>st(a.display_name||a.company_id).localeCompare(st(b.display_name||b.company_id), undefined, {sensitivity:'base'}));\n",
  "    .reverse();\n"),
 ("typing does not narrow the picker",
  "    o.hidden = !!q && !sv(o.textContent).includes(q);\n", "    o.hidden = false;\n"),
 ("from Live the bucket defaults to none",
  "      ${buckets.map((b,i)=>`<option value=\"${esc(b.key)}\"${i===0?' selected':''}>${esc(bucketLabel(b.key))}</option>`).join('')}\n"
  "      <option value=\"\">none \\u2014 not on the Live screen</option></select></div>` : '';",
  "      <option value=\"\">none \\u2014 not on the Live screen</option>\n"
  "      ${buckets.map((b,i)=>`<option value=\"${esc(b.key)}\">${esc(bucketLabel(b.key))}</option>`).join('')}</select></div>` : '';"),
 ("the bucket is never sent",
  "  if(bucket) fields.tracker_status = bucket;\n", ""),
 ("the Projects tab opens the Live form, and its jobs land on the Live screen",
  'onclick="openNewProject(null,{})">+ New project</button></div>`;',
  'onclick="openNewProject(null,{fromLive:true})">+ New project</button></div>`;'),
 ("the Live tab's button is gone",
  '    <button class="pill-btn" data-act="new-project" style="margin-left:auto" onclick="openNewProject(null,{fromLive:true})">+ New project</button></div>`;',
  "    </div>`;"),
 ("the message does not say where the job appears",
  "      + (bucket ? `on the Live screen under ${bucketLabel(bucket)}` : 'not on the Live screen'), '\\u2713');",
  "      + 'saved', '\\u2713');"),
 ("saving with no customer picked is not caught in the form",
  "  if(picked && !ownCompany(cid)){ msg.textContent='✗ pick a customer'; msg.className='saved show errc'; return; }\n", ""),
 ("the company header opens the picker too",
  "  const c = cid == null ? null : ownCompany(cid);\n", "  const c = null;\n"),
 ("the add row shows on the Live tab after the app connects",
  "  if (add) add.style.display = addRowShown(filter) ? 'flex' : 'none';\n",
  "  if (add) add.style.display = 'flex';\n"),
 ("the add row shows on the Projects tab",
  "  return !['project', 'receivable', 'live', 'cfo', 'quotes', 'rankings'].includes(f);\n",
  "  return !['receivable', 'live', 'cfo', 'quotes', 'rankings'].includes(f);\n"),
]


def main():
    worst = 0
    for title, test, target, mutants in (
            ("SERVER -- mcp/server.py", T_SERVER, "mcp/server.py", SERVER),
            ("VIEW -- view/build_view.py", T_VIEW, "view/build_view.py", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

#!/usr/bin/env python3
"""Mutation-test tests/regression/test_view.js -- the view's own decisions.

test_view.js was mutation-covered only through mutate_failure.py's SITES pass,
whose subject is what the app does when a call never comes back. The checks
below grade a different class: what the app OFFERS the operator, and whether
the offer is true. A row rendered clickable that does nothing on click is the
screen asserting an affordance the store cannot honour.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "view/build_view.py"

M = [
 # ---- a numberless project is not offered as something to open ----------
 ("every project counts as numbered, so numberless rows are clickable again",
  "function hasProjectNo(p){ return st(p && p.project_no).trim() !== ''; }",
  "function hasProjectNo(p){ return true; }"),
 ("the Projects tab row keeps its onclick regardless of number",
  "    rows.map(p=>`<tr ${projRowClick(p)}>\n      <td>${projNoCell(p)}</td>",
  "    rows.map(p=>`<tr class=\"click\" onclick=\"openProject('${jesc(st(p.project_no))}')\">\n      <td>${projNoCell(p)}</td>"),
 ("the company page row keeps its onclick regardless of number",
  "    prs.map(p=>`<tr ${projRowClick(p)}>\n      <td>${projNoCell(p)}</td>",
  "    prs.map(p=>`<tr class=\"click\" onclick=\"openProject('${jesc(p.project_no||'')}')\">\n      <td>${projNoCell(p)}</td>"),
 ("the projects sidebar item keeps its onclick",
  "    <div class=\"citem\" ${projItemClick(p)}>",
  "    <div class=\"citem\" onclick=\"openProject('${jesc(st(p.project_no))}')\">"),
 ("the Live card offers Edit on a job it cannot open",
  "      <span style=\"margin-left:auto\">${hasProjectNo(p)\n"
  "        ? `<button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}','${jesc(st(p.company_id))}')\">Edit</button>`\n"
  "        : `<span class=\"muted nw\">${esc(NO_NUMBER_NOTE)}</span>`}</span>",
  "      <span style=\"margin-left:auto\"><button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}','${jesc(st(p.company_id))}')\">Edit</button></span>"),
 ("the Live sidebar item keeps its onclick",
  "      h += `<div class=\"citem\" ${hasProjectNo(r.p)?`onclick=\"liveJump('${jesc(st(r.p.company_id))}','${jesc(st(r.p.project_no))}')\"`:''}>",
  "      h += `<div class=\"citem\" onclick=\"liveJump('${jesc(st(r.p.company_id))}','${jesc(st(r.p.project_no))}')\">"),
 ("a save no longer re-baselines the drawer's snapshotted controls",
  "      if(body.querySelectorAll){\n"
  "        body.querySelectorAll('input,select,textarea').forEach(el=>{\n"
  "          if(el.getAttribute && el.getAttribute('data-orig') !== null) el.setAttribute('data-orig', el.value || '');\n"
  "        });\n"
  "      }\n", ""),
 ("the row goes inert but stops saying why",
  "const NO_NUMBER_NOTE = 'no number \\u2014 give it one in chat to edit here';",
  "const NO_NUMBER_NOTE = '';"),
 ("a numberless row is dropped from the table instead of shown inert",
  "function projNoCell(p){ return hasProjectNo(p) ? `<b>${esc(st(p.project_no))}</b>` : `<span class=\"muted\">${esc(NO_NUMBER_NOTE)}</span>`; }",
  "function projNoCell(p){ return hasProjectNo(p) ? `<b>${esc(st(p.project_no))}</b>` : `</td></tr><!--`; }"),
 ("openProject matches a null number by its string form again",
  "  if(!st(pno).trim()) return;\n"
  "  const p=findProject(pno, cid); if(!p) return;",
  "  const p=DATA.projects.find(x=>String(x.project_no)===String(pno)); if(!p) return;"),
 # ---- a project is (number, customer) --------------------------------------
 ("the lookup finds the first record of that number, whichever customer's",
  "  return DATA.projects.find(x => hasProjectNo(x) && st(x.project_no) === st(pno)\n"
  "                              && (!hasCid(cid) || ck(x.company_id) === ck(cid)));",
  "  return DATA.projects.find(x => hasProjectNo(x) && st(x.project_no) === st(pno));"),
 # ---- review round 1: three classes on the page, one in the builder --------
 ("an empty customer means no customer again",
  "function hasCid(cid){ return cid !== undefined && cid !== null; }",
  "function hasCid(cid){ return cid !== undefined && cid !== null && st(cid) !== ''; }"),
 ("the Receivables link uses the invoice's customer as a hard filter",
  "  const holders = projectsNumbered(pno);\n"
  "  if(holders.some(x => ck(x.company_id) === ck(cid))) return st(cid);\n"
  "  return holders.length === 1 ? st(holders[0].company_id) : null;",
  "  return st(cid);"),
 ("the delete mirror is confined to the customer on an unshared number too",
  "  return projectsNumbered(pno).length > 1 ? ck(cid) : null;",
  "  return ck(cid);"),
 # ---- review round 2: the other holders, and one key form ------------------
 ("the rename mirror carries only records filed under the customer",
  "    const mine = (x)=> !others.has(ck(x.company_id));",
  "    const mine = (x)=> !hasCid(cid) || ck(x.company_id)===ck(cid);"),
 ("a padded company id is another customer on the page",
  "function ck(v){ return st(v).trim(); }",
  "function ck(v){ return st(v); }"),
 ("the page hides invoices by the number alone again",
  "    data[\"invoices\"] = [i for i in data[\"invoices\"]\n"
  "                        if not _srv._invoice_hidden(i, arch)]",
  "    data[\"invoices\"] = [i for i in data[\"invoices\"]\n"
  "                        if _srv._key(i.get(\"project_no\")) not in arch.archived]"),
 ("the page hides legs by the number alone again",
  "    data[\"shipments\"] = [x for x in data[\"shipments\"]\n"
  "                         if not _srv._shipment_hidden(x, arch)]",
  "    data[\"shipments\"] = [x for x in data[\"shipments\"]\n"
  "                         if not _srv._shipment_project_nos(x) <= arch.archived]"),
 ("the Live card Edit passes the number alone",
  "        ? `<button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}','${jesc(st(p.company_id))}')\">Edit</button>`",
  "        ? `<button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}')\">Edit</button>`"),
 ("the table rows pass the number alone",
  "function projRowClick(p){ return hasProjectNo(p) ? `class=\"click\" onclick=\"openProject('${jesc(st(p.project_no))}','${jesc(st(p.company_id))}')\"` : ''; }",
  "function projRowClick(p){ return hasProjectNo(p) ? `class=\"click\" onclick=\"openProject('${jesc(st(p.project_no))}')\"` : ''; }"),
 ("the sidebar items pass the number alone",
  "function projItemClick(p){ return hasProjectNo(p) ? `onclick=\"openProject('${jesc(st(p.project_no))}','${jesc(st(p.company_id))}')\"` : ''; }",
  "function projItemClick(p){ return hasProjectNo(p) ? `onclick=\"openProject('${jesc(st(p.project_no))}')\"` : ''; }"),
 ("the drawer bakes no customer into its handlers",
  "    <button class=\"btn\" id=\"saveBtn\" onclick=\"saveProject('${jesc(pno)}','${jesc(cid)}')\">Save changes</button>",
  "    <button class=\"btn\" id=\"saveBtn\" onclick=\"saveProject('${jesc(pno)}')\">Save changes</button>"),
 ("the save drops company_id from its payload",
  "  const ok = await doSave('update_project', {project_no: pno, fields, company_id: cid}, (r)=>{",
  "  const ok = await doSave('update_project', {project_no: pno, fields}, (r)=>{"),
 ("the local mirror after a save edits the first record of that number",
  "    const p=findProject(pno, cid);\n"
  "    if(p) Object.assign(p, r.project || fields);",
  "    const p=DATA.projects.find(x=>String(x.project_no)===String(pno));\n"
  "    if(p) Object.assign(p, r.project || fields);"),
 ("the rename drops company_id",
  "    try{ rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno, company_id: cid}); }",
  "    try{ rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno}); }"),
 ("the delete drops company_id",
  "  try{ r = await CRM.call('archive_project', {project_no:pno, company_id:cid}); }",
  "  try{ r = await CRM.call('archive_project', {project_no:pno}); }"),
 ("a delete removes every record of that number from the page",
  "    DATA.projects=DATA.projects.filter(x=>!(mine(x) && String(x.project_no)===String(pno)));",
  "    DATA.projects=DATA.projects.filter(x=>String(x.project_no)!==String(pno));"),
 ("a new leg drops company_id",
  "  await doSave('create_shipment', {project_no:pno, fields, company_id:cid}, (r)=>{",
  "  await doSave('create_shipment', {project_no:pno, fields}, (r)=>{"),
 # ---- the deal date follows the date rule; two labels ---------------------
 ("the deal date is sent on every save again",
  "  dateIfChanged('f_date', fields, 'date');     // never send a date he did not touch",
  "  fields.date = document.getElementById('f_date').value.trim() || null;"),
 ("the deal date goes back to a plain text box",
  "      <div class=\"field\"><label>Deal date</label>${dateInput('f_date', p.date)}</div>",
  "      <div class=\"field\"><label>Deal date</label><input id=\"f_date\" value=\"${esc(p.date||'')}\"/></div>"),
 ("the deal date is never snapshotted, so a change is never sent",
  "  snapDates(['f_date']);\n", ""),
 ("the invoice table header says Invoiced again",
  "<th class=\"num\">Invoice date</th><th class=\"num\">Outstanding</th>",
  "<th class=\"num\">Invoiced</th><th class=\"num\">Outstanding</th>"),
 ("the Live card's date loses its label",
  "  return d ? 'started ' + esc(d) : 'no start date';",
  "  return d ? esc(d) : 'no start date';"),
]

sys.exit(mutate(SRC, "./tests/regression/test_view.js", F, M))

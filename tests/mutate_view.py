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
  "        ? `<button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}')\">Edit</button>`\n"
  "        : `<span class=\"muted nw\">${esc(NO_NUMBER_NOTE)}</span>`}</span>",
  "      <span style=\"margin-left:auto\"><button class=\"pill-btn\" onclick=\"openProject('${jesc(st(p.project_no))}')\">Edit</button></span>"),
 ("the Live sidebar item keeps its onclick",
  "    return `<div class=\"citem\" ${projItemClick(r.p)}>",
  "    return `<div class=\"citem\" onclick=\"openProject('${jesc(st(r.p.project_no))}')\">"),
 ("the row goes inert but stops saying why",
  "const NO_NUMBER_NOTE = 'no number \\u2014 give it one in chat to edit here';",
  "const NO_NUMBER_NOTE = '';"),
 ("a numberless row is dropped from the table instead of shown inert",
  "function projNoCell(p){ return hasProjectNo(p) ? `<b>${esc(st(p.project_no))}</b>` : `<span class=\"muted\">${esc(NO_NUMBER_NOTE)}</span>`; }",
  "function projNoCell(p){ return hasProjectNo(p) ? `<b>${esc(st(p.project_no))}</b>` : `</td></tr><!--`; }"),
 ("openProject matches a null number by its string form again",
  "  if(!st(pno).trim()) return;\n"
  "  const p=DATA.projects.find(x=>hasProjectNo(x) && st(x.project_no)===st(pno)); if(!p) return;",
  "  const p=DATA.projects.find(x=>String(x.project_no)===String(pno)); if(!p) return;"),
]

sys.exit(mutate(SRC, "./tests/regression/test_view.js", F, M))

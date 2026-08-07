#!/usr/bin/env python3
"""Mutation-test tests/regression/test_receivables.js.

Every number on the Receivables screen is DERIVED -- outstanding, days late,
which bucket -- so a wrong answer here looks entirely plausible. These mutants
are the plausible wrong answers.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "view/build_view.py"

M = [
 # ---- the money ---------------------------------------------------------
 ("partial % read as UNPAID rather than received",
  "    if(paidPct >= 0 && paidPct <= 100) return Math.round(amt * (1 - paidPct/100));",
  "    if(paidPct >= 0 && paidPct <= 100) return Math.round(amt * (paidPct/100));"),
 ("a missing amount becomes zero instead of null",
  "  const amt = invoiceAmount(v); if(amt == null) return null;",
  "  const amt = invoiceAmount(v); if(amt == null) return 0;"),
 ("an unlinked invoice is given an amount of zero",
  "  const pno = st(v.project_no); if(!pno) return null;",
  "  const pno = st(v.project_no); if(!pno) return 0;"),
 ("the amount ignores which company the project belongs to",
  """  const p = DATA.projects.find(x => String(x.project_no) === String(pno)
                                 && st(x.company_id) === st(v.company_id));""",
  "  const p = DATA.projects.find(x => String(x.project_no) === String(pno));"),
 ("a paid invoice still shows its full value outstanding",
  "  if(ps.startsWith('paid')) return 0;\n  const m = ps.match",
  "  const m = ps.match"),
 ("a project with no revenue is counted as zero",
  "  if(!p || p.revenue == null || isNaN(Number(p.revenue))) return null;",
  "  if(!p) return null;\n  if(p.revenue == null) return 0;"),

 # ---- lateness and bucketing --------------------------------------------
 ("days late can go negative for a future invoice",
  "  return n > 0 ? n : 0;", "  return n;"),
 ("paid invoices fall into the overdue bucket",
  "  if(st(v.payment_status).startsWith('paid')) return 'Paid';\n", ""),
 ("an unreadable date is treated as overdue rather than unknown",
  "  if(!d) return 'No due date';", "  if(!d) return 'Overdue';"),
 ("the due-this-week window is dropped",
  "  if(d <= soon) return 'Due this week';\n", ""),
 ("the company page gets its own copy of the bucket rule",
  "    const bucketOf = (v)=> invoiceBucket(v, todayStr, soonStr);",
  "    const bucketOf = (v)=> st(v.payment_status).startsWith('paid') ? 'Paid'\n"
  "      : (dueOn(v) && dueOn(v) < todayStr ? 'Overdue' : 'Due later');"),

 # ---- ordering and totals -----------------------------------------------
 ("newest debt is listed first instead of oldest",
  "    if(ad!==bd) return ad.localeCompare(bd);",
  "    if(ad!==bd) return bd.localeCompare(ad);"),
 ("the total silently counts unpriced invoices as zero",
  "  const known = rows.filter(r => r.owed != null);",
  "  const known = rows.map(r => ({owed: r.owed || 0}));"),
 ("the total stops saying what it excludes",
  """      unknown ? esc(`excludes ${unknown} invoice${unknown>1?'s':''} with no amount on file`) : ''""",
  "      ''"),
 ("the view opens on Paid rather than Overdue",
  "let recvBucket = 'Overdue';", "let recvBucket = 'Paid';"),

 # ---- presentation that carries meaning ---------------------------------
 ("an unparseable date renders blank instead of as stored",
  "  if(!iso) return t;                       // unparseable: show what is stored",
  "  if(!iso) return '';"),
 ("dates render raw again, so two formats reappear in one column",
  "      <td class=\"num\">${esc(fmtDate(r.due)||'—')}</td>",
  "      <td class=\"num\">${esc(st(r.due)||'—')}</td>"),
 ("a stored status string is shown to the operator raw",
  "  if(low.startsWith('partial')) return `<span class=\"badge b-pending\">Part paid${m?' '+m[1]+'%':''}</span>`;",
  "  if(low.startsWith('partial')) return `<span class=\"badge b-pending\">${esc(s)}</span>`;"),
 ("an unlinked invoice shows an empty project cell",
  "      : '<span class=\"badge b-stage\">Not linked</span>';", "      : '';"),

 # ---- wiring -------------------------------------------------------------
 ("the receivables KPI stops navigating",
  "    [`Open receivables (${thisYear})`, money(recv), 'receivable'],",
  "    [`Open receivables (${thisYear})`, money(recv), null],"),
 ("the KPI is mouse-only",
  """         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setFilter('${jesc(go)}')}\"""",
  '         data-nokeys="1"'),
 ("selecting a company leaves you stranded in the receivables list",
  "  if(filter === 'project' || filter === 'receivable'){ setFilter('all'); fetchEnrichment(id); return; }",
  "  if(filter === 'project'){ setFilter('all'); fetchEnrichment(id); return; }"),
]

sys.exit(mutate(SRC, "./tests/regression/test_receivables.js", F, M))

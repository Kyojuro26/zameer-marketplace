#!/usr/bin/env python3
"""Mutation-test tests/regression/test_split_invoice.js against build_view.py.

The view prices each Receivables row itself, a documented duplication of the
server's rule, so the 0.1.37 exclusion had to be copied into it. These are
the plausible wrong copies: the check missing, the check before the paid
short-circuit (a paid row on a split-billed project turns into a dash), the
count taken across customers, an off-by-one on "more than one", and the row
falling back to the "no amount on file" wording that reads as a linking
error. Every check that kills one runs in a real headless Chromium.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_split_invoice.js"
F = "view/build_view.py"

M = [
 ("the view's split check is removed: each row priced at the full project revenue",
  "  if(splitBilled(v)) return null;\n", ""),
 ("the split check runs BEFORE the paid short-circuit",
  "  const ps = st(v.payment_status).toLowerCase();\n"
  "  if(ps.startsWith('paid')) return 0;\n"
  "  const amt = invoiceAmount(v); if(amt == null) return null;\n",
  "  if(splitBilled(v)) return null;\n"
  "  const ps = st(v.payment_status).toLowerCase();\n"
  "  if(ps.startsWith('paid')) return 0;\n"
  "  const amt = invoiceAmount(v); if(amt == null) return null;\n"),
 ("invoices are counted by project number alone, across customers",
  "    if(st(x.project_no).trim() === pno && st(x.company_id) === cid && ++n > 1) return true;",
  "    if(st(x.project_no).trim() === pno && ++n > 1) return true;"),
 ("more than one invoice is read as more than two",
  "    if(st(x.project_no).trim() === pno && st(x.company_id) === cid && ++n > 1) return true;",
  "    if(st(x.project_no).trim() === pno && st(x.company_id) === cid && ++n > 2) return true;"),
 ("a split-billed row falls back to the 'no amount on file' wording",
  "       : k === 'split' ? 'linked correctly, but the project carries more than one invoice and no per-invoice amount exists yet'\n",
  "       : k === 'split' ? 'no project linked, so no amount on file'\n"),
 ("the row's inline note is dropped, leaving a bare dash",
  "          ? ' <span style=\"font-size:11px\">more than one invoice on this project</span>' : ''}</span>`",
  "          ? '' : ''}</span>`"),
 ("the footer stops naming the split-billed rows it excludes",
  "       split ? `excludes ${split} invoice${split>1?'s':''} on a project with more than one invoice` : '']",
  "       '']"),
 ("the split note is shown whenever the project has two invoices, before the no-amount reason",
  "  if(invoiceAmount(v) == null) return 'no_amount';\n  if(splitBilled(v)) return 'split';",
  "  if(splitBilled(v)) return 'split';\n  if(invoiceAmount(v) == null) return 'no_amount';"),
 # re-anchored 0.1.44: reasonLabel gained a second named reason
 ("the caveat label loses its words",
  "  return k === 'multiple_invoices_on_project' ? 'on a project with more than one invoice'\n",
  "  return k === 'multiple_invoices_on_project' ? 'multiple invoices on project'\n"),
]

sys.exit(mutate(SRC, TEST, F, M))

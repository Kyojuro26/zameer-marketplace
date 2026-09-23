#!/usr/bin/env python3
"""Mutation-test the CFO report (0.1.40, Phase D): tests/regression/test_cfo.py
against mcp/server.py, and tests/regression/test_cfo_view.js (a live
local_server.py in headless Chromium) against view/build_view.py.

Every mutant is the tempting shortcut: sum the export's signs raw, count a
bill payment as spend, guess the sign of an unknown type, drop the export
block on bills, price a job with no legs at 100%, treat an unbilled PO as free,
hand a many-job customer's expense to one job, count a PO that does not
resolve, estimate committed-out with no PO status, count paid invoices as
open, lose the ranking, merge vendor rows by CRM resolution, fold the split
line into overhead, read a missing snapshot as $0, drop the basis facts, break
the project roll-up -- and in the view: show $0 for a missing figure, drop the
stale marker, print a reason code, or shorten the PO-costed warning.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("the export's signs are summed raw",
  '            row = dict(r_, cost_cents=QBO_COST_SIGN[t] * r_["amount_cents"])',
  '            row = dict(r_, cost_cents=r_["amount_cents"])'),
 ("a bill payment is not set aside first",
  "                    or t in QBO_BILL_PAYMENT_TYPES:", "                    or False:"),
 ("a type with no known sign is guessed as a cost",
  "            if t not in QBO_COST_SIGN:\n                other[t] = other.get(t, 0) + 1\n                continue\n"
  '            row = dict(r_, cost_cents=QBO_COST_SIGN[t] * r_["amount_cents"])',
  '            row = dict(r_, cost_cents=QBO_COST_SIGN.get(t, -1) * r_["amount_cents"])'),
 ("bills from an export are not excluded as a block",
  '            elif from_export:\n                rw = "bills_not_linkable_from_export"\n', ""),
 ("a job with no legs is priced with no cost",
  '            elif not j["legs"]:\n                rw = "cost_incomplete"\n', ""),
 ("a PO with no bill is treated as costing nothing",
  "                        elif n in pos:\n                            unbilled = True",
  "                        elif n in pos:\n                            pass"),
 ("an expense of a customer with several jobs goes to one of them",
  "                if len(ks) == 1:", "                if ks:"),
 ("a PO number that does not resolve still PO-costs the job",
  '                    n not in pos or len(pos[n]["vendors"]) != 1', "                    False"),
 ("a job with no PO on any leg is PO-costed at its full invoice",
  '            elif not any(per_leg):\n                pw = "no_po_on_job"\n', ""),
 ("committed-out counts POs with no status",
  '        known = {k: v for k, v in pos.items() if v["status"] - {None}}',
  "        known = pos"),
 ("a paid invoice counts as open",
  '                and r_["open_cents"] > 0]', "                ]"),
 ("who owes the most is not ranked by amount",
  '        who.sort(key=lambda w: (-w["open_usd"]["value_cents"], str(w["name"])))',
  '        who.sort(key=lambda w: str(w["name"]))'),
 ("vendor rows are merged by their CRM resolution",
  '                by_vendor.setdefault(r_.get("vendor"), []).append(r_)',
  '                by_vendor.setdefault(vres(r_.get("vendor"))[0] or r_.get("vendor"), []).append(r_)'),
 ("the split-across-accounts line is folded into overhead",
  '            split = [r_ for r_ in rows if r_.get("split_account") is None]',
  "            split = []"),
 ("a missing cash snapshot reads as a $0 bank total",
  '            "bank_total_usd": _cents_shape(sum(a["balance_cents"] for a in banks), "usd",\n'
  '                                           len(banks), {}, basis_b),',
  '            "bank_total_usd": _cents_shape(sum(a["balance_cents"] for a in banks), "usd",\n'
  '                                           max(1, len(banks)), {}, basis_b),'),
 ("the realized basis drops jobs counted, COGS share and unattributed dollars",
  '                                                    realized_basis_head + ". " + facts),',
  "                                                    realized_basis_head),"),
 ("a project's invoices do not roll up to it",
  '            if _key(pno):\n                return ("project", _key(pno), cid)\n'
  '            if _key(inv_no):\n                return ("invoice", _key(inv_no), cid)',
  '            if _key(inv_no):\n                return ("invoice", _key(inv_no), cid)\n'
  '            if _key(pno):\n                return ("project", _key(pno), cid)'),
]
VIEW = [
 ("a missing figure renders as $0.00",
  "  return (sh && sh.value_cents != null) ? moneyCents(sh.value_cents)",
  "  return sh ? moneyCents(sh.value_cents || 0)"),
 ("the stale marker is never shown",
  "    + (m.stale ? ` <b class=\"badge\" style=\"color:var(--red)\">stale",
  "    + (false ? ` <b class=\"badge\" style=\"color:var(--red)\">stale"),
 ("an exclusion shows its code, not words",
  "  if(ex.length) return ex.map(k => `${n(k)} ${esc(reasonLabel(k))}`).join(' \\u00b7 ');",
  "  if(ex.length) return ex.map(k => `${n(k)} ${esc(k)}`).join(' \\u00b7 ');"),
 ("the PO-costed column loses its warning",
  '<th class="num">PO-costed: excludes costs paid directly as expenses, so it overstates margin</th>',
  '<th class="num">PO-costed</th>'),
]


def main():
    worst = 0
    for title, target, test, mutants in (
            ("SERVER -- mcp/server.py", "mcp/server.py", "./tests/regression/test_cfo.py", SERVER),
            ("VIEW -- view/build_view.py", "view/build_view.py",
             "./tests/regression/test_cfo_view.js", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

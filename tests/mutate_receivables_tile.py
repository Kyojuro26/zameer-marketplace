#!/usr/bin/env python3
"""Mutation-test the Open receivables tile (0.1.44 H2) in view/build_view.py,
graded by tests/regression/test_receivables_tile_view.js on a live server:
with a snapshot the tile leads with QuickBooks' open balance -- the same shape
the Receivables header sums -- dated, stale-flagged, with the quoted figure and
its denominator beneath; with none it is byte-identical to 0.1.43.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_receivables_tile_view.js"
_KPI_Q = ("  // $179,545.38 (0.1.44). No snapshot: exactly as before.\n"
          "  const q = qboLedger('qbo_open_receivable_usd');\n")

M = [
 ("the tile falls back to the quoted figure when a snapshot exists",
  "  if(q){\n    recvN = q.value_cents == null", "  if(false){\n    recvN = q.value_cents == null"),
 ("the tile reads a different shape from the header",
  _KPI_Q, _KPI_Q.replace("qbo_open_receivable_usd", "invoiced_usd")),
 ("a stale snapshot is not flagged on the tile",
  "      + qboStaleBadge(q)\n      + `<br>", "      + `<br>"),
 ("the quoted figure is not shown beneath",
  "      + `<br>${ex && ex.value != null ? money(ex.value) : 'nothing priced'} quoted`\n", ""),
 ("QuickBooks' denominator is dropped",
  "    recvL = `Open receivables \\u00b7 QuickBooks as of ${esc(fmtDate(q.as_of))} \\u00b7 ${esc(shapeCaveat(q))}`\n",
  "    recvL = `Open receivables \\u00b7 QuickBooks as of ${esc(fmtDate(q.as_of))}`\n"),
 ("the as-of date is dropped",
  "    recvL = `Open receivables \\u00b7 QuickBooks as of ${esc(fmtDate(q.as_of))} \\u00b7 ${esc(shapeCaveat(q))}`\n",
  "    recvL = `Open receivables \\u00b7 ${esc(shapeCaveat(q))}`\n"),
 ("the headline is rounded to the dollar",
  "    recvN = q.value_cents == null ? '\\u2014' : moneyCents(q.value_cents);\n",
  "    recvN = q.value_cents == null ? '\\u2014' : money(q.value_cents / 100);\n"),
]

sys.exit(mutate(SRC, TEST, "view/build_view.py", M))

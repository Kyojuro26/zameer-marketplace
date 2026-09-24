#!/usr/bin/env python3
"""Mutation-test the QuickBooks customer check (0.1.44 H3).

SERVER mutants in mcp/server.py are graded by tests/regression/test_qbo_customer.py:
a tied company whose QuickBooks row names someone else is excluded as
qbo_customer_mismatch with both names; an agreeing row prices silently; an
unlinked company or a nameless row prices and is counted as not verified.
VIEW mutants in view/build_view.py are graded by
tests/regression/test_receivables_tile_view.js: the invoice names both.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("a customer mismatch is priced anyway",
  "            if self.qbo_customer_verdict(inv, matched)[0] == \"mismatch\":\n"
  "                return None, \"qbo_customer_mismatch\"\n", ""),
 ("an unverified match is excluded instead of counted",
  "            if self.qbo_customer_verdict(inv, matched)[0] == \"mismatch\":\n",
  "            if self.qbo_customer_verdict(inv, matched)[0] != \"agrees\":\n"),
 ("a qbo_name is not a tie",
  "        tied = bool(q) or (bool(dk) and dk in self.qbo_customer_keys())\n",
  "        tied = bool(dk) and dk in self.qbo_customer_keys()\n"),
 ("a display name QuickBooks uses is not a tie",
  "        tied = bool(q) or (bool(dk) and dk in self.qbo_customer_keys())\n",
  "        tied = bool(q)\n"),
 ("a blank qbo_name counts as a tie",
  "        tied = bool(q) or (bool(dk) and dk in self.qbo_customer_keys())\n",
  "        tied = (\"qbo_name\" in c and c.get(\"qbo_name\") is not None) or (bool(dk) and dk in self.qbo_customer_keys())\n"),
 # re-anchored after the review: qbo_name is compared as QuickBooks compares names
 ("the display name is compared raw, not normalised",
  "            if (q and _name_key(name) == _name_key(q)) or (dk and _name_key(name) == dk):\n",
  "            if (q and _name_key(name) == _name_key(q)) or (dk and name == c.get(\"display_name\")):\n"),
 ("qbo_name is compared exactly, so case or punctuation is a mismatch (review)",
  "            if (q and _name_key(name) == _name_key(q)) or (dk and _name_key(name) == dk):\n",
  "            if (q and name.strip() == q) or (dk and _name_key(name) == dk):\n"),
 ("the CFO report drops a mismatched invoice from its job (review)",
  "              \"qbo_match_shared\", \"partial_qbo_match\", \"qbo_customer_mismatch\")\n",
  "              \"qbo_match_shared\", \"partial_qbo_match\")\n"),
 ("drift counts a mismatched invoice as carrying the QuickBooks row (review)",
  "                    if self.qbo_match(i)[1] != \"qbo_customer_mismatch\"\n", ""),
 ("the shape does not carry the unverified count (review)",
  "        if unverified:                      # a count the screen shows beside the figure\n",
  "        if False:\n"),
 ("a row that names nobody is a mismatch",
  "            if not isinstance(name, str) or not name.strip():\n                verdict = \"unverified\"\n                continue\n",
  "            if not isinstance(name, str) or not name.strip():\n                return \"mismatch\", None\n"),
 ("the basis does not count unverified matches",
  "        tail = f\"; customer not verified: {unverified}\" if unverified else \"\"\n", "        tail = \"\"\n"),
 ("the mismatch does not carry both names",
  "            out[\"qbo_customer_mismatch\"] = {\"crm\": c.get(\"display_name\"), \"qbo\": other}\n", ""),
]
VIEW = [
 ("the cell does not say which customer QuickBooks lists",
  "  if(sh.value_cents == null && mm){\n", "  if(false){\n"),
]


def main():
    worst = 0
    for title, test, target, mutants in (
            ("SERVER -- mcp/server.py", "./tests/regression/test_qbo_customer.py", "mcp/server.py", SERVER),
            ("VIEW -- view/build_view.py", "./tests/regression/test_receivables_tile_view.js", "view/build_view.py", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

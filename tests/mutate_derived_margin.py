#!/usr/bin/env python3
"""Mutation-test "profit and margin follow revenue and cost" (0.1.44 H4).

SERVER mutants in mcp/server.py are graded by tests/regression/test_derived_margin.py;
VIEW mutants in view/build_view.py by tests/regression/test_derived_margin_view.js
(the drawer, on a live server).

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("an edit does not recompute profit and margin",
  "            _derive_profit(fields, target[0])\n", ""),
 ("a create does not derive them",
  "            _derive_profit(fields, None)\n            record.update(fields)\n",
  "            record.update(fields)\n"),
 ("a disagreeing value is accepted",
  "        if (got is None) != (want is None) or (got is not None and abs(got - want) > tol):\n",
  "        if False:\n"),
 ("no tolerance: a value within a cent is refused",
  "        if (got is None) != (want is None) or (got is not None and abs(got - want) > tol):\n",
  "        if (got is None) != (want is None) or (got is not None and abs(got - want) > 0):\n"),
 ("a negative revenue gets a margin",
  "    return gp, (round(gp / rev, 6) if rev > 0 else None)\n",
  "    return gp, (round(gp / rev, 6) if rev else None)\n"),
 ("margin is taken over cost",
  "    return gp, (round(gp / rev, 6) if rev > 0 else None)\n",
  "    return gp, (round(gp / cost, 6) if rev > 0 else None)\n"),
 ("re-sending the same revenue counts as a change",
  "               and (prior is None or _num(fields[k]) != _num(prior.get(k))\n",
  "               and (True\n"),
 ("the derived pair is not saved with the edit",
  "    fields[\"gross_profit\"], fields[\"margin\"] = gp, margin\n", ""),
 ("the refusal does not name the derived value",
  "                f\"give {key} {shown(want) if want is not None else 'null'} -- leave \"\n",
  "                f\"give another {key} -- leave \"\n"),
 ("the check lists archived projects",
  "        if not isinstance(p, dict) or p.get(\"archived\"):\n", "        if not isinstance(p, dict):\n"),
 ("the check ignores a stale margin",
  "        off_m = (sm is None) != (margin is None) or (sm is not None and abs(sm - margin) > MARGIN_TOL)\n",
  "        off_m = False\n"),
 ("no zero-revenue rule: a margin of 0 on zero or negative revenue is flagged (H4b)",
  "        if margin is None and sm == 0:\n            off_m = False", "        if False:\n            off_m = False"),
 ("the check counts projects it could not check",
  "        checked += 1\n", ""),
 # re-anchored in H4b: the gate reads `carried`, not `changed`
 ("a profit or margin sent without a revenue or cost change is not judged (review)",
  "    if not carried and not sent:\n", "    if not carried:\n"),
 ("the changed-only gate is back: a resend does not correct a stale project (H4b)",
  "    if not carried and not sent:\n", "    if not changed and not sent:\n"),
 ("no both-inputs guard: a resend with cost missing wipes a hand-entered profit (H4b)",
  "    if gp is None and not changed and not sent:\n        return", "    if False:\n        return"),
 # RETIRED (review round 2): "with nothing to judge by, a sent profit is
 # refused" targeted the "taken as given" branch, which is gone -- the rule is
 # now one for create and update, below.
 ("with nothing to work it out from, a sent profit is taken as given (round 2)",
  "    gp, margin = _derived_profit(merged)\n",
  "    gp, margin = _derived_profit(merged)\n"
  "    if not changed and (_num(merged.get(\"revenue\")) is None or _num(merged.get(\"total_cost\")) is None):\n"
  "        return\n"),
 ("the check's list is unbounded (review)",
  "    return {\"checked\": checked, \"count\": len(out), \"projects\": out[:50],\n",
  "    return {\"checked\": checked, \"count\": len(out), \"projects\": out,\n"),
 ("crm_info does not run the check",
  "        out[\"derived_mismatch\"] = _derived_mismatch(STORE.load(\"projects\"))\n",
  "        out[\"derived_mismatch\"] = {}\n"),
]
VIEW = [
 ("the drawer sends the stale profit beside a revenue change",
  "    total_cost: numOrNull('f_cost'),\n    // gross_profit and margin are not sent",
  "    total_cost: numOrNull('f_cost'),\n    gross_profit: numOrNull('f_gp'),\n    // gross_profit and margin are not sent"),
 ("profit is editable in the drawer",
  "<input id=\"f_gp\" type=\"number\" readonly title=", "<input id=\"f_gp\" type=\"number\" title="),
 ("the drawer keeps showing the profit it opened with",
  "    if(gpEl) gpEl.value = sp.gross_profit == null ? '' : sp.gross_profit;\n", ""),
]


def main():
    worst = 0
    for title, test, target, mutants in (
            ("SERVER -- mcp/server.py", "./tests/regression/test_derived_margin.py", "mcp/server.py", SERVER),
            ("VIEW -- view/build_view.py", "./tests/regression/test_derived_margin_view.js", "view/build_view.py", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

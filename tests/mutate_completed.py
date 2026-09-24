#!/usr/bin/env python3
"""Mutation-test completed_on (0.1.43 G1) in mcp/server.py, graded by
tests/regression/test_completed.py: a dated, operator-owned project field,
refused when unreadable or in the future (through the frozen clock), warned
about before the deal date, touching neither the bucket nor the collection
status. Its carry-over on a re-import is graded with the rest of
OPERATOR_ONLY by tests/mutate_operator_only.py.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
T_COMPLETED = "./tests/regression/test_completed.py"

_GATE = ("        readable = isinstance(v, str) and bool(_NEXT_ACTION_DATE_RE.fullmatch(v.strip()))\n"
         "        if not (readable and _parse_date_loose(v)):\n")

SERVER = [
 ("completed_on stops being a project field",
  '    "completed_on",\n}', '}'),
 ("null is refused, so nothing can be reopened",
  '    if "completed_on" in fields and fields["completed_on"] is not None:\n'
  '        v = fields["completed_on"]\n',
  '    if "completed_on" in fields:\n'
  '        v = fields["completed_on"]\n'),
 ("an unreadable date is stored",
  _GATE, _GATE.replace("readable and _parse_date_loose(v)", "readable")),
 ("the date gate accepts whatever strptime accepts",
  _GATE, _GATE.replace("readable and _parse_date_loose(v)",
                       "isinstance(v, str) and _parse_date_loose(v)")),
 ("the refusal does not name the value",
  '                             f"or null, not {v!r}")', '                             f"or null")'),
 ("a future completion is saved",
  "    if done > _today():\n", "    if False:\n"),
 ("today is refused (>= for >)",
  "    if done > _today():\n", "    if done >= _today():\n"),
 ("the future test reads the wall clock instead of the hook",
  "    if done > _today():\n", "    if done > datetime.now().date():\n"),
 ("the future refusal does not name today",
  '        raise StoreError(f"completed_on {v} is after today ({_today().isoformat()}) "',
  '        raise StoreError(f"completed_on {v} is after today "'),
 ("no warning before the deal date",
  "    if deal and done < deal.date():\n", "    if False:\n"),
 ("a completion before the deal date is refused instead of warned",
  "    if deal and done < deal.date():\n",
  "    if deal and done < deal.date():\n"
  "        raise StoreError(f\"completed_on {v} is before the deal date {record.get('date')}\")\n"),
 ("the warning does not name the deal date",
  "                f\"{record.get('date')} -- saved as given; check both dates\"]",
  "                f\"-- saved as given; check both dates\"]"),
 ("an unrelated edit repeats the warning",
  '    v = fields.get("completed_on")\n    if v is None:\n        return []\n',
  '    v = record.get("completed_on")\n    if v is None:\n        return []\n'),
 ("update_project skips the completion checks",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = []\n"),
 ("create_project skips the completion checks",
  "            warnings = _check_completed(record, fields)\n",
  "            warnings = []\n"),
 ("update_project drops the warnings from its response",
  '            if warnings:\n                out["warnings"] = warnings\n            if new_cid != old_cid:',
  '            if new_cid != old_cid:'),
 ("marking complete clears the Live Tracker bucket",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n"
  "            if fields.get(\"completed_on\"):\n"
  "                fields[\"tracker_status\"] = None\n"),
 ("marking complete marks it paid",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n"
  "            if fields.get(\"completed_on\"):\n"
  "                fields[\"collection_status\"] = \"paid\"\n"),
]

def main():
    worst = 0
    for title, test, target, mutants in (
            ("SERVER -- mcp/server.py", T_COMPLETED, "mcp/server.py", SERVER),):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

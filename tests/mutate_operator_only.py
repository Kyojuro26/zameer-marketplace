#!/usr/bin/env python3
"""Mutation-test the operator-only carry-over (pipeline/merge.py) and its
read-only audit (pipeline/audit_operator_fields.py), both graded by
tests/regression/test_operator_only.py.

MERGE: every field the importer never produces is carried from the store when
the workbook does not supply it, changelog or not. One mutant per field drops
it from OPERATOR_ONLY, so no member of the set is along for the ride.

AUDIT: one mutant per rule the audit states -- last value wins, renames are
followed, creates count, a project is scoped by its customer, a recorded null
is a value, a different value is a finding as well as a missing one, and a key
more than one record answers to is ambiguous rather than guessed.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_operator_only.py"

# The set exactly as merge.py writes it; each per-field mutant removes one
# member. If the source drifts, every one of these reads ANCHOR-MISSING.
_OO = [("projects.json", ["next_action", "next_action_on", "quote_requested_on",
                          "quote_sent_on", "quote_revisions", "completed_on",
                          "tracker_key"]),
       ("shipments.json", ["eta"]),
       ("invoices.json", ["due_on", "source"]),
       ("companies.json", ["notes", "linked_vendor_id", "qbo_name"]),
       ("vendors.json", ["notes", "qbo_name"])]
_PROJECTS_AS_WRITTEN = ('{"next_action", "next_action_on", "quote_requested_on",\n'
                        '                      "quote_sent_on", "quote_revisions", "completed_on",\n'
                        '                      "tracker_key"}')


def _block(drop=None):
    lines = ["OPERATOR_ONLY = {\n"]
    for fname, fields in _OO:
        keep = [f for f in fields if (fname, f) != drop]
        if fname == "projects.json" and not (drop and drop[0] == fname):
            body = _PROJECTS_AS_WRITTEN
        else:
            body = "{" + ", ".join(f'"{f}"' for f in keep) + "}" if keep else "set()"
        lines.append(f'    "{fname}": {body},\n')
    lines.append("}\n")
    return "".join(lines)


MERGE = [
 ("the carry-over is dropped (the pre-0.1.43 behaviour)",
  "            for field in OPERATOR_ONLY.get(fname, ()):\n"
  "                if merged_rec.get(field) is None and field in prior:\n"
  "                    merged_rec[field] = prior[field]\n", ""),
 ("a workbook null clears an operator field",
  "                if merged_rec.get(field) is None and field in prior:\n",
  "                if field not in merged_rec and field in prior:\n"),
 ("the stored value overrides one the workbook supplies",
  "                if merged_rec.get(field) is None and field in prior:\n",
  "                if field in prior:\n"),
] + [(f"{f} ({fn}) is dropped from OPERATOR_ONLY", _block(), _block((fn, f)))
     for fn, fs in _OO for f in fs]

AUDIT = [
 # rewritten review round 1: the replay is per record, renames are scoped,
 # unreadable lines are counted, a missing changelog is not clean, and --out is
 # checked by file identity
 ("the first entry wins instead of the last (a customer's entries)",
  "                for i in mine:\n                    last[i] = (cid, value, ts)\n",
  "                for i in mine:\n                    last.setdefault(i, (cid, value, ts))\n"),
 ("the first entry wins instead of the last (entries without a customer)",
  "                last[0] = (cid, value, ts)\n", "                last.setdefault(0, (cid, value, ts))\n"),
 ("renames are not followed",
  "                if new and new != key:\n", "                if False:\n"),
 # re-anchored review round 2: an unscoped entry on a shared number is ambiguous, not moved
 ("a rename carries every customer's entries",
  "                            if cid is None or ev[0] == cid:\n", "                            if True:\n"),
 ("an unscoped entry on a shared number is pinned to the renamer (round 2)",
  "                            elif ev[0] is None and shared:\n", "                            elif False:\n"),
 ("an ambiguous entry is ignored at replay (round 2)",
  "            if cid == AMBIGUOUS:\n                for i in range(len(hits)):\n                    last[i] = None\n                continue\n",
  "            if cid == AMBIGUOUS:\n                continue\n"),
 ("an unmatched line does not name its customer (round 2)",
  "            who = f[\"key\"] + (f\" ({f['company_id']})\" if f.get(\"company_id\") else \"\")\n",
  "            who = f[\"key\"]\n"),
 ("the report does not say to check unmatched entries by hand (round 2)",
  "    if res[\"unmatched\"]:\n        L.append(", "    if False:\n        L.append("),
 ("--out as a directory ends in a traceback (round 2)",
  "        if os.path.isdir(out):\n", "        if False:\n"),
 ("--out with a missing folder ends in a traceback (round 2)",
  "        if not os.path.isdir(os.path.dirname(out)):\n", "        if False:\n"),
 ("a create is not read",
  '            if op not in ("update", "create"):\n', '            if op != "update":\n'),
 ("a project is not scoped by its customer",
  '            scope = cid if ent == "project" else None\n', "            scope = None\n"),
 ("a recorded null is not a value",
  "            stored = rec.get(field, MISSING)\n",
  "            if value is None:\n                continue\n            stored = rec.get(field, MISSING)\n"),
 ("only a missing field is a finding, not a different one",
  "            if (stored is MISSING and value is not None) or (stored is not MISSING and stored != value):\n",
  "            if stored is MISSING and value is not None:\n"),
 ("a missing store field against a recorded null is a finding",
  "            if (stored is MISSING and value is not None) or (stored is not MISSING and stored != value):\n",
  "            if stored is MISSING or stored != value:\n"),
 ("an entry without a customer on a shared number takes every record",
  "                    last[i] = None            # which record it meant cannot be told\n",
  "                    last[i] = (cid, value, ts)\n"),
 ("vendors are not audited",
  '           "vendor": "vendors.json"}\n', "           }\n"),
 ("an entity of the wrong type crashes the audit",
  '            if not isinstance(e, dict) or not isinstance(e.get("entity"), str):\n',
  "            if not isinstance(e, dict):\n"),
 ("an unreadable line is not counted",
  "                skipped += 1                  # a torn line: counted, not fatal\n",
  "                pass\n"),
 ("no changelog reads as present, and so as clean",
  "        return events, 0, False\n", "        return events, 0, True\n"),
 ("no changelog exits 0",
  '    if res.get("changelog") == "missing":\n        sys.exit(2)', "    pass"),
 ("--out is never checked against the store",
  "    st_store = os.stat(store)\n", "    return False\n"),
 ("--out is not checked for a hard link to a store file",
  "    if os.path.exists(out):\n        so = os.stat(out)\n", "    if False:\n        so = os.stat(out)\n"),
]


def main():
    worst = 0
    for title, target, mutants in (("MERGE -- pipeline/merge.py", "pipeline/merge.py", MERGE),
                                   ("AUDIT -- pipeline/audit_operator_fields.py",
                                    "pipeline/audit_operator_fields.py", AUDIT)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, TEST, target, mutants))
    return worst


sys.exit(main())

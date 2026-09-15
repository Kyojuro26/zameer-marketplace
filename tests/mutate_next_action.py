#!/usr/bin/env python3
"""Mutation-test tests/regression/test_next_action.py against mcp/server.py and
pipeline/merge.py -- two passes, one per file.

The subject is the operator's "by when": two fields stored as given, refused
when they are not what they claim to be, a due filter that means today or
earlier and never a lost or archived project, and a re-import that leaves
them alone. Every mutant is the obvious wrong version of one of those.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_next_action.py"

SERVER = [
 ("today is no longer due (< for <=)",
  "            return bool(d) and d.date() <= today \\\n",
  "            return bool(d) and d.date() < today \\\n"),
 ("a lost project's next action is due",
  '                and p.get("status") != "lost" and not p.get("archived")',
  '                and not p.get("archived")'),
 ("an archived project's next action is due when archived ones are asked for",
  '                and p.get("status") != "lost" and not p.get("archived")',
  '                and p.get("status") != "lost"'),
 ("the flag is ignored, so every project is due",
  "    if next_action_due:\n", "    if False:\n"),
 ("next_action stops being a project field",
  '    "next_action", "next_action_on",\n}\nSHIPMENT_FIELDS = {',
  '}\nSHIPMENT_FIELDS = {'),
 ("a number is stored as a next action",
  '    if "next_action" in fields and fields["next_action"] is not None \\\n'
  '            and not isinstance(fields["next_action"], str):\n'
  '        raise StoreError("next_action must be text or null")\n', ""),
 ("an unreadable date is stored, and never comes due",
  '        if not isinstance(v, str) or not _parse_date_loose(v):',
  '        if not isinstance(v, str):'),
 ("the due test reads the wall clock instead of the hook",
  "        today = _today()\n        def _due(p):",
  "        today = datetime.now().date()\n        def _due(p):"),
]

MERGE = [
 ("a re-import drops the operator's next action",
  "            for field in touched:\n"
  "                if field in prior:\n"
  "                    merged_rec[field] = prior[field]",
  "            for field in touched - {\"next_action\", \"next_action_on\"}:\n"
  "                if field in prior:\n"
  "                    merged_rec[field] = prior[field]"),
 ("add-only mode drops fields the workbook does not carry",
  "                kept = dict(prior)\n",
  "                kept = {k: v for k, v in prior.items() if k in rec or k in IMPORTER_OWNED}\n"),
]


def main():
    worst = 0
    for title, target, mutants in (("SERVER -- mcp/server.py", "mcp/server.py", SERVER),
                                   ("MERGE -- pipeline/merge.py", "pipeline/merge.py", MERGE)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, TEST, target, mutants))
    return worst


sys.exit(main())

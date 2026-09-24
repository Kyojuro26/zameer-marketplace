#!/usr/bin/env python3
"""Mutation-test the 0.1.43 G4 chat flows in SKILL.md, graded by
tests/regression/test_completed_chat.py. Each mutant is the obvious wrong
version of one instruction Claude acts on: skipping the lookup, not asking
which customer, reopening with an empty string, answering the month's list
with a metric or a total, and forgetting that a vendor or a used number is
refused.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_completed_chat.py"

SKILL = [
 ("the number is not looked up first",
  '  - "Mark 4521 complete": `lookup_number(n="4521")` first. If more than one\n',
  '  - "Mark 4521 complete": If more than one\n'),
 ("a shared number is not asked about",
  "    customer holds the number, ask which customer before changing anything.\n",
  "    customer holds the number, pick the first.\n"),
 ("complete is described as paid",
  "  installed. It is not the same as paid: leave the collection status alone and\n",
  "  installed, and paid: set the collection status as well and\n"),
 ("reopen sends an empty string",
  '    {"completed_on": null})`. The job goes back to its Live bucket.\n',
  '    {"completed_on": ""})`. The job goes back to its Live bucket.\n'),
 ("the month's list comes from a metric",
  '  - "What did we complete this month": `list_projects()` and keep the rows whose\n',
  '  - "What did we complete this month": `crm_metrics(report="rankings")` and keep the rows whose\n'),
 ("the month's list is totalled",
  "    complete). Give a list -- customer, number, description, date -- and do not\n"
  "    total it: this is not a metric.\n",
  "    complete). Give a list -- customer, number, description, date -- with its\n"
  "    revenue total.\n"),
 ("a vendor is not mentioned as refused",
  "  (`list_companies`). A project belongs to a customer or a lead; a vendor is\n  refused.",
  "  (`list_companies`). A project belongs to any company."),
 ("the number is not said to be unique",
  "  refused. Ask for the project number -- the QuickBooks estimate number, unique\n"
  "  across the business, so an existing number is refused -- then\n",
  "  refused. Ask for the project number, then\n"),
]


def main():
    print(f"\n=== SKILL -- SKILL.md  ({len(SKILL)} mutants) ===")
    return mutate(SRC, TEST, "SKILL.md", SKILL)


sys.exit(main())

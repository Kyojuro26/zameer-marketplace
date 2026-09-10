#!/usr/bin/env python3
"""Mutation-test tests/regression/test_project_identity.py against mcp/server.py.

The subject is one decision: an optional company_id narrows a project number
to one customer's record BEFORE the ambiguity test, and only narrows. Every
mutant below is the obvious wrong version of that decision rather than an
injected typo -- the filter dropped, the filter applied after the refusal, an
empty filter falling back to the number-only match, the rename cascade
ignoring the customer, a tool not threading the argument at all.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_project_identity.py"
F = "mcp/server.py"

M = [
 # ---- _one_project: the filter, and where it sits -------------------------
 ("the company filter is dropped, so company_id changes nothing",
  '    if company_id is not None:\n'
  '        cid = _key(company_id)\n'
  '        matches = [p for p in matches if _key(p.get("company_id")) == cid]\n', ""),
 ("the company filter runs only after the ambiguity test has passed",
  '    if company_id is not None:\n'
  '        cid = _key(company_id)\n',
  '    if company_id is not None and len(matches) <= 1:\n'
  '        cid = _key(company_id)\n'),
 ("an empty filter falls back to the number-only match -- the other customer's record",
  '        matches = [p for p in matches if _key(p.get("company_id")) == cid]\n',
  '        matches = [p for p in matches if _key(p.get("company_id")) == cid] or matches\n'),
 ("company_id is compared raw rather than through _key",
  '        cid = _key(company_id)\n'
  '        matches = [p for p in matches if _key(p.get("company_id")) == cid]\n',
  '        cid = company_id\n'
  '        matches = [p for p in matches if p.get("company_id") == cid]\n'),
 # ---- the tools thread it, or do not --------------------------------------
 ("get_project ignores company_id",
  '    _hit = _one_project(projects, want, "Opening it", company_id) if want else None',
  '    _hit = _one_project(projects, want, "Opening it") if want else None'),
 ("get_project lists every leg carrying the number, whichever customer's",
  '    shipments = [s for s in STORE.load("shipments")\n'
  '                 if want in _shipment_project_nos(s)\n'
  '                 and (company_id is None or _key(s.get("company_id")) == cid)]',
  '    shipments = [s for s in STORE.load("shipments")\n'
  '                 if want in _shipment_project_nos(s)]'),
 ("update_project ignores company_id",
  '            hit = _one_project(projects, want, "Editing it", company_id) if want else None',
  '            hit = _one_project(projects, want, "Editing it") if want else None'),
 ("rename_project ignores company_id",
  '            hit = _one_project(projects, old_pn, "Renaming it", company_id)',
  '            hit = _one_project(projects, old_pn, "Renaming it")'),
 ("archive and restore ignore company_id",
  '            hit = (_one_project(projects, want, "Archiving or restoring it", company_id)\n',
  '            hit = (_one_project(projects, want, "Archiving or restoring it")\n'),
 ("create_shipment ignores company_id",
  '            pr = _live_project(project_no, company_id)',
  '            pr = _live_project(project_no)'),
 # ---- the rename cascade is scoped, or is not ------------------------------
 ("the rename cascade carries the OTHER customer's legs too",
  '                if scope is not None and _key(s.get("company_id")) != scope:\n'
  '                    continue\n', ""),
 ("the rename cascade carries the OTHER customer's invoices too",
  '                if scope is not None and _key(i.get("company_id")) != scope:\n'
  '                    continue\n', ""),
 # RETIRED, deliberately: "the cascade scope is taken from the argument, not
 # the record it found" -- _key(company_id) vs _key(target[0]["company_id"]).
 # The filter in _one_project only returns a record whose key EQUALS the
 # argument's key, so the two expressions are the same value by construction
 # and the mutant has no reachable effect. A mutant with no reachable effect
 # is not evidence of anything; it survived, and that is the information.
]

sys.exit(mutate(SRC, TEST, F, M))

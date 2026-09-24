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
  '                 and _key(s.get("company_id")) not in others]',
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
  '                if _key(s.get("company_id")) in others:\n'
  '                    continue\n', ""),
 ("the rename cascade carries the OTHER customer's invoices too",
  '                if _key(i.get("company_id")) in others:\n'
  '                    continue\n', ""),
 # ---- review round 1: three classes ---------------------------------------
 ("an archived twin hides the live twin's records again -- by the number alone",
  '        if pno_key not in self.live:\n'
  '            return True\n'
  '        return (pno_key, cid_key) in self.pairs',
  '        return True'),
 ("an archived number hides only records filed under its own customer, so an unshared project's company-less legs stay",
  '        if pno_key not in self.live:\n'
  '            return True\n', ""),
 ("a move onto a customer already holding the number goes through",
  '            if new_cid != old_cid and any(\n'
  '                    p is not target[0] and _key(p.get("project_no")) == want\n'
  '                    and _key(p.get("company_id")) == new_cid for p in projects):\n',
  '            if False:\n'),
 ("every other company is another holder, so a scoped call on an unshared number strands company-less records",
  '    return {_key(p.get("company_id")) for p in projects\n'
  '            if _key(p.get("project_no")) == key} - {_key(company_id)}',
  '    return {_key(p.get("company_id")) for p in projects} - {_key(company_id)}'),
 # ---- review round 2: the other holders, live or archived ------------------
 ("an archived twin is not another holder, so its own records follow the live twin's rename",
  '    return {_key(p.get("company_id")) for p in projects\n'
  '            if _key(p.get("project_no")) == key} - {_key(company_id)}',
  '    return {_key(p.get("company_id")) for p in projects\n'
  '            if _key(p.get("project_no")) == key and not p.get("archived")} - {_key(company_id)}'),
 ("the cascade is confined to the named customer's own records when a twin exists",
  '                if _key(s.get("company_id")) in others:\n',
  '                if others and _key(s.get("company_id")) != _key(company_id):\n'),
 # RETIRED, deliberately: "the cascade scope is taken from the argument, not
 # the record it found" -- _key(company_id) vs _key(target[0]["company_id"]).
 # The filter in _one_project only returns a record whose key EQUALS the
 # argument's key, so the two expressions are the same value by construction
 # and the mutant has no reachable effect. A mutant with no reachable effect
 # is not evidence of anything; it survived, and that is the information.
 # ---- the refusal names the holders (0.1.43) ------------------------------
 ("the refusal no longer names the holders",
  "                f\"{len(matches)} projects share the number '{key}': \"\n"
  "                f\"{'; '.join(holders)}. {what} needs to know which -- pass \"\n",
  "                f\"{len(matches)} projects share the number '{key}'. \"\n"
  "                f\"{what} needs to know which -- pass \"\n"),
 ("an archived holder is not marked",
  "            return f\"{name} ({cid}{', archived' if m.get('archived') else ''})\"\n",
  "            return f\"{name} ({cid})\"\n"),
 ("two customers get the old store-directly message",
  "        if len(set(cids)) == len(cids):\n", "        if False:\n"),
 ("one customer holding it twice is told to pass company_id",
  "        if len(set(cids)) == len(cids):\n", "        if True:\n"),
 ("the holder is named by id alone",
  "            name = names.get(cid) or m.get(\"company_name\") or \"no name\"\n",
  "            name = cid\n"),
]

sys.exit(mutate(SRC, TEST, F, M))

#!/usr/bin/env python3
"""Mutation-test the FAILURE-SIGNALLING checks.

The subject is one class, not one file: what the app does when a call to the
server does not come back. Three modules assert it, so this script runs three
passes -- a single pass would leave whichever module it did not name resting on
its author's confidence.

Why this class earned its own script: of the ten sites that awaited CRM.call,
four caught a rejection and six did not -- and catching was UNCORRELATED with
being tested. Three of the four (fetchEnrichment, draft, replyToThread) had no
test at all. What tests predicted was not whether a catch existed but whether
it told the truth: doSave caught and reported, fetchEnrichment caught and then
asserted a falsehood about the data. So no mutant here asserts that a catch is
present -- each reintroduces a site as it stood and is killed only by a check
on what the OPERATOR SEES.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "view/build_view.py"
SERVER_F = "mcp/server.py"

REFRESH_TEST = "./tests/regression/test_refresh.js"
VIEW_TEST = "./tests/regression/test_view.js"
TRACKER_TEST = "./tests/regression/test_livetracker.js"
INTEGRITY_TEST = "./tests/regression/test_integrity.py"

# ---- refreshData: three states, not two ----------------------------------
REFRESH = [
 ("one dead call discards the five good answers again (pre-facb583)",
  "    const settled = await Promise.allSettled(WANT.map(t => CRM.call(t, {})));",
  "    const settled = (await Promise.all(WANT.map(t => CRM.call(t, {}))))\n"
  "      .map(v => ({status: 'fulfilled', value: v}));"),
 ("the pill stops naming WHICH sections are stale",
  "    } else if (el && failed.length){\n"
  "      el.textContent = 'Live · could not refresh ' + failed.join(', ')\n"
  "                     + ' — those sections show last built data';\n"
  "    }",
  "    }"),
 ("a partial failure says nothing at all (the 8ec5cac behaviour)",
  "    const el = document.getElementById('modePill');\n"
  "    if (el && failed.length === WANT.length){\n"
  "      el.textContent = 'Live · refresh failed — showing last built data';\n"
  "    } else if (el && failed.length){",
  "    const el = document.getElementById('modePill');\n"
  "    if (false){\n"
  "      el.textContent = '';\n"
  "    } else if (false){"),
 ("a CLEAN refresh also warns, so the warning stops meaning anything",
  "    if (el && failed.length === WANT.length){",
  "    if (el && failed.length >= 0){"),
 ("a clean refresh warns too, with the other two states left correct",
  "    } else if (el && failed.length){",
  "    } else if (el && !failed.length){\n"
  "      el.textContent = 'Live · could not refresh — showing last built data';\n"
  "    } else if (el && failed.length){"),
 ("a failed call is applied as though it had succeeded",
  "      if (v && v.ok) got[WANT[i]] = v; else failed.push(WANT[i]);",
  "      got[WANT[i]] = v || {ok: true, companies: [], contacts: [], projects: [],\n"
  "        shipments: [], invoices: []};\n"
  "      if (!(v && v.ok)) failed.push(WANT[i]);"),
]

# ---- every write that can be refused, and the one read --------------------
# Each mutant is the site exactly as it stood before this commit.
SITES = [
 ("rename_project unwrapped",
  "    let rr;\n"
  "    try{ rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno, company_id: cid}); }\n"
  "    catch(e){ rr = {ok:false, error:(e && e.message) || String(e)}; }",
  "    const rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno, company_id: cid});"),
 ("archive_project unwrapped",
  "  let r;\n"
  "  try{ r = await CRM.call('archive_project', {project_no:pno, company_id:cid}); }\n"
  "  catch(e){ r = {ok:false, error:(e && e.message) || String(e)}; }",
  "  const r=await CRM.call('archive_project', {project_no:pno, company_id:cid});"),
 ("convert_lead unwrapped",
  "  let r;\n"
  "  try{ r = await CRM.call('convert_lead', {company_id:cid}); }\n"
  "  catch(e){ r = {ok:false, error:(e && e.message) || String(e)}; }",
  "  const r=await CRM.call('convert_lead', {company_id:cid});"),
 ("rename_invoice unwrapped",
  "    let rr;\n"
  "    try{ rr = await CRM.call('rename_invoice', {company_id:cid, old_invoice_no:storedNo, new_invoice_no:newNo}); }\n"
  "    catch(e){ rr = {ok:false, error:(e && e.message) || String(e)}; }",
  "    const rr = await CRM.call('rename_invoice', {company_id:cid, old_invoice_no:storedNo, new_invoice_no:newNo});"),
 ("archive_company unwrapped",
  "  let r;\n"
  "  try{ r = await CRM.call('archive_company', {company_id:cid}); }\n"
  "  catch(e){ r = {ok:false, error:(e && e.message) || String(e)}; }",
  "  const r=await CRM.call('archive_company', {company_id:cid});"),
 ("reassign_shipment unwrapped",
  "    let rr;\n"
  "    try{ rr = await CRM.call('reassign_shipment', {shipment_id: sid, new_project_no: newPno || null}); }\n"
  "    catch(e){ rr = {ok:false, error:(e && e.message) || String(e)}; }",
  "    const rr = await CRM.call('reassign_shipment', {shipment_id: sid, new_project_no: newPno || null});"),
 ("an unreachable Outlook reported as \"no signal on file\" again",
  "    ENRICH[id] = {__unreachable: (e && e.message) || String(e)};",
  "    ENRICH[id] = null;"),
 # The two sites that already CAUGHT. A structural check passes on these
 # mutants -- the catch is still there, still catching. Only a check that reads
 # the screen and fails on the string "undefined" kills them.
 ("doSave prints a non-Error rejection as \"undefined\"",
  "    lastSaveError = (e && e.message) || String(e);\n"
  "    msg.textContent='✗ ' + lastSaveError; msg.className='saved show errc';\n"
  "    return false;",
  "    lastSaveError = e.message;\n"
  "    msg.textContent='✗ ' + lastSaveError; msg.className='saved show errc';\n"
  "    return false;"),
 ("replyToThread alerts a non-Error rejection as \"undefined\"",
  "    alert('Could not create reply draft: ' + ((e && e.message) || String(e)));",
  "    alert('Could not create reply draft: ' + e.message);"),
 # A catch that swallows is the shape a structural check would pass: the
 # rejection is handled, nothing escapes, and the operator still learns
 # nothing. If this survives, the checks above are asserting the wrong thing.
 ("archive_project catches the rejection and reports success",
  "  try{ r = await CRM.call('archive_project', {project_no:pno, company_id:cid}); }\n"
  "  catch(e){ r = {ok:false, error:(e && e.message) || String(e)}; }",
  "  try{ r = await CRM.call('archive_project', {project_no:pno, company_id:cid}); }\n"
  "  catch(e){ r = {ok:true}; }"),
]

# ---- the tracker half of the same refresh ---------------------------------
TRACKER = [
 ("the refresh drops list_tracker again",
  "    const WANT = ['list_companies', 'find_contacts', 'list_projects',\n"
  "                  'list_shipments', 'list_invoices', 'list_tracker'];",
  "    const WANT = ['list_companies', 'find_contacts', 'list_projects',\n"
  "                  'list_shipments', 'list_invoices'];"),
 ("a wrong-shaped tracker answer overwrites a good section",
  "      if (Array.isArray(tk.tracker_buckets))  DATA.tracker_buckets  = tk.tracker_buckets;\n"
  "      if (Array.isArray(tk.tracker_unlinked)) DATA.tracker_unlinked = tk.tracker_unlinked;",
  "      DATA.tracker_buckets  = tk.tracker_buckets;\n"
  "      DATA.tracker_unlinked = tk.tracker_unlinked;"),
]


# ---- crm_info: the store's own health check --------------------------------
# Before this commit `grep -rn crm_info tests/mutate_*.py` returned NOTHING --
# the health check the operator relies on had no mutation cover anywhere.
#
# The reason was structural rather than neglect. mutate_lib drives a python
# module as run(None) when its signature takes one parameter, and
# test_integrity.py's did: Store(None) failed before a single mutant could be
# applied, so the baseline never passed and no verdict was reachable. The
# run(server, crm_dir=None) fallback in this commit is what makes any of this
# gradable; the mutant below is the proof that it grades.
#
# Anchored on the WHOLE per-file loop, not the bare except arm: the decision
# being reversed is "one unreadable file is tolerated per entity", and a
# fragment could not say which loop it mutated.
HEALTH = [
 ("crm_info stops tolerating one unreadable file and dies on the whole check",
  "    for e in ENTITY_FILES:\n"
  "        try:\n"
  "            counts[e] = len(STORE.load(e))\n"
  "        except StoreError as ex:\n"
  "            counts[e] = None\n"
  "            problems[e] = str(ex)",
  "    for e in ENTITY_FILES:\n"
  "        counts[e] = len(STORE.load(e))"),
 # ADDED WITH THE FIX IT GRADES, not with the plumbing one commit back.
 # This anchors on the REORDERED tail, which did not exist then -- dropped into
 # that commit it reported ANCHOR-MISSING and proved nothing.
 #
 # The anchor is the whole tail because the defect is an ORDER: `ok` computed at
 # the top of it rather than the bottom, with the two edit points twenty-two
 # lines apart. No shorter anchor can express that, and a fuzzy one could not
 # say which of the two it moved.
 # re-anchored 0.1.44: crm_info gained the derived_mismatch block
 ("crm_info computes ok BEFORE the blocks that can still add problems",
  "    # `ok` is NOT computed here. Two blocks below can still add to `problems`\n"
  "    # -- the enrichment/archive read and the auto_created manifest -- and a\n"
  "    # value snapshotted at this point reported \"ok\": true with those problems\n"
  "    # listed underneath it. A caller branches on `ok` and never reads the list,\n"
  "    # so the one machine-readable field said the store was fine while the\n"
  "    # human-readable one said it was not. Computed once, at the end, from the\n"
  "    # finished dict.\n"
  "    out = {\"interface_version\": VERSION,\n"
  "           \"server_version\": SERVER_VERSION,\n"
  "           \"store\": str(STORE.root), \"counts\": counts}\n"
  "    try:\n"
  "        out[\"archived_companies\"] = len(_archived_ids())\n"
  "        out[\"enriched_companies\"] = len(STORE.load_enrichment())\n"
  "    except StoreError as ex:\n"
  "        problems[\"enrichment/archive\"] = str(ex)\n"
  "    # Data quality, not a store fault: listed, never counted against `ok`.\n"
  "    try:\n"
  "        out[\"derived_mismatch\"] = _derived_mismatch(STORE.load(\"projects\"))\n"
  "    except StoreError as ex:\n"
  "        problems[\"derived_mismatch\"] = str(ex)\n"
  "    # A store file this build had to create at first boot is surfaced here,\n"
  "    # not buried in a temp-dir launch log. If it was missing because OneDrive\n"
  "    # had not synced it down, this is the operator's only signal.\n"
  "    try:\n"
  "        created = (STORE._manifest_read_raw() or {}).get(\"auto_created\") or []\n"
  "        if created:\n"
  "            out[\"auto_created_store_files\"] = created\n"
  "            problems[\"auto_created\"] = (\n"
  "                f\"{created} did not exist when the CRM first started and were \"\n"
  "                f\"created empty. If they should have held records, restore them \"\n"
  "                f\"from your backup before making further edits.\")\n"
  "    except Exception:                                 # noqa: BLE001\n"
  "        pass\n"
  "    if problems:\n"
  "        out[\"problems\"] = problems\n"
  "    out[\"ok\"] = not problems\n"
  "    return out",
  "    # `ok` is NOT computed here. Two blocks below can still add to `problems`\n"
  "    # -- the enrichment/archive read and the auto_created manifest -- and a\n"
  "    # value snapshotted at this point reported \"ok\": true with those problems\n"
  "    # listed underneath it. A caller branches on `ok` and never reads the list,\n"
  "    # so the one machine-readable field said the store was fine while the\n"
  "    # human-readable one said it was not. Computed once, at the end, from the\n"
  "    # finished dict.\n"
  "    out = {\"ok\": not problems, \"interface_version\": VERSION,\n"
  "           \"server_version\": SERVER_VERSION,\n"
  "           \"store\": str(STORE.root), \"counts\": counts}\n"
  "    try:\n"
  "        out[\"archived_companies\"] = len(_archived_ids())\n"
  "        out[\"enriched_companies\"] = len(STORE.load_enrichment())\n"
  "    except StoreError as ex:\n"
  "        problems[\"enrichment/archive\"] = str(ex)\n"
  "    # Data quality, not a store fault: listed, never counted against `ok`.\n"
  "    try:\n"
  "        out[\"derived_mismatch\"] = _derived_mismatch(STORE.load(\"projects\"))\n"
  "    except StoreError as ex:\n"
  "        problems[\"derived_mismatch\"] = str(ex)\n"
  "    # A store file this build had to create at first boot is surfaced here,\n"
  "    # not buried in a temp-dir launch log. If it was missing because OneDrive\n"
  "    # had not synced it down, this is the operator's only signal.\n"
  "    try:\n"
  "        created = (STORE._manifest_read_raw() or {}).get(\"auto_created\") or []\n"
  "        if created:\n"
  "            out[\"auto_created_store_files\"] = created\n"
  "            problems[\"auto_created\"] = (\n"
  "                f\"{created} did not exist when the CRM first started and were \"\n"
  "                f\"created empty. If they should have held records, restore them \"\n"
  "                f\"from your backup before making further edits.\")\n"
  "    except Exception:                                 # noqa: BLE001\n"
  "        pass\n"
  "    if problems:\n"
  "        out[\"problems\"] = problems\n"
  "    return out"),
]


def main():
    worst = 0
    # Per-section TARGET file. Every section used to mutate view/build_view.py,
    # which silently limited this script to the screen -- the server side of the
    # same class could not be graded here at all.
    for title, test_rel, target, mutants in (
            ("REFRESH -- test_refresh.js", REFRESH_TEST, F, REFRESH),
            ("SITES -- test_view.js", VIEW_TEST, F, SITES),
            ("TRACKER -- test_livetracker.js", TRACKER_TEST, F, TRACKER),
            ("HEALTH -- test_integrity.py", INTEGRITY_TEST, SERVER_F, HEALTH)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test_rel, target, mutants))
    return worst


sys.exit(main())

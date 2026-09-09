#!/usr/bin/env python3
"""Mutation-test the Live Tracker suite.

The Live Tracker spans three files, so this runs three passes -- the importer
against the python module, the screen against the node module, and merge.py
against the python module because that is where the regeneration interlock is
asserted. A single pass would leave whichever file it did not name untested by
anything but its own author's confidence.

The mutants are grouped by the decision each one reverses, and every group has
at least one entry that is the OBVIOUS alternative rather than an injected
typo: the legend anchored on colour instead of on the last keyed row, an
unrecognised fill guessed at instead of left unset, FF00FF00 treated as a
fourth bucket, adoption defaulting the customer instead of refusing. Those are
the versions of this feature a reasonable person would have written, and they
are the ones a test suite has to be able to tell apart.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
PY_TEST = "./tests/regression/test_livetracker.py"
JS_TEST = "./tests/regression/test_livetracker.js"

# --------------------------------------------------------------- importer ---
NORMALIZE = [
 # ---- the legend boundary: the decision, and its two obvious alternatives ---
 ("the legend is scanned by COLOUR instead of below the last keyed row",
  "    for i in range(last_keyed + 1, inv_header_idx):",
  "    for i in range(1, inv_header_idx):"),
 ("the boundary is off by one and eats the last keyed row",
  "    for i in range(last_keyed + 1, inv_header_idx):",
  "    for i in range(last_keyed, inv_header_idx):"),
 # ---- what separates a job from a footer line ------------------------------
 ("the footer skip goes back to position alone, dropping a trailing job",
  "            if _i > last_keyed and not _job_shaped(r):\n"
  "                continue    # skip-ok: a footer line -- no client, no legs, so no job\n",
  ""),
 ("job-shape reverts to 'a key and anything else', so TOTAL moves the boundary",
  "        if has_value(cells[3]):                       # a client name\n"
  "            return True\n"
  "        return sum(1 for j in range(6, 22) if has_value(cells[j])) >= 2",
  "        return any(has_value(c) for c in cells[1:])"),
 ("a single stray footer cell counts as a vendor leg",
  "        return sum(1 for j in range(6, 22) if has_value(cells[j])) >= 2",
  "        return sum(1 for j in range(6, 22) if has_value(cells[j])) >= 1"),
 ("the client column stops making a row a job",
  "        if has_value(cells[3]):                       # a client name\n"
  "            return True\n",
  ""),
 ("the boundary drops the job-shape test entirely",
  "        return bool(row and row[0] is not None and _job_shaped(row))",
  "        return bool(row and row[0] is not None)"),
 ("an unreadable fill on a legend row is reported as a missing legend",
  '                "type": "tracker_legend_unreadable_colour",',
  '                "type": "quietly_ignored_legend",'),
 ("the unlinked row stops carrying the parsed key merge matches on",
  '                "parsed_keys": [p for p in pnos if p],\n', ""),

 # ---- FF00FF00 ---------------------------------------------------------------
 ("FF00FF00 loses its never-a-bucket registration",
  '    "FF00FF00": "section header of the second table",\n', ""),
 ("FF00FF00 is promoted to a fourth bucket",
  '    "FF00FFFF": "awaiting_materials",    # cyan\n}',
  '    "FF00FFFF": "awaiting_materials",    # cyan\n'
  '    "FF00FF00": "section_header",        # green\n}'),

 # ---- an unknown colour is never guessed ------------------------------------
 ("an unrecognised fill is guessed at instead of left unset",
  "        bucket = BUCKET_BY_ARGB.get(argb)",
  '        bucket = BUCKET_BY_ARGB.get(argb) or ("action_admin" if argb else None)'),
 ("the unknown-colour entry stops naming the ARGB",
  '                    (f"the notes cell is filled {argb}, which is not one of "',
  '                    (f"the notes cell is filled with a colour that is not one of "'),
 ("the unknown-colour entry stops naming the row it is on",
  '                ) + " Its status was left unset rather than guessed.",\n'
  '                "sheet": "Project Tracker", "sheet_row": row_no,\n',
  '                ) + " Its status was left unset rather than guessed.",\n'),
 ("an unknown fill is flagged but the row keeps a status anyway",
  "        if argb and not bucket and argb not in NON_BUCKET_ARGB \\\n"
  "                and r and r[0] is not None:",
  "        if argb and not bucket and argb not in NON_BUCKET_ARGB \\\n"
  "                and r and r[0] is not None:\n"
  '            bucket = "action_owner"'),
 ("the unknown-colour flag is re-coupled to the boundary",
  "        if argb and not bucket and argb not in NON_BUCKET_ARGB \\\n"
  "                and r and r[0] is not None:",
  "        if _i <= last_keyed and argb and not bucket \\\n"
  "                and argb not in NON_BUCKET_ARGB and r and r[0] is not None:"),

 # ---- a fill that is present but unreadable ------------------------------
 ("an unreadable fill is dropped from the map again, so nothing is said",
  "            elif pat is not None:\n"
  "                # isinstance() above is the right guard -- a theme or indexed\n"
  "                # colour makes .rgb hand back the descriptor object, and\n"
  "                # .upper() on that would invent a bucket name. But the cell IS\n"
  "                # filled, so record that rather than letting it read as bare.\n"
  "                fills[i] = UNREADABLE_FILL\n",
  ""),
 ("an unreadable fill is decoded anyway, inventing a bucket name",
  '            if pat == "solid" and isinstance(rgb, str):',
  '            if pat == "solid" and rgb is not None:'),
 ("a solid fill with no foreground colour flags on every import",
  '    "00000000": "a solid fill with no foreground colour set",\n', ""),

 # ---- reading the fill at all ------------------------------------------------
 ("the fill is read from the wrong column",
  "                                               min_col=6, max_col=6)):",
  "                                               min_col=1, max_col=1)):"),
 ("the fill read stops before the legend rows",
  "        for i, cells in enumerate(ws.iter_rows(min_row=1, max_row=inv_header_idx + 8,",
  "        for i, cells in enumerate(ws.iter_rows(min_row=1, max_row=inv_header_idx - 6,"),

 # ---- a bucket the legend never names ---------------------------------------
 ("a bucket with no legend row is dropped instead of kept unnamed",
  '            tracker_buckets.append({"key": key, "label": None, "argb": argb,\n'
  '                                    "legend_row": None})',
  "            pass"),
 ("a bucket with no legend row is given an invented name",
  '            tracker_buckets.append({"key": key, "label": None, "argb": argb,\n'
  '                                    "legend_row": None})',
  '            tracker_buckets.append({"key": key,\n'
  '                                    "label": key.replace("_", " ").title(),\n'
  '                                    "argb": argb, "legend_row": None})'),
 ("a missing legend row is not reported at all",
  '                "type": "tracker_legend_missing",', '                "type": "quietly_ignored",'),

 # ---- the note is a property of the row -------------------------------------
 ("the note goes back to the shipment legs only",
  "                if clean(cells[5]):\n"
  '                    projects[pno]["open_orders_notes"] = clean(cells[5])\n', ""),
 ("the vendor loop reverts to stopping at S/T",
  "        for j in range(6, 22, 2):   # G..V as PO/date pairs",
  "        for j in range(6, 20, 2):   # G..T as PO/date pairs"),

 # ---- unlinked rows ----------------------------------------------------------
 ("a keyed row that matches no project is silently dropped again",
  "        if not matched_any:", "        if False:"),
 ("an unlinked row loses the status colour it was found under",
  '                    "location": clean(_c[4]), "open_orders_notes": clean(_c[5]),\n'
  '                    "tracker_status": bucket,',
  '                    "location": clean(_c[4]), "open_orders_notes": clean(_c[5]),\n'
  '                    "tracker_status": None,'),
 ("an unlinked row loses the key the sheet actually carried",
  '                "raw_key": str(raw_key),', '                "raw_key": None,'),
 ("the unlinked rows are no longer written out",
  "        \"tracker_unlinked.json\": stamp_fingerprints(unlinked_rows),",
  "        \"tracker_unlinked.json\": [],"),
 # NEW: the fingerprint is the handle a dismissal is scoped to. A row that
 # reaches the store without one can never be dismissed.
 ("the rows are written without their fingerprint",
  "        \"tracker_unlinked.json\": stamp_fingerprints(unlinked_rows),",
  "        \"tracker_unlinked.json\": unlinked_rows,"),
 # The exclusion of sheet_row is the whole reason a reordering does not
 # resurrect every dismissal.
 # The ordinal is what stops ONE dismissal retiring TWO rows whose every
 # visible field is identical -- one of them live work, hidden, with its note
 # and legs rendered nowhere.
 # Identical rows are ONE decision -- the operator cannot tell them apart
 # either -- so they share a handle and one click clears both. The card has to
 # SAY that; a click that clears two cards silently reads as a bug.
 ("a shared fingerprint stops being counted, so the card cannot say so",
  "        if counts[base] > 1:\n"
  "            row[\"shares_fingerprint\"] = counts[base]\n", ""),
 ("the fingerprint starts moving with the row",
  '        "client": _t(u.get("client")),',
  '        "sheet_row": _t(u.get("sheet_row")),\n'
  '        "client": _t(u.get("client")),'),
 ("the fingerprint stops covering the note, so a retitle stays hidden",
  '        "notes": _t(u.get("open_orders_notes")),\n', ''),

 # ---- provenance of a row --------------------------------------------------
 ("the recorded tracker row is off by one",
  "        row_no = _i + 1", "        row_no = _i"),
 ("the project stops recording which row it came from",
  '                projects[pno]["tracker_row"] = row_no',
  '                projects[pno]["tracker_row"] = None'),
]

# ------------------------------------------------------------------ merge ---
MERGE = [
 ("add-only mode removes the status when the workbook is silent about it",
  "                kept = dict(prior)\n"
  "                for field in IMPORTER_OWNED:\n"
  "                    if field in rec:\n"
  "                        kept[field] = rec[field]",
  "                kept = dict(prior)\n"
  "                for field in IMPORTER_OWNED:\n"
  "                    if field in rec:\n"
  "                        kept[field] = rec[field]\n"
  "                    else:\n"
  "                        kept.pop(field, None)"),
 # RETIRED, deliberately, rather than deleted -- seven mutants that graded
 # key-matching. Every one of them asserted that merge decides which rows leave
 # the "Not in the CRM yet" list, and merge no longer decides that at all:
 #
 #   "an adopted row is offered for adoption again on the next import"
 #   "the adopted match uses the display string instead of the parsed key"
 #   "the adopted match goes back to matching on the sheet row"
 #   "a phrase-keyed row he adopted comes back forever"
 #   "the sheet-key handle matches any project, adopted or not"
 #   "the report stops naming the rows it dropped"
 #   "the report stops printing what it took off the screen"
 #
 # by_sheet_key accumulated a key from every adoption ever made and nothing
 # expired it, so it was compared against a sheet that turns over completely --
 # and a free-text key collides across weeks, which retires a row NOBODY
 # adopted. by_key went with it: it reads a real identifier, but it accumulates
 # the same way. There is nothing left for these to grade, and a mutant with no
 # reachable target is not evidence.
 #
 # What replaced them is below: the operator's own decision, scoped to the row
 # as it stands in the sheet, swept when that row is gone.
 # by_key is what makes the migration burn down: adopt a row and it retires
 # itself next import. Its ARCHIVED exclusion is what stops a deleted project
 # suppressing a row forever, leaving the job on neither list.
 ("an adopted row is offered for adoption again on the next import",
  "            keys = [k for k in (_idkey(x) for x in (u.get(\"parsed_keys\") or []))\n"
  "                    if k]\n"
  "            if keys and all(k in by_key for k in keys):\n"
  "                adopted.extend(keys)\n"
  "                continue    # skip-ok: it IS a project now; named in the report",
  "            keys = []\n"
  "            if False:\n"
  "                pass"),
 ("an ARCHIVED project keeps suppressing its row",
  "        projs = [p for p in (merged.get(\"projects.json\") or [])\n"
  "                 if isinstance(p, dict) and not p.get(\"archived\")\n"
  "                 and p.get(\"company_id\") not in _arch_co]\n"
  "        by_key = {_idkey(p.get(\"project_no\")) for p in projs\n"
  "                  if _idkey(p.get(\"project_no\"))}",
  "        projs = [p for p in (merged.get(\"projects.json\") or [])\n"
  "                 if isinstance(p, dict)]\n"
  "        by_key = {_idkey(p.get(\"project_no\")) for p in projs\n"
  "                  if _idkey(p.get(\"project_no\"))}"),
 ("the report stops naming the rows it retired",
  '            report["adopted"] = adopted', "            pass"),
 ("the sweep is removed, so dismissals accumulate forever",
  "        kept, seen_fp, swept = [], set(), 0\n"
  "        for d in dismissals:\n"
  "            fp = _s(d.get(\"fingerprint\"))\n"
  "            if fp and fp in live:\n"
  "                if fp not in seen_fp:\n"
  "                    seen_fp.add(fp)\n"
  "                    kept.append(d)\n"
  "            else:\n"
  "                swept += 1",
  "        kept, seen_fp, swept = list(dismissals), set(), 0"),
 ("a dismissed row is DELETED rather than flagged, so no count can show",
  "            if fp and fp in reason_by_fp:\n"
  "                u = dict(u, dismissed=True, reason_dismissed=reason_by_fp[fp])\n"
  "                n_dismissed_rows += 1\n"
  "            else:\n"
  "                u = {k: v for k, v in u.items()\n"
  "                     if k not in (\"dismissed\", \"reason_dismissed\")}\n"
  "            out_rows.append(u)",
  "            if fp not in reason_by_fp:\n"
  "                out_rows.append(u)"),
 ("a stale dismissed flag on the row outvotes the swept table",
  "            if fp and fp in reason_by_fp:\n"
  "                u = dict(u, dismissed=True, reason_dismissed=reason_by_fp[fp])\n"
  "                n_dismissed_rows += 1\n"
  "            else:\n"
  "                u = {k: v for k, v in u.items()\n"
  "                     if k not in (\"dismissed\", \"reason_dismissed\")}\n"
  "            out_rows.append(u)",
  "            if fp and fp in reason_by_fp:\n"
  "                u = dict(u, dismissed=True, reason_dismissed=reason_by_fp[fp])\n"
  "                n_dismissed_rows += 1\n"
  "            out_rows.append(u)"),
 ("an unreadable dismissal file reads as 'nothing dismissed', silently",
  "            unreadable = (f\"tracker_dismissed.json could not be read ({e}); \"\n"
  "                          f\"every row is being shown, and the file has been \"\n"
  "                          f\"left exactly as it is\")",
  "            unreadable = None"),
 ("the sweep stops de-duplicating, so the count stops meaning anything",
  "        kept, seen_fp, swept = [], set(), 0\n"
  "        for d in dismissals:\n"
  "            fp = _s(d.get(\"fingerprint\"))\n"
  "            if fp and fp in live:\n"
  "                if fp not in seen_fp:\n"
  "                    seen_fp.add(fp)\n"
  "                    kept.append(d)\n"
  "            else:\n"
  "                swept += 1",
  "        kept, seen_fp, swept = [], set(), 0\n"
  "        for d in dismissals:\n"
  "            fp = _s(d.get(\"fingerprint\"))\n"
  "            if fp and fp in live:\n"
  "                kept.append(d)\n"
  "            else:\n"
  "                swept += 1"),
 # RETIRED before it ever counted. I wrote this to grade the `fp and` guard in
 # the kept loop, and it SURVIVED -- because `live` is itself built excluding
 # empty fingerprints, so "" can never be in it and the guard cannot change an
 # outcome. It is belt-and-braces, not a decision. A mutant with no reachable
 # effect is not evidence, and leaving it green would have claimed cover the
 # suite does not have.
 ("the report stops saying what it swept",
  '        if swept:\n            report["dismissals_swept"] = swept\n', ""),
 ("the report stops saying how many rows are held dismissed",
  "        if n_dismissed_rows:\n"
  "            # ROWS, not records. One dismissal flags every row sharing its\n"
  "            # fingerprint -- by design, since the operator cannot tell those\n"
  "            # rows apart -- so counting records printed \"HOLDING 1\" over three\n"
  "            # cards. A count he cannot reconcile with the screen is worse than\n"
  "            # none, which is the rule the dedupe above states.\n"
  "            report[\"dismissed\"] = n_dismissed_rows",
  "        if False:\n"
  "            report[\"dismissed\"] = n_dismissed_rows"),
]

# -------------------------------------------------------------------- view ---
VIEW = [
 # RETIRED with the behaviour they graded:
 #
 #   "adoption gets its own private write path" -- now INVERTED. Adoption MUST
 #     have its own path: adopt_tracker_row writes the project and the
 #     dismissal that retires its row under one lock. Split across two calls, a
 #     crash between them leaves a project whose row is still offered and
 #     undismissable, which is 0.1.32's defect.
 #   "an archived customer's unlinked row is shown again"
 #   "the archived-name match is taken after the companies are filtered out"
 #     -- both graded the squashed display-name filter, deleted here. It
 #     justified itself as "only ever HIDES a card, so a near-miss costs a
 #     visible row, never a wrong record", which inverts this repo's rule that
 #     a hidden job is worse than a duplicate card. On a store with duplicate
 #     records for one customer -- the likeliest reason to archive anything --
 #     it hid the SURVIVOR's live jobs too.
 ("cards are numbered off the filtered list again, so the indices shift",
  "  const _unlAll = arr(DATA.tracker_unlinked)\n"
  "    .map((u, i)=>({u, i}))\n"
  "    .filter(x=>x.u && typeof x.u === 'object' && unlinkedMatches(x.u, q));",
  "  const _unlAll = arr(DATA.tracker_unlinked)\n"
  "    .filter(u=>u && typeof u === 'object' && unlinkedMatches(u, q))\n"
  "    .map((u, i)=>({u, i}));"),
 # ---- the three buttons, and the section that must never be invisible ------
 ("the dismiss buttons are dropped, so a row can only be adopted or left",
  "        ${fp ? `<button class=\"pill-btn\" onclick=\"dismissRow('${jesc(fp)}','already_adopted')\">Already in the CRM</button>\n"
  "        <button class=\"pill-btn\" onclick=\"dismissRow('${jesc(fp)}','not_a_job')\">Not a job</button>`\n"
  "        : `<span class=\"muted nw\">re-import the workbook to dismiss this row</span>`}",
  "        "),
 ("the burndown count goes back to a bare number",
  "      <span class=\"muted\">${leftToClear} row${leftToClear===1?'':'s'} left to clear${\n"
  "        unlinked.length===leftToClear?'':` \\u00b7 ${unlinked.length} shown`}</span></div>",
  "      <span class=\"muted\">${unlinked.length}</span></div>"),
 ("the card stops saying a click clears two identical rows",
  "        ${fp && u.shares_fingerprint > 1\n"
  "          ? `<span class=\"muted nw\">${esc(st(u.shares_fingerprint))} identical rows on the sheet \u2014 this clears both</span>`\n"
  "          : ''}\n", ""),
 ("the two dismiss reasons collapse into one soft label",
  ">Already in the CRM</button>", ">Hide</button>"),
 ("the Dismissed section is not rendered at all",
  "  if(dismissed.length){", "  if(false){"),
 ("a dismissal cannot be undone",
  "<button class=\"pill-btn\" onclick=\"restoreRow('${jesc(st(u.fingerprint))}')\">Put it back</button>", ""),
 # A dismissal that LANDED, reported as one that did not: the drawer left
 # open over a red mark, with the button still up inviting a second press.
 ("linking it leaves every surface saying the write failed",
  "  const _d = document.getElementById('drawer');\n"
  "  if(_d && _d.classList && _d.classList.contains('open') && _wasOpen === _openSeq){",
  "  const _d = null;\n"
  "  if(false){"),
 ("the restore button loses the guard its sibling has",
  "<span style=\"margin-left:auto\">${st(u.fingerprint)\n"
  "        ? `<button class=\"pill-btn\" onclick=\"restoreRow('${jesc(st(u.fingerprint))}')\">Put it back</button>`\n"
  "        : `<span class=\"muted nw\">re-import to restore</span>`}</span>",
  "<span style=\"margin-left:auto\"><button class=\"pill-btn\" onclick=\"restoreRow('${jesc(st(u.fingerprint))}')\">Put it back</button></span>"),
 ("the built page stops honouring dismissals made through the tools",
  "        for d in (_raw if isinstance(_raw, list) else []):",
  "        for d in []:"),
 ("Add to CRM dead-ends again on a number already in use",
  "    const said = st(lastSaveError);\n"
  "    const fp = st(u.fingerprint);\n"
  "    if(fp && /^project .* already exists$/i.test(said.trim())){",
  "    const said = st(lastSaveError);\n"
  "    const fp = st(u.fingerprint);\n"
  "    if(false){"),
 # Anchored with the two lines above it, because `const fp = st(u.fingerprint)`
 # occurs in saveAdoptTrackerRow too and a bare one-line anchor is AMBIGUOUS --
 # it could not say which of the two it mutated.
 ("the dismiss button is offered on a row that has no handle for it",
  "  // than no button. The next import stamps them.\n"
  "  const fp = st(u.fingerprint);",
  "  // than no button. The next import stamps them.\n"
  "  const fp = st(u.fingerprint) || 'none';"),

 # ---- the landing screen ----------------------------------------------------
 ("the live view never paints itself on load",
  "if(filter === 'live') renderMain();\n", ""),
 ("the app no longer lands on the tracker",
  "let filter='live', selected=null, query='';",
  "let filter='all', selected=null, query='';"),
 ("the Live tab is present but not the one selected",
  '        <button data-f="live" class="on">Live</button>',
  '        <button data-f="live">Live</button>'),

 # ---- what a ship-date cell means -------------------------------------------
 ("a passed estimate is reported as a passed hard date",
  "  return {kind: late ? (est?'est-passed':'passed') : 'ok', text: fmtDate(iso),",
  "  return {kind: late ? 'passed' : 'ok', text: fmtDate(iso),"),
 ("an unparseable ship date is treated as no date at all",
  "  if(!iso) return {kind:'text', text:t};",
  "  if(!iso) return {kind:'none', text:'no date'};"),
 ("an empty ship date is treated as text rather than missing",
  "  if(!t) return {kind:'none', text:'no date'};",
  "  if(!t) return {kind:'text', text:''};"),
 ("a leg with no date stops being flagged",
  "    else if(d.kind==='none') amber.push('leg with no date');\n", ""),
 ("a TBD start date stops being flagged",
  "  if(/^tbd$/i.test(start)) red.push('start TBD');\n", ""),
 ("the flags are no longer de-duplicated",
  "  return {red: [...new Set(red)], amber: [...new Set(amber)]};", "  return {red, amber};"),
 # ---- two severities ---------------------------------------------------------
 ("a leg with no date is promoted to red",
  "    else if(d.kind==='none') amber.push('leg with no date');",
  "    else if(d.kind==='none') red.push('leg with no date');"),
 ("undated legs count towards \"need a look\"",
  "  const flagged = rows.filter(r=>r.flags.red.length).length;   // red only: late NOW",
  "  const flagged = rows.filter(r=>r.flags.red.length||r.flags.amber.length).length;"),
 ("an amber badge wears red",
  "${r.flags.amber.map(f=>`<span class=\"badge b-pending\">${esc(f)}</span>`).join('')}",
  "${r.flags.amber.map(f=>`<span class=\"badge b-lost\">${esc(f)}</span>`).join('')}"),
 ("an undated leg is bold red on the row again",
  "              : d.kind==='passed' ? 'lt-bad'\n"
  "              : (d.kind==='none'||d.kind==='est-passed') ? 'lt-warn' : 'muted';",
  "              : (d.kind==='passed'||d.kind==='none') ? 'lt-bad'\n"
  "              : (d.kind==='est-passed' ? 'lt-warn' : 'muted');"),
 ("amber-only rows sort among the clean ones",
  "    if(a.flags.amber.length !== b.flags.amber.length) return b.flags.amber.length - a.flags.amber.length;\n", ""),
 ("the sidebar counts amber as flags",
  "  return (nr ? `<span class=\"owed\">${nr} flag${nr>1?'s':''}</span>` : '')\n"
  "       + (na ? `<span>${nr ? '\\u00b7 ' : ''}${na} to check</span>` : '');",
  "  return `<span class=\"owed\">${nr+na} flag${nr+na>1?'s':''}</span>`;"),

 # ---- who is on the screen ---------------------------------------------------
 ("archived projects come back onto the live screen",
  "    .filter(p=>p && !p.archived && st(p.tracker_status) && liveMatches(p, q))",
  "    .filter(p=>p && st(p.tracker_status) && liveMatches(p, q))"),
 ("every project is treated as live work",
  "    .filter(p=>p && !p.archived && st(p.tracker_status) && liveMatches(p, q))",
  "    .filter(p=>p && !p.archived && liveMatches(p, q))"),
 ("legs are matched on the number alone, ignoring the company",
  "      const legs = (DATA.shipments||[]).filter(s=>\n"
  "        st(s.company_id)===st(p.company_id) &&\n"
  "        _shipmentProjectNos(s).has(st(p.project_no)));",
  "      const legs = (DATA.shipments||[]).filter(s=>\n"
  "        _shipmentProjectNos(s).has(st(p.project_no)));"),
 ("the busiest row sorts last instead of first",
  "    if(a.flags.red.length !== b.flags.red.length) return b.flags.red.length - a.flags.red.length;",
  "    if(a.flags.red.length !== b.flags.red.length) return a.flags.red.length - b.flags.red.length;"),

 # ---- the note ---------------------------------------------------------------
 ("the note is truncated to a preview",
  '    <div class="lt-note">${esc(st(p.open_orders_notes)||\'\')||\'<span class="muted">no note</span>\'}</div>',
  '    <div class="lt-note">${esc(st(p.open_orders_notes).slice(0,80))||\'<span class="muted">no note</span>\'}</div>'),
 ("an unlinked row's note is truncated to a preview",
  '    <div class="lt-note">${esc(st(u.open_orders_notes)||\'\')||\'<span class="muted">no note</span>\'}</div>',
  '    <div class="lt-note">${esc(st(u.open_orders_notes).slice(0,80))||\'<span class="muted">no note</span>\'}</div>'),
 ("the note is written into the page unescaped",
  '    <div class="lt-note">${esc(st(p.open_orders_notes)||\'\')||\'<span class="muted">no note</span>\'}</div>',
  '    <div class="lt-note">${st(p.open_orders_notes)||\'<span class="muted">no note</span>\'}</div>'),
 ("the note box stops wrapping",
  "  .lt-note{margin:8px 0 0;font-size:13.5px;line-height:1.5;white-space:pre-wrap}",
  "  .lt-note{margin:8px 0 0;font-size:13.5px;line-height:1.5;white-space:nowrap;overflow:hidden}"),

 # ---- bucket labels -----------------------------------------------------------
 ("a bucket with no label shows nothing instead of its key",
  "  if(b && b.label) return b.label;\n"
  "  return st(key).replace(/_/g,' ').replace(/^\\w/, c=>c.toUpperCase());",
  "  return b ? st(b.label) : '';"),
 ("a store with no bucket file loses the grouping entirely",
  "  if(seen.length) return seen;", "  return seen;"),

 # ---- adoption: the refusals --------------------------------------------------
 ("the empty customer choice is dropped, so the browser picks the first",
  "        cid ? '' : '<option value=\"\">— choose a customer —</option>'}${",
  "        ''}${"),
 ("vendors are offered as the customer for a project",
  "        (DATA.companies||[]).filter(c=>st(c.role)!=='vendor')",
  "        (DATA.companies||[])"),

 # ---- adoption: what gets written ---------------------------------------------
 ("the sheet's own key is written as the CRM project number",
  "    project_no: pno, company_id: cid,",
  "    project_no: (u && u.raw_key) || pno, company_id: cid,"),
 ("the status bucket is dropped on adoption",
  "    tracker_status: u.tracker_status || null,",
  "    tracker_status: null,"),
 ("adoption stops recording which sheet row it came from",
  "    tracker_row: u.sheet_row == null ? null : u.sheet_row,",
  "    tracker_row: null,"),
 ("the unlinked section is hidden altogether",
  "  if(unlinked.length){", "  if(false){"),

 ("adoption accepts a row with no project number",
  "  if(!pno){ msg.textContent='\u2717 project # is required';\n"
  "            msg.className='saved show errc'; return false; }\n", ""),
 ("adoption accepts a row with no customer",
  "  if(!cid){ msg.textContent='\u2717 pick a customer';\n"
  "            msg.className='saved show errc'; return false; }\n", ""),
 ("the sidebar label is escaped before it is shortened",
  "${esc(st(_liveListLabel(r.p.tracker_status)).slice(0,28))}",
  "${esc(_liveListLabel(r.p.tracker_status)).slice(0,28)}"),
 ("the sidebar dresses an unrecognised status as a real bucket",
  "  return known.has(st(key)) ? bucketLabel(key) : 'status not recognised';",
  "  return bucketLabel(key);"),
 ("a settled leg is rendered red even though its badge is gone",
  "    const cls = legSettled(l) ? 'muted'\n"
  "              : d.kind==='passed' ? 'lt-bad'",
  "    const cls = d.kind==='passed' ? 'lt-bad'"),
 ("the drawer tells him a numberless row's legs are already in the CRM",
  "      arr(u.legs).length === 0 ? 'No vendor legs on this row.'\n"
  "      : st(u.raw_key)",
  "      arr(u.legs).length === 0 ? 'No vendor legs on this row.'\n"
  "      : true"),
 ("the drawer tells him a keyed row's legs were never imported",
  "      arr(u.legs).length === 0 ? 'No vendor legs on this row.'\n"
  "      : st(u.raw_key)",
  "      arr(u.legs).length === 0 ? 'No vendor legs on this row.'\n"
  "      : false"),
 # ---- the review pass ---------------------------------------------------------
 ("the customer guess matches vendors again, defeating the no-default rule",
  "  const hit = (DATA.companies||[]).find(c=>\n"
  "    st(c.role)!=='vendor' &&\n"
  "    sv(c.display_name).replace(/[^a-z0-9]+/g, '') === n);",
  "  const hit = (DATA.companies||[]).find(c=>\n"
  "    sv(c.display_name).replace(/[^a-z0-9]+/g, '') === n);"),
 ("saving loses its missing-row guard",
  "  if(!u || typeof u !== 'object'){\n"
  "    msg.textContent='\u2717 that tracker row is no longer on the list \u2014 reload';\n"
  "    msg.className='saved show errc'; return false;\n"
  "  }\n",
  ""),
 ("a status no bucket knows about is counted but drawn nowhere",
  "  if(orphans.length){", "  if(false){"),
 ("the orphan section is filled from the wrong list",
  "  const orphans = rows.filter(r=>!known.has(st(r.p.tracker_status)));",
  "  const orphans = [];"),
 ("a delivered leg is late again, and pins the row to the top forever",
  "    if(legSettled(l)) return;\n", ""),
 ("only delivered counts as settled, not installed or cancelled",
  "const LEG_DONE = new Set(['delivered', 'installed', 'cancelled']);",
  "const LEG_DONE = new Set(['delivered']);"),
 ("an unlinked row's legs skip arr() again",
  "  const legs = arr(u.legs).filter(l=>l && typeof l === 'object').map(l=>{\n"
  "    const d = legDate(l.ship_date), paid = legPaid(l.vendor_po_raw);",
  "  const legs = (u.legs||[]).map(l=>{\n"
  "    const d = legDate(l.ship_date), paid = legPaid(l.vendor_po_raw);"),
 ("the card reads only p.date, disagreeing with its own TBD flag",
  "${esc(fmtDate(p.date||p.start_date)||st(p.date||p.start_date)||'no start date')}",
  "${esc(fmtDate(p.date)||st(p.date)||'no start date')}"),
 ("a live refresh stops repainting the cards on the landing screen",
  "    else if (filter === 'live') renderMain();\n", ""),
 ("a tracker file of the wrong shape kills the app at load again",
  "        if not isinstance(data.get(name), list):\n"
  "            data[name] = []\n"
  '            problems.append(f"{name}.json is not a list -- built with 0 {name}")\n',
  ""),
 # ---- the round-two review fixes ---------------------------------------------
 ("the job-level note loses its editor again",
  """    <div class="field"><label>Open orders note <span class="muted"
      style="text-transform:none;font-weight:400">(the note shown on the Live
      screen)</span></label>
      <textarea id="f_oon" style="min-height:88px">${esc(p.open_orders_notes||\'\')}</textarea>""",
  """    <div class="field" style="display:none"><label>Open orders note</label>
      <textarea id="f_oon_disabled"></textarea>"""),
 ("the project save stops sending the job-level note",
  "    open_orders_notes: document.getElementById('f_oon').value,\n", ""),
 ("clearing the note sends null, which reads as 'never set'",
  "    open_orders_notes: document.getElementById('f_oon').value,",
  "    open_orders_notes: document.getElementById('f_oon').value || null,"),
 ("search stops narrowing the live cards",
  "    .filter(p=>p && !p.archived && st(p.tracker_status) && liveMatches(p, q))",
  "    .filter(p=>p && !p.archived && st(p.tracker_status))"),
 ("search stops narrowing the unlinked rows",
  "    .filter(x=>x.u && typeof x.u === 'object' && unlinkedMatches(x.u, q));",
  "    .filter(x=>x.u && typeof x.u === 'object');"),
 ("search matches the number but not the note",
  "      || sv(p.open_orders_notes).includes(q);", "      ;"),
 ("typing repaints the sidebar but not the cards",
  "  if(filter === 'project' || filter === 'live') renderMain();",
  "  if(filter === 'project') renderMain();"),
 ("the main pane goes back to rendering every row",
  "    h += mine.slice(0, LIVE_CAP).map(r=>liveCard(r)).join('');",
  "    h += mine.map(r=>liveCard(r)).join('');"),
 ("the cap is applied silently, with nothing said",
  """      h += `<div class="muted" style="font-size:12px;padding:4px 2px">Showing
        the first ${LIVE_CAP} of ${mine.length} — search to narrow this
        down.</div>`;""", "      ;"),
 ("adoption goes back to assuming the deal is won",
  "    status: document.getElementById('a_status').value || null,",
  "    status: 'won',"),
 ("adoption goes back to stamping the year it was adopted in",
  "    year: numOrNull('a_year'),", "    year: new Date().getFullYear(),"),
 ("the adopted year is read from the clock rather than the start date",
  "  const iso = isoDate(st(u && u.start_date));\n"
  "  return iso ? Number(iso.slice(0, 4)) : new Date().getFullYear();",
  "  return new Date().getFullYear();"),

 ("adoption stops recording the key the sheet carries",
  "    tracker_key: st(u.raw_key) || null,\n", ""),
 ("a live refresh stops pulling the tracker files",
  "                  'list_shipments', 'list_invoices', 'list_tracker'];",
  "                  'list_shipments', 'list_invoices'];"),
 ("a refresh blanks the tracker sections when the server cannot answer",
  "      if (Array.isArray(tk.tracker_buckets))  DATA.tracker_buckets  = tk.tracker_buckets;\n"
  "      if (Array.isArray(tk.tracker_unlinked)) DATA.tracker_unlinked = tk.tracker_unlinked;",
  "      DATA.tracker_buckets  = tk.tracker_buckets;\n"
  "      DATA.tracker_unlinked = tk.tracker_unlinked;"),
 ("the bucket selector is dropped from the project drawer",
  '    <div class="field"><label>Live Tracker bucket</label>\n'
  '      <select id="f_tracker" data-orig="${esc(st(p.tracker_status))}">\n'
  "        ${trackerOpts(p.tracker_status)}</select>",
  '    <div class="field" style="display:none"><label>bucket</label>\n'
  '      <select id="f_tracker_gone">'),
 ("the bucket selector offers a value the server would refuse",
  "  trackerBuckets().forEach(b=>{\n"
  "    h += `<option value=\"${esc(b.key)}\"${b.key===cur ? ' selected' : ''}>`\n"
  "       + `${esc(bucketLabel(b.key))}</option>`;\n"
  "  });",
  "  trackerBuckets().forEach(b=>{\n"
  "    h += `<option value=\"${esc(b.key)}\"${b.key===cur ? ' selected' : ''}>`\n"
  "       + `${esc(bucketLabel(b.key))}</option>`;\n"
  "  });\n"
  "  if(cur && !trackerBuckets().some(b=>b.key===cur))\n"
  "    h += `<option value=\"${esc(cur)}\" selected>${esc(cur)}</option>`;"),
 ("the bucket is sent on every save, clearing it on an unrelated edit",
  "  if(trk && (trk.value || '') !== (trk.getAttribute('data-orig') || '')){\n"
  "    fields.tracker_status = trk.value || null;\n"
  "  }",
  "  if(trk){ fields.tracker_status = trk.value || null; }"),
 # RETIRED, deliberately, rather than left to read SURVIVED forever:
 #   ("the changed-check trips on empty-versus-absent again",
 #    "(trk.value || '') !== (trk.getAttribute('data-orig') || '')"
 #     -> "trk.value !== trk.getAttribute('data-orig')")
 # data-orig used to be absent until something wrote it, so getAttribute
 # returned null and the `|| ''` was the whole guard. openProject now
 # snapshots the baseline FROM THE CONTROL on every open, so the attribute is
 # always a string and the mutation has no reachable effect. A mutant with no
 # reachable effect is not evidence of anything; the two mutants below are the
 # ones that now carry this behaviour.
 ("openProject no longer snapshots the bucket baseline from the control",
  "  const _trk = document.getElementById('f_tracker');\n"
  "  if(_trk) _trk.setAttribute('data-orig', _trk.value);\n", ""),
 ("a saved bucket is not re-baselined, so changing it back sends nothing",
  "    if(trk) trk.setAttribute('data-orig', trk.value);\n", ""),
 ("an unrecognised bucket is no longer explained in the form",
  "      ${knownBucket(p.tracker_status) ? '' : (st(p.tracker_status)",
  "      ${true ? '' : (st(p.tracker_status)"),
 # ---- the card's invoice: who owes me, not only whose court -----------------
 ("the invoice is looked up by number alone, so another customer's can answer",
  "  const v = (invoicesByCo[p.company_id]||[]).find(x => st(x.invoice_no).trim() === no);",
  "  const v = (DATA.invoices||[]).find(x => st(x.invoice_no).trim() === no);"),
 ("the invoice number is compared untrimmed",
  ".find(x => st(x.invoice_no).trim() === no);",
  ".find(x => st(x.invoice_no) === no);"),
 ("a number with no record behind it vanishes from the card",
  "  if(!v) return `<span class=\"muted nw\">inv ${esc(no)} \\u00b7 no invoice record</span>`;",
  "  if(!v) return '';"),
 ("a paid invoice with an old due date is shown as late",
  "  const late = invoiceBucket(v) === 'Overdue' ? daysLate(v) : 0;",
  "  const late = daysLate(v);"),
 ("the number goes back to inert text",
  "  return `<button class=\"pill-btn\" onclick=\"openEditInvoice('${jesc(st(p.company_id))}','${jesc(st(v.invoice_no))}')\">inv ${esc(no)}</button>`",
  "  return `<span class=\"muted nw\">inv ${esc(no)}</span>`"),
 ("the link carries the trimmed number, which the drawer cannot find",
  "'${jesc(st(v.invoice_no))}')\">inv ${esc(no)}</button>`",
  "'${jesc(no)}')\">inv ${esc(no)}</button>`"),
 # ---- the sidebar in the main pane's order --------------------------------
 ("the sidebar goes back to one flat flag-sorted list",
  "  const groups = trackerBuckets().map(b=>({label: bucketLabel(b.key),\n"
  "    rows: rows.filter(r=>st(r.p.tracker_status)===b.key)}));\n"
  "  groups.push({label: 'Status not recognised', rows: rows.filter(r=>!known.has(st(r.p.tracker_status)))});",
  "  const groups = [{label: '', rows: rows}];"),
 ("the unrecognised statuses fall out of the sidebar",
  "  groups.push({label: 'Status not recognised', rows: rows.filter(r=>!known.has(st(r.p.tracker_status)))});\n", ""),
 ("the bucket headings are dropped",
  "    h += `<div class=\"due-group\" style=\"padding:8px 12px 2px\">${esc(g.label)}</div>`;\n", ""),
 ("a sidebar click opens the edit drawer again",
  "      h += `<div class=\"citem\" ${hasProjectNo(r.p)?`onclick=\"liveJump('${jesc(st(r.p.project_no))}')\"`:''}>",
  "      h += `<div class=\"citem\" ${hasProjectNo(r.p)?`onclick=\"openProject('${jesc(st(r.p.project_no))}')\"`:''}>"),
 ("the jump no longer marks the card it reached",
  "  el.classList.add('lt-hit');\n", ""),
 ("cards lose their ids, so the jump has nothing to reach",
  "  return `<div class=\"lt-card\"${hasProjectNo(p) ? ` id=\"lt-${esc(st(p.project_no))}\"` : ''}>",
  "  return `<div class=\"lt-card\">"),
]


# ------------------------------------------------------------------ server ---
SERVER = [
 ("tracker_status loses its enum check, so a live job leaves the board",
  '    if "tracker_status" in fields and fields["tracker_status"] is not None \\\n'
  '            and fields["tracker_status"] not in TRACKER_STATUSES:\n'
  '        raise StoreError(\n'
  '            f"tracker_status must be one of {sorted(TRACKER_STATUSES)} or null")\n',
  ""),
 ("the check rejects null too, so a retired row can never be cleared",
  '    if "tracker_status" in fields and fields["tracker_status"] is not None \\\n'
  '            and fields["tracker_status"] not in TRACKER_STATUSES:',
  '    if "tracker_status" in fields \\\n'
  '            and fields["tracker_status"] not in TRACKER_STATUSES:'),
 ("the server's bucket keys drift from the importer's",
  'TRACKER_STATUSES = {"action_admin", "action_owner", "awaiting_materials"}',
  'TRACKER_STATUSES = {"action_admin", "action_owner", "awaiting_material"}'),
 ("tracker_status stops being a writable project field",
  '    "tracker_status", "open_orders_notes", "tracker_row",\n', ""),
 ("moving a project leaves its legs filed under the old company",
  "            if new_cid != old_cid:\n"
  "                shipments = STORE.load(\"shipments\")",
  "            if False:\n"
  "                shipments = STORE.load(\"shipments\")"),
 ("the cascade drags another company's leg on the same number along",
  "                    if _key(s.get(\"company_id\")) == old_cid and \\\n"
  "                            want in {_key(n) for n in\n"
  "                                     _as_list(s.get(\"all_project_nos\"))\n"
  "                                     or [s.get(\"project_no\")]}:",
  "                    if want in {_key(n) for n in\n"
  "                                _as_list(s.get(\"all_project_nos\"))\n"
  "                                or [s.get(\"project_no\")]}:"),
 ("the project's invoices stay behind when it moves",
  "                    if _key(i.get(\"company_id\")) == old_cid and \\\n"
  "                            _key(i.get(\"project_no\")) == want:\n"
  "                        i[\"company_id\"] = fields[\"company_id\"]\n"
  "                        moved_inv += 1\n",
  ""),
 ("the move is made but never reported",
  "                out[\"shipments_moved\"] = moved_ship\n", ""),

 # ---- the finishing pass ------------------------------------------------------
 ("tracker_key stops being a writable project field",
  '    "tracker_key",\n}', "}"),
 ("tracker_key is left as free text, so a numeric sheet key never matches",
  "    # coerced to text like every other identifier: the sheet's key cell can be\n"
  "    # a number, and a float 1419.0 stored here would never match the \"1419.0\"\n"
  "    # string the importer writes into the unlinked row\n"
  '    "tracker_key",\n', ""),
 ("list_tracker reports a missing tracker file as an error",
  '        v = self._read_json(self.root / filename, [])\n'
  "        return v if isinstance(v, list) else []",
  "        with open(self.root / filename, encoding=\"utf-8-sig\") as f:\n"
  "            return json.load(f)"),
 ("list_tracker passes a wrong-shaped file straight through",
  "        return v if isinstance(v, list) else []", "        return v"),
 # Both mutants below anchor on list_tracker's WHOLE per-file body.
 # The anchor this replaced was shortened to the bare `except` arm when the
 # body changed, and a fragment cannot say WHICH line it mutated -- it is
 # also one rename away from colliding with crm_info's near-identical arm.
 ("list_tracker swallows a corrupt file as empty",
  "    out, problems = {}, {}\n"
  "    for key, fname in ((\"tracker_buckets\", \"tracker_buckets.json\"),\n"
  "                       (\"tracker_unlinked\", \"tracker_unlinked.json\")):\n"
  "        try:\n"
  "            out[key] = STORE.load_side(fname)\n"
  "        except StoreError as ex:\n"
  "            out[key] = []\n"
  "            problems[key] = str(ex)\n",
  "    out, problems = {}, {}\n"
  "    for key, fname in ((\"tracker_buckets\", \"tracker_buckets.json\"),\n"
  "                       (\"tracker_unlinked\", \"tracker_unlinked.json\")):\n"
  "        try:\n"
  "            out[key] = STORE.load_side(fname)\n"
  "        except StoreError as ex:\n"
  "            out[key] = []\n"),
 # The per-file split is the point: one bad file must not take the other's
 # rows with it. This mutant restores the single shared try.
 ("list_tracker goes back to ONE try around both loads",
  "    out, problems = {}, {}\n"
  "    for key, fname in ((\"tracker_buckets\", \"tracker_buckets.json\"),\n"
  "                       (\"tracker_unlinked\", \"tracker_unlinked.json\")):\n"
  "        try:\n"
  "            out[key] = STORE.load_side(fname)\n"
  "        except StoreError as ex:\n"
  "            out[key] = []\n"
  "            problems[key] = str(ex)\n",
  "    out, problems = {}, {}\n"
  "    try:\n"
  "        for key, fname in ((\"tracker_buckets\", \"tracker_buckets.json\"),\n"
  "                           (\"tracker_unlinked\", \"tracker_unlinked.json\")):\n"
  "            out[key] = STORE.load_side(fname)\n"
  "    except StoreError as ex:\n"
  "        out[\"tracker_buckets\"] = []\n"
  "        out[\"tracker_unlinked\"] = []\n"
  "        problems[\"tracker\"] = str(ex)\n"),
]


def main():
    worst = 0
    for title, test_rel, target, mutants in (
            ("IMPORTER -- pipeline/normalize.py", PY_TEST,
             "pipeline/normalize.py", NORMALIZE),
            ("MERGE -- pipeline/merge.py", PY_TEST, "pipeline/merge.py", MERGE),
            ("SERVER -- mcp/server.py", PY_TEST, "mcp/server.py", SERVER),
            ("SCREEN -- view/build_view.py", JS_TEST,
             "view/build_view.py", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test_rel, target, mutants))
    return worst


sys.exit(main())

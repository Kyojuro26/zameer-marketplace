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
  '        "tracker_unlinked.json": unlinked_rows,', '        "tracker_unlinked.json": [],'),

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
 ("an adopted row is offered for adoption again on the next import",
  "            hit = next((k for k in keys if k and k in by_key), None)",
  "            hit = None"),
 ("the adopted match uses the display string instead of the parsed key",
  '            keys = [_idkey(k) for k in (u.get("parsed_keys") or [])]\n'
  "            if not keys:\n"
  '                keys = [_idkey(u.get("raw_key"))]',
  '            keys = [_idkey(u.get("raw_key"))]'),
 ("the adopted match goes back to matching on the sheet row",
  "            hit = next((k for k in keys if k and k in by_key), None)",
  "            hit = next((k for k in keys if k and k in by_key), None) \\\n"
  '                  or (u.get("sheet_row") and "row")'),
 ("the report stops printing what it took off the screen",
  '    if report.get("adopted"):\n'
  '        # A row dropped from the Live Tracker with nothing said is the same\n'
  "        # silence this module exists to end -- and the two `# skip-ok:` markers\n"
  "        # at the drop site claim it is reported here, which has to be true.\n",
  "    if False:\n"),
 ("the tracker files are merged by key instead of regenerated",
  'REGENERATED = {"needs_review.json", "tracker_buckets.json",\n'
  '               "tracker_unlinked.json"}',
  'REGENERATED = {"needs_review.json"}'),
 ("only the buckets are regenerated, not the unlinked rows",
  'REGENERATED = {"needs_review.json", "tracker_buckets.json",\n'
  '               "tracker_unlinked.json"}',
  'REGENERATED = {"needs_review.json", "tracker_buckets.json"}'),
 ("add-only mode withholds the status colour again (empty tracker on upgrade)",
  'IMPORTER_OWNED = {"tracker_status", "tracker_row"}',
  'IMPORTER_OWNED = set()'),
 ("add-only mode force-refreshes the NOTE too, over an operator edit",
  'IMPORTER_OWNED = {"tracker_status", "tracker_row"}',
  'IMPORTER_OWNED = {"tracker_status", "tracker_row", "open_orders_notes"}'),
 ("the report stops naming the rows it dropped",
  '            report["adopted"] = adopted', "            pass"),
]

# -------------------------------------------------------------------- view ---
VIEW = [
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
  "    else if(d.kind==='none') out.push('leg with no date');\n", ""),
 ("a TBD start date stops being flagged",
  "  if(/^tbd$/i.test(start)) out.push('start TBD');\n", ""),
 ("the flags are no longer de-duplicated",
  "  return [...new Set(out)];", "  return out;"),

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
  "    if(a.flags.length !== b.flags.length) return b.flags.length - a.flags.length;",
  "    if(a.flags.length !== b.flags.length) return a.flags.length - b.flags.length;"),

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
 ("adoption gets its own private write path",
  "  const ok = await doSave('create_project', {fields}, (r)=>{",
  "  const ok = await doSave('adopt_tracker_row', {fields}, (r)=>{"),
 ("the adopted row stays on the list, inviting a duplicate project",
  "    DATA.tracker_unlinked = (DATA.tracker_unlinked||[])\n"
  "      .filter(x=>x !== u);\n", ""),
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
  "              : (d.kind==='passed'||d.kind==='none') ? 'lt-bad'",
  "    const cls = (d.kind==='passed'||d.kind==='none') ? 'lt-bad'"),
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
 ("cards are numbered off the filtered list again, so the indices shift",
  "  const unlinked = arr(DATA.tracker_unlinked)\n"
  "    .map((u, i)=>({u, i}))\n"
  "    .filter(x=>x.u && typeof x.u === 'object' && unlinkedMatches(x.u, q));",
  "  const unlinked = arr(DATA.tracker_unlinked)\n"
  "    .filter(u=>u && typeof u === 'object' && unlinkedMatches(u, q))\n"
  "    .map((u, i)=>({u, i}));"),
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
  "  const legs = arr(u.legs).map(l=>{", "  const legs = (u.legs||[]).map(l=>{"),
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
 ("an archived customer's unlinked row is shown again",
  """    data["tracker_unlinked"] = [
        u for u in data["tracker_unlinked"]
        if not (isinstance(u, dict) and _squash(u.get("client")) in arch_names)]""",
  "    pass"),
 ("the archived-name match is taken after the companies are filtered out",
  "    arch_names = {_squash(c.get(\"display_name\")) for c in _all_companies\n"
  "                  if c.get(\"archived\")}",
  "    arch_names = {_squash(c.get(\"display_name\")) for c in data[\"companies\"]\n"
  "                  if c.get(\"archived\")}"),
 ("adoption goes back to assuming the deal is won",
  "    status: document.getElementById('a_status').value || null,",
  "    status: 'won',"),
 ("adoption goes back to stamping the year it was adopted in",
  "    year: numOrNull('a_year'),", "    year: new Date().getFullYear(),"),
 ("the adopted year is read from the clock rather than the start date",
  "  const iso = isoDate(st(u && u.start_date));\n"
  "  return iso ? Number(iso.slice(0, 4)) : new Date().getFullYear();",
  "  return new Date().getFullYear();"),

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

"""Merge a fresh import into a live store without destroying operator work.

The problem this exists for
---------------------------
normalize.py rewrites all seven store files wholesale. `_guard_live_store`
refuses to do that to a store that has been used, and `--force` bypasses the
guard -- so the operator's only two options were "never re-import" or "lose
everything since the last import": hand-entered invoices (source="manual")
deleted outright, and every payment status, note and due-date override reverted
to whatever the workbook says. The normal case -- keep using the tracker, pull
an updated import -- had no supported path at all.

The rule
--------
A field is refreshed from the workbook UNLESS the operator has edited that
exact field on that exact record. changelog.jsonl records every edit as
(entity, key, fields), so this is precise rather than a heuristic about which
fields "look operator-owned".

Three things are absolute:

  * NOTHING IS EVER DELETED. A record the workbook no longer mentions is kept
    and flagged. A hand-created record is kept. An archived record is kept, and
    stays archived. A re-import must never be able to remove a receivable.
  * archived / archived_at always survive. Soft-delete is an operator decision
    and the workbook knows nothing about it.
  * If the store holds data but changelog.jsonl is missing, MERGE REFUSES.
    Without it we cannot tell an operator edit from an import artefact, and
    guessing is exactly what caused the damage this module prevents.

Everything it did is reported, per record and per field, so a merge is
reviewable rather than trusted.
"""
import json
import os

# Identity for each entity: how a record from the workbook is matched to one
# already in the store. Mirrors the tool layer's own keys.
KEYS = {
    "companies.json": lambda r: ("company_id", _s(r.get("company_id"))),
    # "?" is the literal placeholder normalize.py writes into the email column,
    # so it identifies nobody -- keying on it collapsed every placeholder
    # contact in a company into one record.
    "contacts.json": lambda r: ("contact",
                                (_s(r.get("company_id")),
                                 (_s(r.get("email")).lower()
                                  if _s(r.get("email")) not in ("", "?") else "")
                                 or _s(r.get("name")).lower())),
    "projects.json": lambda r: ("project_no", _idkey(r.get("project_no"))),
    "shipments.json": lambda r: ("shipment_id", _idkey(r.get("shipment_id"))),
    "invoices.json": lambda r: ("invoice",
                                (_s(r.get("company_id")), _idkey(r.get("invoice_no")))),
    "vendors.json": lambda r: ("company_id", _s(r.get("company_id"))),
}
# needs_review is regenerated wholesale every import: it is the importer's own
# commentary on THIS run, not operator data.
# tracker_buckets/tracker_unlinked join it: both are the importer's reading of
# the Project Tracker sheet on THIS run -- the bucket labels come from the
# legend, the unlinked rows are ones that could not be matched to a project.
# Neither is operator data, and neither has a stable key to merge on.
REGENERATED = {"needs_review.json", "tracker_buckets.json",
               "tracker_unlinked.json"}

# Fields the WORKBOOK owns, refreshed (never removed) even in add-only mode.
#
# Add-only mode exists to protect operator edits when there is no changelog to
# identify them. Withholding these meant an operator whose store has no
# changelog.jsonl -- created lazily, so absent on any store that was imported
# and never edited -- would upgrade, import, land on the new default screen and
# read "No live projects yet" permanently, on every subsequent import too.
#
# They are NOT unwritable: tracker_status is in PROJECT_FIELDS and reachable
# through update_project, and tracker_row is written by the adopt flow. So this
# does trade away one thing -- in add-only mode a bucket the operator moved
# through chat is overwritten by the sheet. That is the deliberate call: the
# sheet is where the colour comes from, the bucket is re-derivable, and the
# alternative is a screen with nothing on it. Non-conservative mode still
# preserves such an edit normally, via `touched`.
#
# open_orders_notes is deliberately NOT here: it is the operator's own text.
IMPORTER_OWNED = {"tracker_status", "tracker_row"}

# how Store.log names each entity, and how it builds the key it logs under
CHANGELOG_ENTITY = {
    "companies.json": "company", "contacts.json": "contact",
    "projects.json": "project", "shipments.json": "shipment",
    "invoices.json": "invoice", "vendors.json": "vendor",
}


def _s(v):
    return "" if v is None else str(v).strip()


def _idkey(v):
    """Identifier in the form Store.log writes it.

    Must match server._key(): it de-floats through _num_to_str, so an
    invoice_no stored as the JSON number 7011.0 is logged as "7011". Using a
    bare str() here produced "7011.0", matched no changelog entry, and a
    collected receivable silently reverted to open on the next re-import.
    """
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def load_operator_edits(store_dir):
    """{(entity, key): {field, ...}} -- every field the operator has changed.

    Returns None if changelog.jsonl is absent, which the caller must treat as
    "cannot merge safely", not as "no edits".
    """
    path = os.path.join(store_dir, "changelog.jsonl")
    if not os.path.exists(path):
        return None
    edits, created, renamed_from = {}, set(), set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue                      # torn tail line; skip, not fatal
            if not isinstance(e, dict):
                continue
            ent, key, op = e.get("entity"), _s(e.get("key")), e.get("op")
            fields = e.get("fields")
            if not ent or not key:
                continue
            if op == "create":
                created.add((ent, key))
                # A record the operator CREATED is theirs in full: everything
                # they set at creation must survive a re-import. Without this a
                # hand-entered invoice marked paid reverted to open and lost
                # source="manual", which also re-armed the commission audit.
                if isinstance(fields, dict):
                    edits.setdefault((ent, key), set()).update(fields.keys())
                edits.setdefault((ent, key), set()).update(
                    {"payment_status", "pay_date", "payment_notes", "source",
                     "invoice_no", "project_no", "due_on"}
                    if ent == "invoice" else {"source"})
            if op == "rename" and isinstance(fields, dict):
                # An edit is recorded under the number the record had AT THE
                # TIME. A later rename moves the record, so looking it up by its
                # CURRENT key found nothing and the workbook silently reverted a
                # payment the operator had recorded -- the exact failure this
                # module exists to prevent. Renames are therefore applied
                # SEQUENTIALLY, in log order, to the edits accumulated so far.
                # (Same defect, same fix, as audit_commission_pct.load_changelog:
                # a timestamp-free old->new map applied every rename to every
                # edit and got undone renumbers and reused numbers wrong.)
                new_key = _renamed_key(ent, key, fields)
                if new_key and new_key != key:
                    # the workbook still lists the OLD number; re-adding it
                    # would resurrect the same receivable as a second record,
                    # one open and one paid, double-counting the total
                    renamed_from.add((ent, key))
                    renamed_from.discard((ent, new_key))
                    moved = edits.pop((ent, key), set())
                    # the rename is itself an operator decision: the identifier
                    # must not be reverted by the workbook either
                    moved.update({"invoice_no"} if ent == "invoice"
                                 else {"project_no"} if ent == "project" else set())
                    edits.setdefault((ent, new_key), set()).update(moved)
                    if (ent, key) in created:
                        created.discard((ent, key))
                        created.add((ent, new_key))
                continue
            if op == "reassign" and isinstance(fields, dict):
                # logs old_project_no/new_project_no/also_project_nos -- names
                # that appear nowhere on the record. Map them to the fields the
                # reassignment actually changes, or the operator's "this leg was
                # filed under the wrong deal" correction is silently undone.
                edits.setdefault((ent, key), set()).update(
                    {"project_no", "all_project_nos", "linked_to_project",
                     "company_id", "client_name"})
                continue
            if op in ("update", "archive", "restore") and isinstance(fields, dict):
                edits.setdefault((ent, key), set()).update(fields.keys())
            if op in ("archive", "restore"):
                edits.setdefault((ent, key), set()).update({"archived", "archived_at"})
    return {"edits": edits, "created": created,
            "renamed_from": renamed_from}


def _renamed_key(entity, old_key, fields):
    """The changelog key a record moves to when it is renamed.

    Mirrors what Store.log writes: rename_project logs key=<old project_no>
    with new_project_no; rename_invoice logs key="<company_id>:<old>" with
    new_invoice_no.
    """
    if entity == "project":
        return _s(fields.get("new_project_no")) or None
    if entity == "invoice":
        new_no = _s(fields.get("new_invoice_no"))
        if not new_no:
            return None
        cid = old_key.rsplit(":", 1)[0] if ":" in old_key else ""
        return f"{cid}:{new_no}" if cid else None
    return None


def _entities_in_changelog(store_dir):
    """Entity names appearing in changelog.jsonl -- evidence a file existed."""
    seen = set()
    path = os.path.join(store_dir, "changelog.jsonl")
    try:
        if not os.path.exists(path):
            return seen
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict) and e.get("entity"):
                    seen.add(e["entity"])
    except OSError:
        return set()
    return seen


def _log_key(fname, rec):
    """Rebuild the key Store.log would have written for this record."""
    if fname == "invoices.json":
        return f"{_s(rec.get('company_id'))}:{_idkey(rec.get('invoice_no'))}"
    if fname == "contacts.json":
        return _s(rec.get("email")) or _s(rec.get("name"))
    if fname == "projects.json":
        return _idkey(rec.get("project_no"))
    if fname == "shipments.json":
        return _idkey(rec.get("shipment_id"))
    return _s(rec.get("company_id"))


def merge_all(fresh_files, store_dir):
    """Merge every entity file. Raises RuntimeError if it cannot do so safely.

    fresh_files: {"invoices.json": [...], ...} straight from normalize.run
    """
    # An entity file that is ABSENT while the changelog proves it held records
    # is the OneDrive-not-synced case. Merging would write the workbook's
    # version of that entity over a file whose real contents are simply not
    # here yet. The server refuses to start on this; the importer must refuse
    # too, or it becomes the way around that guard.
    missing_but_evidenced = []
    ents = _entities_in_changelog(store_dir)
    for fname, ent in (("invoices.json", "invoice"), ("projects.json", "project"),
                       ("shipments.json", "shipment"), ("contacts.json", "contact"),
                       ("companies.json", "company"), ("vendors.json", "vendor")):
        if ent in ents and not os.path.exists(os.path.join(store_dir, fname)):
            missing_but_evidenced.append(fname)
    if missing_but_evidenced:
        raise RuntimeError(
            f"{missing_but_evidenced} are missing from the store, but its own "
            f"changelog shows those records existed. Refusing to import -- if "
            f"the store is on OneDrive the files may simply not have synced "
            f"down yet, and importing now would write over records that are "
            f"not here. Check the folder is fully synced, then re-run.")

    operator = load_operator_edits(store_dir)
    has_data = False
    for fname in KEYS:
        p = os.path.join(store_dir, fname)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    if json.load(f):
                        has_data = True
                        break
            except (OSError, ValueError):
                has_data = True                # unreadable: assume it matters
                break
    # No changelog on a store that holds data: we cannot tell an operator edit
    # from an import artefact. The first version REFUSED and told the operator
    # to use --replace -- which itself refuses, then needs --force, which
    # destroys every record. Pointing at the more destructive option is the
    # dead-end class this project has hit twice before.
    #
    # Instead: fall back to ADD-ONLY. New rows from the workbook are added;
    # every record already in the store is left completely untouched. That is
    # safe whether the changelog is absent because nothing was ever edited or
    # because it was lost, and it is strictly safer than either alternative.
    conservative = has_data and operator is None
    operator = operator or {"edits": {}, "created": set(), "renamed_from": set()}
    if conservative:
        report_note = ("no changelog.jsonl: nothing already in the store was "
                       "refreshed, only new rows were added -- except the "
                       "Project Tracker status colour, which the workbook owns "
                       "outright and which nothing in the app can edit")
    else:
        report_note = None
    operator.setdefault("renamed_from", set())

    merged, report = {}, {"refreshed": 0, "preserved": [], "kept": [], "added": 0,
                      "ambiguous": [], "renamed_away": [], "note": None}
    for fname, fresh in fresh_files.items():
        if fname in REGENERATED:
            merged[fname] = fresh
            continue
        path = os.path.join(store_dir, fname)
        existing = []
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8-sig") as f:
                    existing = json.load(f)
            except (OSError, ValueError):
                raise RuntimeError(f"{fname} is unreadable; refusing to merge "
                                   f"into a store that cannot be read")
        if not isinstance(existing, list):
            existing = []

        keyfn = KEYS[fname]
        ent = CHANGELOG_ENTITY[fname]
        # group, do NOT collapse. A dict comprehension is last-wins, so two
        # records sharing a key silently lost one -- and the edit lookup then
        # attributed one record's changes to the other, which the report
        # cheerfully described as "kept your edits". Duplicate project numbers
        # are the exact legacy shape _one_project exists for, and duplicate
        # contact keys occur in the ordinary case.
        old_groups = {}
        for rec in existing:
            if isinstance(rec, dict):
                old_groups.setdefault(keyfn(rec)[1], []).append(rec)
        ambiguous = {k for k, v in old_groups.items() if len(v) > 1}
        old_by_key = {k: v[0] for k, v in old_groups.items() if len(v) == 1}
        out, used = [], set()

        for rec in fresh:
            k = keyfn(rec)[1]
            if (ent, _log_key(fname, rec)) in operator["renamed_from"]:
                report["renamed_away"].append({"file": fname, "key": str(k)})
                continue
            if k in ambiguous:
                # cannot tell which record the workbook row refers to, and
                # cannot tell whose edits are whose. Keep every existing record
                # untouched and refresh none of them.
                report["ambiguous"].append({"file": fname, "key": str(k),
                                            "count": len(old_groups[k])})
                continue
            prior = old_by_key.get(k)
            if prior is None:
                out.append(rec)
                report["added"] += 1
                continue
            used.add(k)
            if conservative:
                # untouched, except for the fields the workbook owns outright.
                #
                # REFRESHED WHEN PRESENT, NEVER REMOVED. "Absent from the fresh
                # record" does not mean "retired on the sheet": normalize only
                # attaches these fields to a project a tracker row MATCHED, so
                # every project is missing them whenever the tracker matched
                # nothing -- an older copy of the workbook, a renamed sheet, a
                # tracker not yet filled in for the week. Popping on absence
                # emptied the Live screen off one such import, which is the
                # exact failure this block exists to prevent, and it destroyed
                # tracker_row on adopted projects, which the importer can never
                # re-derive. A stale bucket is recoverable by importing the
                # right workbook; a wiped one is not.
                kept = dict(prior)
                for field in IMPORTER_OWNED:
                    if field in rec:
                        kept[field] = rec[field]
                out.append(kept)
                report["untouched"] = report.get("untouched", 0) + 1
                continue
            touched = operator["edits"].get((ent, _log_key(fname, prior)), set())
            merged_rec = dict(rec)
            for field in touched:
                if field in prior:
                    merged_rec[field] = prior[field]
            # soft-delete is always the operator's, never the workbook's
            for field in ("archived", "archived_at"):
                if field in prior:
                    merged_rec[field] = prior[field]
            if touched:
                report["preserved"].append(
                    {"file": fname, "key": str(k), "fields": sorted(touched)})
            report["refreshed"] += 1
            out.append(merged_rec)

        for k in ambiguous:
            out.extend(old_groups[k])          # all of them, untouched
        # anything the workbook no longer mentions is KEPT, never dropped
        for k, prior in old_by_key.items():
            if k in used:
                continue
            why = ("created by hand"
                   if _s(prior.get("source")).lower() == "manual"
                   else "archived" if prior.get("archived")
                   else "no longer in the workbook")
            report["kept"].append({"file": fname, "key": str(k), "why": why})
            out.append(prior)

        merged[fname] = out

    # ---- a row he already adopted must not come back -----------------------
    #
    # tracker_unlinked is regenerated from the sheet on every run, and the sheet
    # still has no CRM number on that row -- the number went into the CRM, which
    # is the direction of travel. Without this the row he adopted last week
    # returns beside the project it became, "Add to CRM" on the phantom fails
    # with "project already exists", and saveAdoptTrackerRow only clears a card
    # on SUCCESS, so the card is undismissable and returns every import.
    #
    # ONLY the exact key match. A first attempt also matched a numberless row on
    # (tracker_row, note), and that heuristic was wrong three ways: both notes
    # empty collapsed it to the row number alone -- which HIDES a live job, the
    # outcome this file calls worse than a duplicate card; a note edited in the
    # adopt form (which the form invites) never matched anyway; and rows move
    # week to week. A numberless row genuinely has nothing stable to match on,
    # so it is left showing. A duplicate card is visible and survivable; a
    # dropped job is neither. See report["adopted"] and format_report.
    #
    # _idkey, not _s: a numeric key cell reaches JSON as 7011.0 and normalize
    # stores raw_key with a bare str(). This module has been bitten by that
    # exact ".0" mismatch before -- see the _idkey docstring.
    unl = merged.get("tracker_unlinked.json")
    if isinstance(unl, list):
        by_key = {_idkey(p.get("project_no"))
                  for p in (merged.get("projects.json") or [])
                  if isinstance(p, dict) and _idkey(p.get("project_no"))}
        kept_unl, adopted = [], []
        for u in unl:
            if not isinstance(u, dict):
                continue    # skip-ok: a malformed entry is not a row to show
            keys = [_idkey(k) for k in (u.get("parsed_keys") or [])]
            if not keys:
                keys = [_idkey(u.get("raw_key"))]
            hit = next((k for k in keys if k and k in by_key), None)
            if hit:
                adopted.append(hit)
                continue    # skip-ok: it IS a project now; listed in report["adopted"]
            kept_unl.append(u)
        merged["tracker_unlinked.json"] = kept_unl
        if adopted:
            report["adopted"] = adopted

    report["note"] = report_note
    return merged, report


def format_report(report):
    L = ([f"NOTE: {report['note']}"] if report.get("note") else []) + [f"refreshed {report['refreshed']} record(s) from the workbook, "
         f"added {report['added']} new one(s)."]
    if report["preserved"]:
        L.append(f"\nKEPT YOUR EDITS on {len(report['preserved'])} record(s) -- "
                 f"the workbook did not overwrite these:")
        for p in report["preserved"][:40]:
            L.append(f"  {p['file']} {p['key']}: {', '.join(p['fields'])}")
        if len(report["preserved"]) > 40:
            L.append(f"  ... and {len(report['preserved']) - 40} more")
    if report.get("ambiguous"):
        L.append(f"\nCOULD NOT MATCH {len(report['ambiguous'])} workbook row(s): "
                 f"the store holds more than one record under each of these "
                 f"numbers, so there is no way to tell which one the workbook "
                 f"meant. Every existing record was left EXACTLY as it is, and "
                 f"the workbook's version of these was NOT applied -- it will "
                 f"keep being skipped until the duplicate is resolved:")
        for a in report["ambiguous"][:40]:
            L.append(f"  {a['file']} {a['key']}  ({a['count']} records share it)")
        if len(report["ambiguous"]) > 40:
            L.append(f"  ... and {len(report['ambiguous']) - 40} more")
    if report.get("renamed_away"):
        L.append(f"\nSKIPPED {len(report['renamed_away'])} workbook row(s) whose "
                 f"number you have since changed -- re-adding them would create "
                 f"the same record twice:")
        for a in report["renamed_away"][:20]:
            L.append(f"  {a['file']} {a['key']}")
    if report.get("adopted"):
        # A row dropped from the Live Tracker with nothing said is the same
        # silence this module exists to end -- and the two `# skip-ok:` markers
        # at the drop site claim it is reported here, which has to be true.
        L.append(f"\nTOOK {len(report['adopted'])} tracker row(s) off the "
                 f"\"Not in the CRM yet\" list: you already gave each of these a "
                 f"project number, so the row is now a project and is no longer "
                 f"offered for adoption:")
        for a in report["adopted"][:40]:
            L.append(f"  project {a}")
        if len(report["adopted"]) > 40:
            L.append(f"  ... and {len(report['adopted']) - 40} more")
    if report.get("untouched"):
        L.append(f"\n{report['untouched']} record(s) already in the store were "
                 f"left untouched (see the note above).")
    if report["kept"]:
        L.append(f"\nKEPT {len(report['kept'])} record(s) the workbook no longer "
                 f"lists. Nothing was deleted -- review these:")
        for k in report["kept"][:40]:
            L.append(f"  {k['file']} {k['key']}  ({k['why']})")
        if len(report["kept"]) > 40:
            L.append(f"  ... and {len(report['kept']) - 40} more")
    return "\n".join(L)

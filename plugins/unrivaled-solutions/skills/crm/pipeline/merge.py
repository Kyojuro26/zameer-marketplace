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

# Fields the importer NEVER produces, per file: only the operator (through the
# server) writes them. The refresh path starts from the workbook's record and
# used to copy back only what the changelog named, so one of these survived a
# re-import ONLY while its changelog line existed -- and Store.log swallows
# OSError (a locked changelog on OneDrive), so an edit can land with no line.
# The next import then deleted it outright: a follow-up date, a quote date, a
# due-date override, gone with no word. These are now carried from the stored
# record whenever the workbook's record does not supply them (absent or null),
# changelog or not. tests/regression/test_operator_only.py holds the project
# set equal to "PROJECT_FIELDS the importer does not emit".
OPERATOR_ONLY = {
    "projects.json": {"next_action", "next_action_on", "quote_requested_on",
                      "quote_sent_on", "quote_revisions", "completed_on",
                      "tracker_key"},
    "shipments.json": {"eta"},
    "invoices.json": {"due_on", "source"},
    "companies.json": {"notes", "linked_vendor_id", "qbo_name"},
    "vendors.json": {"notes", "qbo_name"},
}

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


def _po(v):
    """A vendor PO as a person reads it: case and spacing do not make it a
    different PO."""
    return " ".join(_s(v).split()).casefold()


def _po_changed(prior, rec):
    """The leg at this position is a different delivery. A PO that appears
    where there was none is the same leg being filled in; a PO that changes,
    or disappears, cannot be confirmed as the same delivery."""
    old = _po(prior.get("vendor_po_raw"))
    return bool(old) and old != _po(rec.get("vendor_po_raw"))


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


DISMISS_REASONS = ("not_a_job", "already_adopted")


def _dismiss_reason(v):
    """The three the card knows. Anything else is not a reason it can show."""
    return _s(v) if _s(v) in DISMISS_REASONS else "not_a_job"


def _sweep_dismissals(merged, store_dir, report):
    """The dismissal sweep. ONE implementation, used by both import modes.

    Extracted rather than copied: merge mode and replace mode disagreeing about
    what bounds this table is exactly how the bound stops being structural.
    """
    # ---- what takes a row off the list, and what no longer does -----------
    #
    # by_sheet_key is DELETED. It held the sheet's own free-text key, recorded
    # on the project at adoption, so it accumulated a key from every adoption
    # ever made and compared it against a sheet that turns over completely.
    # Free-text keys collide -- "Word Proposal" and "Check" are real shapes on
    # this workbook -- so a row nobody adopted got retired by a phrase somebody
    # adopted months ago, which HIDES A LIVE JOB. The workbook is being retired
    # after a handful more imports, so this list is a one-time migration
    # checklist rather than a weekly screen, and a job hidden during the
    # migration is one that never reaches the system of record at all.
    #
    # by_key is KEPT: the sheet's parsed project NUMBER against the numbers
    # currently in the store. One time horizon, both sides read now, nothing
    # carried forward from a past adoption. It is what makes the checklist burn
    # down -- adopt a row and it retires itself on the next import, instead of
    # needing a second click on the one pass through the sheet that matters.
    #
    # So there are still TWO things that can take a row off this list, and an
    # earlier version of this comment claimed there was one. They agree only
    # because of the ORDER below: by_key retires first, and the dismissal sweep
    # then runs over the SURVIVORS. A dismissal on a retired row is therefore
    # swept rather than stranded, and neither path can hide what the other has
    # already settled. Reverse that order and they disagree exactly as by_key
    # and by_sheet_key once did -- a row counted in "HOLDING N dismissed" with
    # no card on screen, returning already-dismissed the day its project is
    # archived.
    #
    # THE DISMISSAL RULE: a dismissal is scoped to the row AS IT EXISTS IN THIS
    # SHEET. Dismissals whose rows are not among this import's survivors are
    # SWEPT. That is what bounds the table -- kept is a subset of the rows on
    # the sheet, so it can never be larger than the sheet. A dismissal store
    # that accumulates is by_sheet_key with a new name.
    unl = merged.get("tracker_unlinked.json")
    if isinstance(unl, list):
        rows = [u for u in unl if isinstance(u, dict)]

        # An archived COMPANY takes its projects with it. archive_company marks
        # only the company record, so a project under it stays unarchived --
        # and by_key went on suppressing its tracker row while build_view
        # dropped the project itself off the page. The job was then on no list
        # and in no count, the one outcome this screen exists to prevent.
        _arch_co = {c.get("company_id")
                    for c in (merged.get("companies.json") or [])
                    if isinstance(c, dict) and c.get("archived")}
        projs = [p for p in (merged.get("projects.json") or [])
                 if isinstance(p, dict) and not p.get("archived")
                 and p.get("company_id") not in _arch_co]
        by_key = {_idkey(p.get("project_no")) for p in projs
                  if _idkey(p.get("project_no"))}

        # RETIRE FIRST, then sweep against what SURVIVES. `live` used to be
        # built from every row -- before the by_key drop -- so a row that was
        # both dismissed and retired kept its dismissal while its row vanished:
        # no card, no "Put it back", dismiss_tracker_row refusing it as "not on
        # the current sheet", and "HOLDING 1 dismissed" printed over an empty
        # section. Archive the project later and the row came back ALREADY
        # dismissed on a stale reason, defeating the archived exclusion for
        # exactly the rows that needed it.
        survivors, adopted = [], []
        for u in rows:
            # NUMBERS only, and ALL of them.
            #
            # No raw_key fallback: parsed_keys is empty exactly when the key
            # cell is free text, so falling back to it matched a phrase against
            # project_no -- and the store really does hold free-text project
            # numbers ("Word Offer", "Cash Deal?", "INV 1065") while a live row
            # is keyed "Word Proposal". Same collision by_sheet_key was deleted
            # for, minus only its accumulation.
            #
            # ALL, not ANY: a row keyed "4530 and 4531" carries two jobs.
            # Retiring it when the first is adopted takes the whole row off the
            # checklist while the second never reaches the store, and on a
            # one-time migration a job that leaves the checklist unentered is
            # simply lost.
            keys = [k for k in (_idkey(x) for x in (u.get("parsed_keys") or []))
                    if k]
            if keys and all(k in by_key for k in keys):
                adopted.extend(keys)
                continue    # skip-ok: it IS a project now; named in the report
            survivors.append(u)
        live = {_s(u.get("fingerprint")) for u in survivors
                if _s(u.get("fingerprint"))}

        # Unreadable is NOT empty. Reading a half-written OneDrive file as "no
        # dismissals" would silently un-dismiss everything; reading it as "all
        # dismissed" would silently hide live work. Neither is safe to guess,
        # so every row shows and it SAYS the file could not be read.
        dismissals, unreadable = [], None
        dpath = os.path.join(store_dir, "tracker_dismissed.json")
        try:
            with open(dpath, encoding="utf-8-sig") as f:
                raw = json.load(f)
            dismissals = [d for d in raw if isinstance(d, dict)] \
                if isinstance(raw, list) else []
        except FileNotFoundError:
            pass                # absence is normal on any store before this
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            unreadable = (f"tracker_dismissed.json could not be read ({e}); "
                          f"every row is being shown, and the file has been "
                          f"left exactly as it is")

        # DEDUPED, first entry wins -- a conflicted copy concatenated by
        # OneDrive can carry one fingerprint several times. A duplicate is
        # DROPPED but not counted as SWEPT: `swept` means "its row left the
        # sheet", and it is the counter the report offers as proof the bound
        # is working.
        #
        # An EMPTY fingerprint matches nothing: `live` never holds one, and
        # without the `fp and` guard _s(None) == "" on both sides would flag
        # every pre-upgrade row at once.
        kept, seen_fp, swept = [], set(), 0
        for d in dismissals:
            fp = _s(d.get("fingerprint"))
            if fp and fp in live:
                if fp not in seen_fp:
                    seen_fp.add(fp)
                    kept.append(d)
            else:
                swept += 1
        reason_by_fp = {_s(d.get("fingerprint")): _dismiss_reason(d.get("reason"))
                        for d in kept}

        # Flagged, not deleted. The screen has to be able to show a count: a
        # dismissal the operator cannot see is one that can hide a live job.
        # The REASON rides along, because the card reads it off the row.
        out_rows, n_dismissed_rows = [], 0
        for u in survivors:
            fp = _s(u.get("fingerprint"))
            if fp and fp in reason_by_fp:
                u = dict(u, dismissed=True, reason_dismissed=reason_by_fp[fp])
                n_dismissed_rows += 1
            else:
                u = {k: v for k, v in u.items()
                     if k not in ("dismissed", "reason_dismissed")}
            out_rows.append(u)
        merged["tracker_unlinked.json"] = out_rows
        if adopted:
            report["adopted"] = adopted
        if unreadable:
            # NOT written back. _finish writes every key of `merged`, so an
            # empty list here would DELETE the file the report is telling him
            # to fix, turning a transient half-written read into permanent
            # loss of every dismissal.
            report["dismissals_unreadable"] = unreadable
        else:
            merged["tracker_dismissed.json"] = kept
        if swept:
            report["dismissals_swept"] = swept
        if n_dismissed_rows:
            # ROWS, not records. One dismissal flags every row sharing its
            # fingerprint -- by design, since the operator cannot tell those
            # rows apart -- so counting records printed "HOLDING 1" over three
            # cards. A count he cannot reconcile with the screen is worse than
            # none, which is the rule the dedupe above states.
            report["dismissed"] = n_dismissed_rows


    return merged


def sweep_dismissals_only(merged, store_dir):
    """--replace path: no record merge, but the dismissal table is still swept.

    Replace mode discards operator RECORDS by design. It does not get to
    abandon the rule that a dismissal cannot outlive the row it was scoped to.

    Returns (merged, report). The report was discarded here at first, which
    made replace mode SILENT about both halves it is meant to speak about: a
    swept dismissal, and a dismissal file it could not read. Merge mode prints
    a paragraph on each; a mode that quietly does the same work and says
    nothing is how a operator stops being able to check the bound at all."""
    report = {}
    _sweep_dismissals(merged, store_dir, report)
    return merged, report


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
                      "ambiguous": [], "renamed_away": [], "note": None,
                      "company_changed": [], "po_changed": []}
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
            for field in OPERATOR_ONLY.get(fname, ()):
                if merged_rec.get(field) is None and field in prior:
                    merged_rec[field] = prior[field]
            # Merge follows the key; when the workbook changes what stands
            # behind it, say so (0.1.43, the operator's decision).
            #   A project listed under another customer: the number is unique
            #   across the business, so this is a correction -- the operator's
            #   fields carry, and the report names both customers and them.
            #   A shipment leg's id is its position on the sheet, so a leg
            #   whose vendor PO changed is a different delivery: its operator
            #   fields do NOT carry (not even through the changelog), and the
            #   report lists what was dropped so it can be re-entered.
            # Both compare the stored record with what the MERGED record keeps,
            # not with the workbook's row: a company or PO the operator changed
            # in the app is kept by the touched loop above, so the workbook
            # disagreeing with it is not a change (focused review of 0.1.43).
            dropped = {}
            if fname == "projects.json" and \
                    _s(prior.get("company_id")) != _s(merged_rec.get("company_id")):
                report["company_changed"].append({
                    "key": str(k),
                    "old": _s(prior.get("company_id")), "new": _s(merged_rec.get("company_id")),
                    "old_name": _s(prior.get("company_name")),
                    "new_name": _s(merged_rec.get("company_name")),
                    "carried": sorted(f for f in OPERATOR_ONLY[fname]
                                      if rec.get(f) is None and merged_rec.get(f) is not None)})
            if fname == "shipments.json" and _po_changed(prior, merged_rec):
                dropped = {f: merged_rec[f] for f in sorted(OPERATOR_ONLY[fname])
                           if rec.get(f) is None and merged_rec.get(f) is not None}
                for f in dropped:
                    if f in rec:
                        merged_rec[f] = rec[f]
                    else:
                        merged_rec.pop(f, None)
                if dropped:
                    report["po_changed"].append({
                        "key": str(k), "old_po": _s(prior.get("vendor_po_raw")),
                        "new_po": _s(merged_rec.get("vendor_po_raw")), "dropped": dropped})
            # soft-delete is always the operator's, never the workbook's
            for field in ("archived", "archived_at"):
                if field in prior:
                    merged_rec[field] = prior[field]
            # what was actually kept: a touched field is copied only when the
            # stored record has it, and a dropped one was not kept at all --
            # listing the changelog's names said "kept eta" on a leg with none
            kept = {f for f in touched if f in prior} - set(dropped)
            if kept:
                report["preserved"].append(
                    {"file": fname, "key": str(k), "fields": sorted(kept)})
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

    _sweep_dismissals(merged, store_dir, report)

    report["note"] = report_note
    return merged, report


def format_report(report):
    # .get() throughout. sweep_dismissals_only produces a report carrying ONLY
    # the dismissal keys, and three raw subscripts here raised KeyError on it --
    # AFTER the import had written every file, so the operator got a traceback
    # and exit 1 on top of a successful import and never saw the line it was
    # raising about.
    L = [f"NOTE: {report['note']}"] if report.get("note") else []
    if "refreshed" in report or "added" in report:
        L.append(f"refreshed {report.get('refreshed', 0)} record(s) from the "
                 f"workbook, added {report.get('added', 0)} new one(s).")
    if report.get("preserved"):
        L.append(f"\nKEPT YOUR EDITS on {len(report['preserved'])} record(s) -- "
                 f"the workbook did not overwrite these:")
        for p in report["preserved"][:40]:
            L.append(f"  {p['file']} {p['key']}: {', '.join(p['fields'])}")
        if len(report["preserved"]) > 40:
            L.append(f"  ... and {len(report['preserved']) - 40} more")
    if report.get("company_changed"):
        L.append(f"\nCUSTOMER CHANGED on {len(report['company_changed'])} project(s): the "
                 f"workbook now lists these numbers under a different customer. "
                 f"Your own fields were carried onto them:")
        for c in report["company_changed"][:40]:
            old = f"{c.get('old_name') or c['old']} ({c['old']})" if c["old"] else "no customer"
            new = f"{c.get('new_name') or c['new']} ({c['new']})" if c["new"] else "no customer"
            L.append(f"  project {c['key']}: {old} -> {new}; carried: "
                     f"{', '.join(c['carried']) or 'none'}")
        if len(report["company_changed"]) > 40:
            L.append(f"  ... and {len(report['company_changed']) - 40} more")
    if report.get("po_changed"):
        L.append(f"\nDELIVERY VENDOR CHANGED on {len(report['po_changed'])} shipment leg(s): "
                 f"the workbook now has a different vendor PO at this position, so "
                 f"your own dates for the old one were NOT carried. Re-enter them "
                 f"if they still apply:")
        for c in report["po_changed"][:40]:
            L.append(f"  {c['key']}: {c['old_po'] or '(no PO)'} -> {c['new_po'] or '(no PO)'}; "
                     f"dropped " + ", ".join(f"{f} {v}" for f, v in c["dropped"].items()))
        if len(report["po_changed"]) > 40:
            L.append(f"  ... and {len(report['po_changed']) - 40} more")
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
    if report.get("dismissals_unreadable"):
        L.append(f"\nCOULD NOT READ your dismissed-rows file, so every tracker "
                 f"row is showing:\n  {report['dismissals_unreadable']}")
    if report.get("dismissals_swept"):
        # Swept means the row it was scoped to is not on this sheet. Said out
        # loud because it is the mechanism that keeps this table from growing
        # into the thing it replaced, and a mechanism nobody can see is one
        # nobody can check.
        L.append(f"\nCLEARED {report['dismissals_swept']} dismissal(s) whose "
                 f"tracker row is no longer on the sheet. A dismissal only ever "
                 f"applies to the row as it stands in the workbook -- if one of "
                 f"those rows comes back, or comes back changed, it is offered "
                 f"again rather than staying hidden on an old decision.")
    if report.get("adopted"):
        # A row leaving the screen with nothing said is the silence this module
        # exists to end, and the skip-ok marker at the drop site claims it is
        # reported here.
        L.append(f"\nTOOK {len(report['adopted'])} tracker row(s) off the "
                 f"\"Not in the CRM yet\" list: each of these now has a project "
                 f"under the same number, so the row is a project and is no "
                 f"longer offered for adoption:")
        for a in report["adopted"][:40]:
            L.append(f"  project {a}")
        if len(report["adopted"]) > 40:
            L.append(f"  ... and {len(report['adopted']) - 40} more")
    if report.get("untouched"):
        L.append(f"\n{report['untouched']} record(s) already in the store were "
                 f"left untouched (see the note above).")
    if report.get("kept"):
        L.append(f"\nKEPT {len(report['kept'])} record(s) the workbook no longer "
                 f"lists. Nothing was deleted -- review these:")
        for k in report["kept"][:40]:
            L.append(f"  {k['file']} {k['key']}  ({k['why']})")
        if len(report["kept"]) > 40:
            L.append(f"  ... and {len(report['kept']) - 40} more")
    if report.get("dismissed"):
        L.append(f"\nHOLDING {report['dismissed']} tracker row(s) dismissed -- "
                 f"they are on the Live screen under \"Dismissed\", not gone.")

    return "\n".join(L)

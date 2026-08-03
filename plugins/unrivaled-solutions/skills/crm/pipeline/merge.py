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
    "projects.json": lambda r: ("project_no", _s(r.get("project_no"))),
    "shipments.json": lambda r: ("shipment_id", _s(r.get("shipment_id"))),
    "invoices.json": lambda r: ("invoice",
                                (_s(r.get("company_id")), _s(r.get("invoice_no")))),
    "vendors.json": lambda r: ("company_id", _s(r.get("company_id"))),
}
# needs_review is regenerated wholesale every import: it is the importer's own
# commentary on THIS run, not operator data.
REGENERATED = {"needs_review.json"}

# how Store.log names each entity, and how it builds the key it logs under
CHANGELOG_ENTITY = {
    "companies.json": "company", "contacts.json": "contact",
    "projects.json": "project", "shipments.json": "shipment",
    "invoices.json": "invoice", "vendors.json": "vendor",
}


def _s(v):
    return "" if v is None else str(v).strip()


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


def _log_key(fname, rec):
    """Rebuild the key Store.log would have written for this record."""
    if fname == "invoices.json":
        return f"{_s(rec.get('company_id'))}:{_s(rec.get('invoice_no'))}"
    if fname == "contacts.json":
        return _s(rec.get("email")) or _s(rec.get("name"))
    if fname == "projects.json":
        return _s(rec.get("project_no"))
    if fname == "shipments.json":
        return _s(rec.get("shipment_id"))
    return _s(rec.get("company_id"))


def merge_all(fresh_files, store_dir):
    """Merge every entity file. Raises RuntimeError if it cannot do so safely.

    fresh_files: {"invoices.json": [...], ...} straight from normalize.run
    """
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
                       "refreshed, only new rows were added")
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
                out.append(prior)              # untouched; refresh nothing
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
    if report["kept"]:
        L.append(f"\nKEPT {len(report['kept'])} record(s) the workbook no longer "
                 f"lists. Nothing was deleted -- review these:")
        for k in report["kept"][:40]:
            L.append(f"  {k['file']} {k['key']}  ({k['why']})")
        if len(report["kept"]) > 40:
            L.append(f"  ... and {len(report['kept']) - 40} more")
    return "\n".join(L)

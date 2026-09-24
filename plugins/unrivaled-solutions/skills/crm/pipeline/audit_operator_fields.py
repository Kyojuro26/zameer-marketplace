#!/usr/bin/env python3
"""
audit_operator_fields.py -- find operator-only fields a re-import wiped or
changed, by comparing the changelog's last recorded value against the store.

STRICTLY READ-ONLY. Every store file is opened 'r'; nothing constructs the
server's Store. A report file, if asked for with --out, is refused when it
resolves inside the store.

Background
----------
Before 0.1.43, merge.py's refresh path kept a field the importer never
produces (a follow-up date, a quote date, a due-date override, a company note)
ONLY while that edit's changelog line existed, and Store.log swallows OSError,
so an edit could land without its line. The next import then deleted the field.
merge.OPERATOR_ONLY now carries those fields regardless. That fix protects the
FUTURE; it does not restore anything already lost. This script lists what the
changelog says the operator set that the store no longer holds.

What it compares
----------------
For every field in merge.OPERATOR_ONLY (read from merge.py, one definition),
the value in the LAST changelog entry that set it -- an `update` or a `create`
-- per record, following project and invoice renames in log order, exactly as
merge.load_operator_edits does. A record is listed when the store's field is
missing or holds a different value. A recorded null counts as a value (the
operator cleared the field); a missing field against a recorded null does not,
since both read as empty.

Coverage -- read before trusting a clean result
------------------------------------------------
It can only see edits whose line exists. An edit whose line was never written
(the OSError case itself) is invisible here as it was to merge. Records it
cannot place are listed separately, never silently dropped: `unmatched` (no
store record under that key -- the record was renamed without a logged rename,
or the key is not in the store) and `ambiguous` (more than one record answers
to the key, e.g. two customers' 4521 logged before 0.1.41 without a company).

Usage
-----
    python3 audit_operator_fields.py --store <store dir> [--out report.txt] [--json]
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _sibling_merge():
    """merge.py beside this file, by path: `import merge` would take whatever
    module of that name is already loaded, which need not be this one's."""
    spec = importlib.util.spec_from_file_location("_audit_operator_merge",
                                                  os.path.join(HERE, "merge.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


OPERATOR_ONLY = _sibling_merge().OPERATOR_ONLY   # the one definition

STORE_MARKERS = ("companies.json", "projects.json", "invoices.json")
FILE_OF = {"project": "projects.json", "shipment": "shipments.json",
           "invoice": "invoices.json", "company": "companies.json",
           "vendor": "vendors.json"}
MISSING = object()


def st(v):
    return "" if v is None else str(v).strip()


def idkey(v):
    """The identifier as Store.log writes it (server._key / merge._idkey)."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def load(store, name, required):
    """Read one store file, 'r' only. FATALs on a missing required file rather
    than report 'clean' against the wrong directory."""
    path = os.path.join(store, name)
    if not os.path.exists(path):
        if required:
            sys.exit(f"FATAL: {name} not found in {store}. Refusing to report "
                     f"a clean result from an incomplete store.")
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"FATAL: {name} is not valid JSON ({e}).")
    if not isinstance(data, list):
        sys.exit(f"FATAL: {name} is {type(data).__name__}, expected a list.")
    return data


def load_changelog(store):
    """{(entity, key, company_id or None, field): (value, ts)} -- the LAST value
    each operator-only field was set to, keys moved through renames in order."""
    last = {}
    path = os.path.join(store, "changelog.jsonl")
    if not os.path.exists(path):
        return last
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
            ent, key, op, fields = e.get("entity"), st(e.get("key")), e.get("op"), e.get("fields")
            if ent not in FILE_OF or not key or not isinstance(fields, dict):
                continue
            if op == "rename":
                new = _renamed(ent, key, fields)
                if new and new != key:
                    for k in [k for k in last if k[0] == ent and k[1] == key]:
                        last[(ent, new) + k[2:]] = last.pop(k)
                continue
            if op not in ("update", "create"):
                continue
            cid = e.get("company_id") if ent == "project" else None
            for field in set(fields) & OPERATOR_ONLY.get(FILE_OF[ent], set()):
                last[(ent, key, cid, field)] = (fields[field], e.get("ts"))
    return last


def _renamed(ent, key, fields):
    if ent == "project":
        return st(fields.get("new_project_no")) or None
    if ent == "invoice":
        new_no = st(fields.get("new_invoice_no"))
        cid = key.rsplit(":", 1)[0] if ":" in key else ""
        return f"{cid}:{new_no}" if new_no and cid else None
    return None


def _matches(ent, rec, key, cid):
    if ent == "project":
        return idkey(rec.get("project_no")) == key and (cid is None or rec.get("company_id") == cid)
    if ent == "invoice":
        return f"{st(rec.get('company_id'))}:{idkey(rec.get('invoice_no'))}" == key
    if ent == "shipment":
        return idkey(rec.get("shipment_id")) == key
    return st(rec.get("company_id")) == key


def audit(store):
    records = {f: load(store, f, f in STORE_MARKERS) for f in set(FILE_OF.values())}
    last = load_changelog(store)
    findings, unmatched, ambiguous = [], [], []
    for (ent, key, cid, field), (value, ts) in sorted(last.items(), key=lambda kv: str(kv[0])):
        hits = [r for r in records[FILE_OF[ent]] if isinstance(r, dict) and _matches(ent, r, key, cid)]
        where = {"entity": ent, "key": key, "company_id": cid, "field": field}
        if not hits:
            unmatched.append(where)
            continue
        if len(hits) > 1:
            ambiguous.append(dict(where, count=len(hits)))
            continue
        stored = hits[0].get(field, MISSING)
        if (stored is MISSING and value is not None) or (stored is not MISSING and stored != value):
            findings.append(dict(where, changelog_value=value,
                                 stored_value="<missing>" if stored is MISSING else stored,
                                 changelog_ts=ts))
    return {"findings": findings, "unmatched": unmatched, "ambiguous": ambiguous,
            "fields_checked": len(last)}


def render(res, store):
    L = [f"Operator-only field audit -- {store}",
         f"{res['fields_checked']} recorded (record, field) values compared.", ""]
    L.append(f"DIFFERS FROM THE CHANGELOG: {len(res['findings'])}")
    for f in res["findings"]:
        who = f["key"] + (f" ({f['company_id']})" if f["company_id"] else "")
        L.append(f"  {f['entity']} {who} {f['field']}: changelog {json.dumps(f['changelog_value'])}"
                 f" at {f['changelog_ts']}; store {json.dumps(f['stored_value'])}")
    for title, rows in (("NO STORE RECORD UNDER THAT KEY", res["unmatched"]),
                        ("MORE THAN ONE RECORD ANSWERS TO THE KEY", res["ambiguous"])):
        L.append(f"{title}: {len(rows)}")
        for f in rows:
            L.append(f"  {f['entity']} {f['key']} {f['field']}")
    L += ["", "Read-only: no store file was modified. Nothing was restored; each "
          "line is for a person to review."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="CRM store directory")
    ap.add_argument("--out", help="report path (must be OUTSIDE the store)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args()
    store = os.path.realpath(a.store)
    if not os.path.isdir(store):
        sys.exit(f"FATAL: no such store directory: {store}")
    if not any(os.path.exists(os.path.join(store, m)) for m in STORE_MARKERS):
        sys.exit(f"FATAL: {store} has none of {', '.join(STORE_MARKERS)}. "
                 f"This does not look like a CRM store.")
    if a.out:
        out = os.path.realpath(a.out)
        try:
            inside = os.path.commonpath([out, store]) == store
        except ValueError:
            inside = False
        if inside:
            sys.exit("FATAL: --out resolves inside the store. This audit never "
                     "writes into a live store. Choose a path outside it.")
    res = audit(store)
    text = json.dumps(res, indent=2, default=str) if a.json else render(res, store)
    if a.out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()

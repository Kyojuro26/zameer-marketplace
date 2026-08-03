#!/usr/bin/env python3
"""audit_qualified_paid.py -- find receivables the importer wrongly marked PAID.

STRICTLY READ-ONLY. Every store file is opened 'r'. Nothing is written unless
--out is given, and --out is refused if it resolves inside the store.

Why this exists
---------------
Until v0.1.28, pipeline/normalize.py decided "was this paid?" with a bare
`\\bpaid\\b` applied to a blob that includes the free-text collection-notes
column. That reads:

    "NOT PAID as of 7/1 - chasing"   -> paid
    "will be paid net 60"            -> paid
    "50% paid, balance due"          -> paid
    "Never paid - write off"         -> paid

with no needs_review entry, and the value was then back-filled onto the
project's collection_status. The regex was identical in v0.1.23 through
v0.1.26, so any store migrated by those versions can hold receivables recorded
as collected that were never collected. Fixing the importer does not repair
records already written -- this finds them.

It is deliberately NOT part of audit_commission_pct.py: that script replays the
old importer to reconstruct its decisions, and it must keep the old regex to do
so. This one asks a different question -- does the evidence still on the record
actually support the stored status?

Usage
-----
    python3 pipeline/audit_qualified_paid.py --store /path/to/store
    python3 pipeline/audit_qualified_paid.py --store /path/to/store --out report.md

Exit code: 0 when nothing is found, 1 when something needs a person.
"""
import argparse
import json
import os
import re
import sys

PAID_RE = re.compile(r"\bpaid\b", re.IGNORECASE)
# kept in step with normalize.py's PAID_QUALIFIER_RE
PAID_QUALIFIER_RE = re.compile(
    r"\b(?:not|never|non|no|isn'?t|wasn'?t|aren'?t|won'?t|"
    r"will|shall|should|would|expect(?:ed|ing|s)?|due|pending|awaiting|chas(?:e|ing)|"
    r"partial(?:ly)?|part|half|balance|remaining|outstanding|short|"
    r"if|unless|when|once|after|before|upon|assuming|"
    r"to\s+be|yet\s+to|going\s+to|supposed\s+to)\b", re.IGNORECASE)


def st(v):
    return "" if v is None else str(v)


def qualified(text):
    """A paid-ish word that is negated or conditioned by nearby wording."""
    t = st(text)
    return bool(PAID_RE.search(t)) and bool(PAID_QUALIFIER_RE.search(t))


def load(store, name, required=True):
    path = os.path.join(store, name)
    if not os.path.exists(path):
        if required:
            sys.exit(f"FATAL: {name} not found in {store}. Refusing to report a "
                     f"clean result from an incomplete store.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"FATAL: {name} is not valid JSON ({e}).")
    if not isinstance(data, list):
        sys.exit(f"FATAL: {name} is {type(data).__name__}, expected a list.")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--out", default=None, help="write a markdown report here")
    args = ap.parse_args()
    store = os.path.abspath(args.store)
    if args.out and os.path.abspath(args.out).startswith(store + os.sep):
        sys.exit("FATAL: --out resolves inside the store. Refusing to write there.")

    invoices = load(store, "invoices.json")
    projects = load(store, "projects.json")
    findings = []

    for inv in invoices:
        if not isinstance(inv, dict):
            continue
        blob = f"{st(inv.get('payment_status_raw'))} {st(inv.get('payment_notes'))}"
        stored = st(inv.get("payment_status")).strip().lower()
        if stored.startswith("paid") and qualified(blob):
            findings.append({
                "kind": "invoice",
                "company_id": st(inv.get("company_id")),
                "invoice_no": st(inv.get("invoice_no")),
                "stored": stored,
                "evidence": blob.strip(),
                "sheet_row": inv.get("sheet_row"),
            })

    for p in projects:
        if not isinstance(p, dict):
            continue
        stored = st(p.get("collection_status")).strip().lower()
        # the project's own notes are the only evidence back-filled onto it
        blob = f"{st(p.get('notes'))} {st(p.get('payment_notes'))}"
        if stored.startswith("paid") and qualified(blob):
            findings.append({
                "kind": "project",
                "project_no": st(p.get("project_no")),
                "company_id": st(p.get("company_id")),
                "stored": stored,
                "evidence": blob.strip(),
            })

    L = ["# Receivables recorded as PAID on qualified evidence", ""]
    if not findings:
        L += ["**Nothing found.** No record stores a paid status whose own "
              "evidence text is negated or conditional.", "",
              "This checks the evidence still on each record. An invoice whose "
              "`payment_notes` were tidied up after import no longer carries "
              "the original wording, so a clean result here is not proof that "
              "no record was ever mis-imported -- it is proof that none of the "
              "surviving evidence contradicts its stored status."]
    else:
        L += [f"**{len(findings)} record(s) need a person.** Each stores a PAID "
              f"status while its own evidence text says otherwise. Check each "
              f"against the source workbook before changing anything.", ""]
        for f in findings:
            if f["kind"] == "invoice":
                L.append(f"- invoice **{f['invoice_no']}** ({f['company_id']}) "
                         f"stored `{f['stored']}`"
                         + (f", tracker row {f['sheet_row']}" if f["sheet_row"] else ""))
            else:
                L.append(f"- project **{f['project_no']}** ({f['company_id']}) "
                         f"stored `{f['stored']}`")
            L.append(f"  - evidence on the record: `{f['evidence']}`")
            L.append(f"  - if it is genuinely unpaid: "
                     f"`update_invoice(company_id=\"{f.get('company_id','')}\", "
                     f"invoice_no=\"{f.get('invoice_no','')}\", "
                     f"fields={{\"payment_status\": \"open\"}})`"
                     if f["kind"] == "invoice" else
                     f"  - if it is genuinely unpaid: "
                     f"`update_project(project_no=\"{f.get('project_no','')}\", "
                     f"fields={{\"collection_status\": \"open\"}})`")
            L.append("")
    report = "\n".join(L)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)
    print(f"\nFOUND {len(findings)}" if findings else "\nCLEAN")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

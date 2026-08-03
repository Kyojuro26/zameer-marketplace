#!/usr/bin/env python3
"""readiness_check.py -- can this store be trusted as the source of truth?

STRICTLY READ-ONLY. Every file is opened 'r'. Nothing is written anywhere
unless you pass --out, and --out is refused if it resolves inside the store.
Safe to run on the live store at any time, including while the CRM is open.

Why this exists
---------------
Every other check in this project runs against synthetic fixtures. This one
runs against the REAL store and answers the only question that matters before
the workbook is retired: what is actually in here, and is any of it beyond the
CRM's reach or quietly wrong?

It reports three different kinds of problem, and the difference matters:

  FROZEN    the record exists and is visible, but no tool can edit it. Its
            revenue still counts in totals. Left alone it is a permanent hole
            in a system that is supposed to be authoritative.
  WRONG     the record is editable and looks fine, but the stored value
            contradicts its own evidence. Nobody will notice. This is the
            dangerous category.
  FRAGILE   works today, will bite later -- unparseable dates, missing links.

Usage
-----
    python3 readiness_check.py --store "C:\\path\\to\\store"
    python3 readiness_check.py --store /path/to/store --out report.md

Exit: 0 nothing found, 1 findings need attention, 2 the store cannot be read.

The report names invoice numbers, customers and amounts. Keep it local -- do
not paste it anywhere public.
"""
import argparse
import json
import os
import re
import sys

ENTITY_FILES = ["companies.json", "contacts.json", "projects.json",
                "shipments.json", "invoices.json", "vendors.json",
                "needs_review.json"]

# Keys that exist on Object.prototype -- the visual app indexes companies into
# a plain JS object, so one of these as a company_id stops the app rendering.
JS_RESERVED = {"__proto__", "constructor", "prototype", "tostring", "valueof",
               "hasownproperty", "isprototypeof", "propertyisenumerable",
               "tolocalestring"}


def _load_payment_words():
    """The importer's own payment wording, so this agrees with what decided."""
    p = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                     "payment_words.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("crm_payment_words", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:                                 # noqa: BLE001
        return None


_PW = _load_payment_words()

# Deliberately BROADER than the importer's rule -- this is an audit, so its
# errors must point at "look at this" rather than "nothing to see". Mirrors
# audit_qualified_paid.SUSPECT_RE.
SUSPECT_RE = re.compile(
    r"\b(?:not|never|non|un|isn'?t|wasn'?t|hasn'?t|haven'?t|didn'?t|won'?t|"
    r"will|shall|should|would|expect|promis|pending|awaiting|chas|"
    r"partial|part|half|deposit|instal?lment|1st|2nd|first|balance|remain|"
    r"outstanding|short|less|rest|owe|owes|owed|owing|still|open|"
    r"bounce|nsf|return|revers|charge|void|cancel|refund|insufficient|"
    r"disput|confirm|verify|unclear|unsure|claim|"
    r"if|unless|once|when|upon|c\.?o\.?d\.?|delivery|"
    r"vendor|supplier|freight|carrier)\b"
    r"|\?|\d{1,3}\s*%|\$?[\d,]+(?:\.\d\d)?\s+of\s+", re.IGNORECASE)

DATE_OK = re.compile(r"^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})")


def st(v):
    return "" if v is None else str(v)


def key_of(v):
    """The comparison form the tools use (server._key): de-floats and strips.
    Reimplemented here, deliberately, so this script needs nothing but the
    standard library and cannot be broken by importing the server."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def canon_of(v):
    """What a caller typing this identifier would arrive with (server._canon)."""
    k = key_of(v)
    return k[:-2] if k.endswith(".0") and k[:-2].lstrip("-").isdigit() else k


class Report:
    def __init__(self):
        self.frozen, self.wrong, self.fragile, self.notes = [], [], [], []

    def add(self, bucket, title, detail, examples=None):
        bucket.append({"title": title, "detail": detail,
                       "examples": examples or []})


def read_store(store):
    data, problems = {}, []
    for f in ENTITY_FILES:
        p = os.path.join(store, f)
        if not os.path.exists(p):
            problems.append(f"{f} is MISSING")
            data[f] = []
            continue
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                v = json.load(fh)
            data[f] = v if isinstance(v, list) else []
            if not isinstance(v, list):
                problems.append(f"{f} is a {type(v).__name__}, expected a list")
        except (OSError, ValueError) as e:
            problems.append(f"{f} could not be read ({e})")
            data[f] = []
    return data, problems


def check(store, data, r):
    projects = data["projects.json"]
    invoices = data["invoices.json"]
    shipments = data["shipments.json"]
    contacts = data["contacts.json"]
    companies = data["companies.json"]

    # ---------------------------------------------------------------- FROZEN
    pk = {}
    for p in projects:
        if isinstance(p, dict):
            pk.setdefault(key_of(p.get("project_no")), []).append(p)

    blank = pk.get("", [])
    if blank:
        r.add(r.frozen, f"{len(blank)} project(s) have no project number",
              "Visible in the app and their revenue counts in the totals, but "
              "no tool can open, edit, renumber, delete or archive them -- "
              "every lookup needs a number. The importer writes these for a "
              "deal row that has revenue but no project number.",
              [f"{st(p.get('description')) or '(no description)'} "
               f"-- {st(p.get('company_name')) or st(p.get('company_id'))}, "
               f"revenue {p.get('revenue')}" for p in blank[:10]])

    dupes = {k: v for k, v in pk.items() if k and len(v) > 1}
    if dupes:
        r.add(r.frozen, f"{len(dupes)} project number(s) used more than once",
              "The tools refuse to act on a duplicated number because they "
              "cannot tell which record you mean, so these are uneditable "
              "until the duplicate is resolved. There is no in-app repair for "
              "projects (there is one for shipments).",
              [f"project {k}: {len(v)} records "
               f"({sum(1 for x in v if x.get('archived'))} archived)"
               for k, v in list(dupes.items())[:10]])

    unreachable = [p for p in projects if isinstance(p, dict)
                   and key_of(p.get("project_no"))
                   and key_of(p.get("project_no")) != canon_of(p.get("project_no"))]
    if unreachable:
        r.add(r.frozen, f"{len(unreachable)} project number(s) nobody can type",
              "Stored in a form (a trailing .0) that no typed lookup matches. "
              "They can still be opened by clicking through the app, and "
              "renaming one to its plain number fixes it permanently.",
              [f"stored {p.get('project_no')!r} -- you would type "
               f"{canon_of(p.get('project_no'))!r}" for p in unreachable[:10]])

    sk = {}
    for s in shipments:
        if isinstance(s, dict):
            sk.setdefault(key_of(s.get("shipment_id")), []).append(s)
    sdupes = {k: v for k, v in sk.items() if len(v) > 1}
    if sdupes:
        r.add(r.frozen, f"{len(sdupes)} shipment id(s) used by more than one leg",
              "Editing or moving these is refused, and the app opens whichever "
              "comes first. REPAIRABLE: ask Claude to "
              "'renumber duplicate shipments <id>' for each one below, then "
              "they become editable individually.",
              [f"{k}: {len(v)} legs (POs: "
               f"{[st(x.get('vendor_po_raw')) for x in v][:4]})"
               for k, v in list(sdupes.items())[:10]])

    # ----------------------------------------------------------------- WRONG
    paid_suspect = []
    for i in invoices:
        if not isinstance(i, dict):
            continue
        blob = f"{st(i.get('payment_status_raw'))} {st(i.get('payment_notes'))}"
        if st(i.get("payment_status")).strip().lower().startswith("paid") \
                and SUSPECT_RE.search(blob):
            paid_suspect.append((i, blob.strip()))
    if paid_suspect:
        r.add(r.wrong,
              f"{len(paid_suspect)} receivable(s) marked PAID whose own notes "
              f"say otherwise",
              "Until v0.1.28 the importer read any note containing 'paid' as "
              "paid -- including 'NOT PAID', 'will be paid' and '50% paid'. "
              "These are off the collections list. Check each against the "
              "workbook before changing anything; the wording is quoted so you "
              "can see what the sheet actually said.",
              [f"invoice {st(i.get('invoice_no'))} "
               f"({st(i.get('client_name')) or st(i.get('company_id'))})"
               + (f", tracker row {i.get('sheet_row')}" if i.get("sheet_row") else "")
               + f"  --  note reads: {blob!r}" for i, blob in paid_suspect[:20]])

    orphan_inv = [i for i in invoices if isinstance(i, dict)
                  and not st(i.get("company_id")).strip()]
    if orphan_inv:
        r.add(r.wrong,
              f"{len(orphan_inv)} invoice(s) are attached to no customer",
              "The app only shows invoices inside a customer page, so these are "
              "invisible everywhere -- they will not appear in any total the "
              "operator sees. Usually the client name in the sheet did not "
              "match a company.",
              [f"invoice {st(i.get('invoice_no'))} "
               f"-- client name in the sheet: "
               f"{st(i.get('client_name')) or '(blank)'}" for i in orphan_inv[:15]])

    live_ids = {st(c.get("company_id")) for c in companies
                if isinstance(c, dict) and not c.get("archived")}
    all_ids = {st(c.get("company_id")) for c in companies if isinstance(c, dict)}
    hidden = [i for i in invoices if isinstance(i, dict)
              and st(i.get("company_id"))
              and st(i.get("company_id")) in all_ids
              and st(i.get("company_id")) not in live_ids]
    if hidden:
        r.add(r.wrong,
              f"{len(hidden)} invoice(s) belong to a DELETED customer",
              "They are hidden from every list while the customer is archived. "
              "If any are still owed, restore the customer.",
              [f"invoice {st(i.get('invoice_no'))} -- customer "
               f"{st(i.get('company_id'))}" for i in hidden[:15]])

    bad_co = [c for c in companies if isinstance(c, dict)
              and st(c.get("company_id")).lower() in JS_RESERVED]
    if bad_co:
        r.add(r.wrong, f"{len(bad_co)} customer id(s) break the desktop app",
              "These collide with a JavaScript built-in name and stop the "
              "visual app rendering at all (the chat side is unaffected).",
              [st(c.get("company_id")) for c in bad_co])

    # --------------------------------------------------------------- FRAGILE
    bad_dates = []
    for i in invoices:
        if not isinstance(i, dict):
            continue
        d = i.get("invoice_date")
        if d not in (None, "") and not DATE_OK.match(st(d)):
            bad_dates.append(i)
    if bad_dates:
        r.add(r.fragile,
              f"{len(bad_dates)} invoice date(s) the CRM cannot read",
              "Kept exactly as the tracker had them (nothing is lost), but no "
              "due date can be computed, so these never appear as overdue. "
              "Retyping the date in the invoice drawer fixes each one.",
              [f"invoice {st(i.get('invoice_no'))} -- date stored as "
               f"{i.get('invoice_date')!r}" for i in bad_dates[:15]])

    ph = {}
    for c in contacts:
        if isinstance(c, dict) and st(c.get("email")).strip() == "?":
            ph.setdefault(st(c.get("company_id")), []).append(c)
    multi = {k: v for k, v in ph.items() if len(v) > 1}
    if multi:
        r.add(r.fragile,
              f"{sum(len(v) for v in multi.values())} contact(s) have no email "
              f"address",
              "The tracker left these blank and the importer stored a '?'. They "
              "work, but Outlook sync skips them and they cannot be matched by "
              "email. Adding real addresses is worth doing before relying on "
              "the contact list.",
              [f"{k}: {', '.join(st(x.get('name')) for x in v[:4])}"
               for k, v in list(multi.items())[:10]])

    strnum = [p for p in projects if isinstance(p, dict)
              and (isinstance(p.get("revenue"), str)
                   or isinstance(p.get("year"), str))]
    if strnum:
        r.add(r.fragile,
              f"{len(strnum)} project(s) store revenue or year as text",
              "Older versions could mis-total these on the dashboard. The "
              "current version handles it, but re-saving each project through "
              "the app normalises the value.",
              [f"project {st(p.get('project_no'))}: revenue={p.get('revenue')!r} "
               f"year={p.get('year')!r}" for p in strnum[:10]])

    if not os.path.exists(os.path.join(store, "changelog.jsonl")):
        r.add(r.fragile, "no changelog.jsonl in this store",
              "The CRM records every edit here, and a re-import uses it to know "
              "which values you have changed so it does not overwrite them. "
              "Without it a re-import can only ADD new rows -- it will not "
              "refresh anything already in the store.")

    # ------------------------------------------------------------------ info
    r.notes.append(f"{len(companies)} customers/vendors, {len(projects)} projects, "
                   f"{len(invoices)} invoices, {len(shipments)} shipment legs, "
                   f"{len(contacts)} contacts")
    owed = [i for i in invoices if isinstance(i, dict)
            and not st(i.get("payment_status")).lower().startswith("paid")]
    r.notes.append(f"{len(owed)} invoice(s) currently show as not fully paid")


def render(r, store):
    L = ["# CRM readiness check", "",
         f"Store: `{store}`", ""]
    L += ["  " + n for n in r.notes] + [""]
    total = len(r.frozen) + len(r.wrong) + len(r.fragile)
    if not total:
        L += ["**Nothing found.** Every record in this store is reachable by "
              "the tools, no stored payment status contradicts its own notes, "
              "and no dates are unreadable.", "",
              "That is not a guarantee the numbers are RIGHT -- it means "
              "nothing in the store is self-contradictory or out of reach. "
              "Spot-check a few receivables against the workbook before "
              "retiring it."]
        return "\n".join(L)

    def section(title, items, lead):
        if not items:
            return []
        out = [f"## {title}", "", lead, ""]
        for it in items:
            out.append(f"### {it['title']}")
            out.append("")
            out.append(it["detail"])
            if it["examples"]:
                out.append("")
                for e in it["examples"]:
                    out.append(f"  - {e}")
            out.append("")
        return out

    L += section("Frozen -- visible but not editable", r.frozen,
                 "These records show up in the CRM and count toward totals, but "
                 "no tool can change them. They need fixing before the CRM can "
                 "be the source of truth, because they are permanent holes.")
    L += section("Wrong -- editable, but the stored value is not the truth",
                 r.wrong,
                 "Nothing will error and nobody will notice. This is the "
                 "category that matters most when retiring the workbook.")
    L += section("Fragile -- works now, worth cleaning up", r.fragile,
                 "None of these block anything today.")
    L += ["---", "",
          "This report is read-only; nothing in the store was changed. It names "
          "customers, invoice numbers and amounts, so keep it local."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", required=True)
    ap.add_argument("--out", default=None, help="write the report to a file")
    a = ap.parse_args()
    store = os.path.abspath(a.store)
    if not os.path.isdir(store):
        print(f"FATAL: no such folder: {store}", file=sys.stderr)
        return 2
    if a.out and os.path.abspath(a.out).startswith(store + os.sep):
        print("FATAL: --out is inside the store. Refusing to write there.",
              file=sys.stderr)
        return 2

    data, problems = read_store(store)
    if problems:
        print("FATAL: this store could not be read completely:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Refusing to report on an incomplete store -- a clean result "
              "here would be meaningless.", file=sys.stderr)
        return 2

    r = Report()
    check(store, data, r)
    report = render(r, store)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {a.out}")
    else:
        print(report)
    found = len(r.frozen) + len(r.wrong) + len(r.fragile)
    print(f"\n{'FINDINGS: ' + str(found) if found else 'CLEAN'}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

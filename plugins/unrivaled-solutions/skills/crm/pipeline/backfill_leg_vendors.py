#!/usr/bin/env python3
"""Report which vendor each shipment leg's PO text names, by the one rule in
vendor_match.py -- and, on --apply, write exactly those.

    python3 pipeline/backfill_leg_vendors.py --store <dir>            # report
    python3 pipeline/backfill_leg_vendors.py --store <dir> --apply    # write

REPORT MODE (the default) writes nothing. For every leg without a vendor_id
it prints the token the PO carries and the vendor it matches (exactly, or
through vendor_aliases.json) or UNMATCHED; then a table of the unmatched
tokens by count -- the list an operator answers, by adding lines to
vendor_aliases.json ({"fs": "fs-racking"}) or by fixing a vendor's name --
and the before/after counts a write would produce.

--apply, under the store's own write lock, sets vendor_id ONLY where the
match is exact or aliased -- never a guess, never a token, never a vendor
whose company is archived -- writes one changelog entry per leg so a
re-import preserves the vendor through merge's touched rule, and prints the
before/after counts. A leg that already carries a vendor_id is never touched
by either mode: nothing here second-guesses a vendor already on file. Run
twice, the second run finds nothing to do.
"""
import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vendor_match import load_aliases, match_vendor, vendor_index, vendor_token  # noqa: E402

INTERFACE_VERSION = "0.1"


def _read(store, name, problems=None):
    """A store file as a list, or [] -- and a file that is present but cannot
    be read is NAMED in `problems` rather than raised: a traceback tells the
    operator nothing about which file, and a silent [] would report a store
    of no legs."""
    p = os.path.join(store, name)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        if problems is not None:
            problems.append(f"{name} could not be read ({e}); treated as empty")
        return []
    if not isinstance(data, list):
        if problems is not None:
            problems.append(f"{name} is not a list of records; treated as empty")
        return []
    return data


def _archived_company_ids(store, problems=None):
    return {c.get("company_id") for c in _read(store, "companies.json", problems)
            if isinstance(c, dict) and c.get("archived") and c.get("company_id")}


def plan(store):
    """Every leg without a vendor_id, with the token it carries and what the
    rule makes of it. Pure: reads the store, writes nothing. Each row keeps
    the leg's POSITION in shipments.json, so two legs sharing a shipment_id
    are never confused with each other on a write."""
    problems = []
    shipments = _read(store, "shipments.json", problems)
    vendors = _read(store, "vendors.json", problems)
    aliases = load_aliases(store, problems)
    archived = _archived_company_ids(store, problems)
    idx = vendor_index(vendors)
    rows = []
    for i, s in enumerate(shipments):
        if not isinstance(s, dict):
            continue
        if s.get("vendor_id"):
            continue                       # never second-guessed
        token = vendor_token(s.get("vendor_po_raw"))
        vid, how = match_vendor(token, vendors, aliases, idx, archived)
        rows.append({"i": i, "shipment_id": s.get("shipment_id"), "po": s.get("vendor_po_raw"),
                     "token": token, "vendor_id": vid, "how": how})
    return {"legs": len([s for s in shipments if isinstance(s, dict)]),
            "with_vendor": len([s for s in shipments
                                if isinstance(s, dict) and s.get("vendor_id")]),
            "rows": rows, "problems": problems}


VERDICT = {"no_token": "NO TOKEN", "unmatched": "UNMATCHED",
           "ambiguous": "AMBIGUOUS (two vendors share this name)",
           "alias_unknown": "ALIAS NAMES NO VENDOR",
           "vendor_archived": "VENDOR IS ARCHIVED"}


def format_report(p):
    L = []
    rows = p["rows"]
    for msg in p.get("problems", []):
        L.append(f"WARNING: {msg}")
    L.append(f"{p['legs']} legs; {p['with_vendor']} already carry a vendor_id "
             f"(left alone); {len(rows)} without one.\n")
    for r in rows:
        tok = r["token"] if r["token"] is not None else "(no parenthetical)"
        verdict = f"-> {r['vendor_id']}  [{r['how']}]" if r["vendor_id"] else VERDICT[r["how"]]
        L.append(f"  {str(r['shipment_id']):<14} {tok:<28} {verdict}")
    unmatched = collections.Counter(r["token"] for r in rows
                                    if r["vendor_id"] is None and r["token"] is not None)
    L.append("")
    if unmatched:
        L.append("UNMATCHED TOKENS (count, token, example PO) -- answer these in "
                 "vendor_aliases.json as {\"token\": \"<vendor company_id>\"}:")
        example = {}
        for r in rows:
            if r["vendor_id"] is None and r["token"] is not None:
                example.setdefault(r["token"], r["po"])
        for tok, n in unmatched.most_common():
            L.append(f"  {n:>4}  {tok:<28} e.g. {example[tok]}")
    else:
        L.append("No unmatched tokens.")
    matched = sum(1 for r in rows if r["vendor_id"])
    exact = sum(1 for r in rows if r["how"] == "exact")
    alias = sum(1 for r in rows if r["how"] == "alias")
    no_token = sum(1 for r in rows if r["how"] == "no_token")
    L.append("")
    L.append(f"Would set vendor_id on {matched} leg(s) ({exact} exact, {alias} by alias); "
             f"{len(rows) - matched} left as they are ({no_token} with no token, "
             f"{len(rows) - matched - no_token} unmatched or ambiguous).")
    L.append(f"vendor_id on legs: {p['with_vendor']} of {p['legs']} now -> "
             f"{p['with_vendor'] + matched} of {p['legs']} after a write.")
    return "\n".join(L)


def _store_lock(store):
    """The store's own write lock, through normalize's loader (which takes it
    without constructing a Store). Without the lock an edit made in the app
    between our read and our write would be discarded with no error."""
    try:
        from normalize import _store_write_lock
        return _store_write_lock(store)
    except Exception as e:                                          # noqa: BLE001
        import contextlib
        print(f"WARNING: could not take the store lock ({e}); close the CRM "
              f"before applying.", file=sys.stderr)
        return contextlib.nullcontext()


def apply(store):
    """Write vendor_id where the match is exact or aliased; nothing else.
    Re-plans under the lock so the rows describe the file as it is written.
    Returns (legs written, before, after)."""
    with _store_lock(store):
        p = plan(store)
        clog = os.path.join(store, "changelog.jsonl")
        if os.path.exists(clog) and not os.path.isfile(clog):
            # refused BEFORE anything is written: a write that lands and a
            # log that then raises leaves the store changed and unlogged
            return {"written": 0, "before": p["with_vendor"], "after": p["with_vendor"],
                    "legs": p["legs"], "logged": False,
                    "refused": "changelog.jsonl is not a file; nothing written"}
        shipments = _read(store, "shipments.json")
        entries, written = [], 0
        for r in p["rows"]:
            if not r["vendor_id"]:
                continue
            s = shipments[r["i"]]
            if s.get("vendor_id"):
                continue                       # never overwritten, whatever the plan said
            s["vendor_id"] = r["vendor_id"]
            written += 1
            entries.append({"ts": datetime.now(timezone.utc).isoformat(),
                            "op": "update", "entity": "shipment",
                            "key": str(s.get("shipment_id")),
                            "fields": {"vendor_id": r["vendor_id"]},
                            "interface_version": INTERFACE_VERSION,
                            "source": f"backfill_leg_vendors:{r['how']}"})
        logged = False
        if written:
            target = os.path.join(store, "shipments.json")
            tmp = target + ".backfill.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(shipments, f, indent=2, ensure_ascii=False)
            os.replace(tmp, target)
            # The changelog is appended to, never CREATED. merge.py reads the
            # file's mere presence as "every operator edit is logged" and
            # switches from add-only to full refresh; a store without one had
            # its un-logged edits protected by that absence, and one backfill
            # run must not take that protection away. Without a changelog the
            # add-only path keeps every record untouched, vendor included.
            if os.path.exists(clog):
                with open(clog, "a", encoding="utf-8") as f:
                    for e in entries:
                        f.write(json.dumps(e, default=str) + "\n")
                logged = True
        return {"written": written, "before": p["with_vendor"],
                "after": p["with_vendor"] + written, "legs": p["legs"], "logged": logged,
                "refused": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", required=True, help="store directory")
    ap.add_argument("--apply", action="store_true",
                    help="write vendor_id where the match is exact or aliased; never a guess")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.store):
        print(f"not a directory: {args.store}", file=sys.stderr)
        return 2
    print(format_report(plan(args.store)))
    if not args.apply:
        print("Report mode: nothing was written.")
        return 0
    a = apply(args.store)
    if a["refused"]:
        print(f"REFUSED: {a['refused']}")
        return 1
    written, before, after, legs, logged = a["written"], a["before"], a["after"], a["legs"], a["logged"]
    n_log = written if logged else 0
    print(f"APPLIED: vendor_id set on {written} leg(s); {before} of {legs} -> {after} of {legs} "
          f"legs carry a vendor_id. {n_log} changelog entr{'y' if n_log == 1 else 'ies'} written."
          + ("" if logged or not written else
             " No changelog.jsonl on this store, so none was created: a re-import stays "
             "add-only and keeps every record, vendor included."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

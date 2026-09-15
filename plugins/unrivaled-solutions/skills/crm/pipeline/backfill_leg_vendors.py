#!/usr/bin/env python3
"""Report which vendor each shipment leg's PO text names, by the one rule in
vendor_match.py -- and which tokens name no vendor record.

    python3 pipeline/backfill_leg_vendors.py --store <dir>

REPORT MODE ONLY. Nothing is written. For every leg without a vendor_id it
prints the token the PO carries and the vendor it matches (exactly, or through
vendor_aliases.json) or UNMATCHED; then a table of the unmatched tokens by
count -- the list an operator answers, by adding lines to vendor_aliases.json
({"fs": "fs-racking"}) or by fixing a vendor's name -- and the before/after
counts a write would produce. A leg that already carries a vendor_id is left
out entirely: nothing here ever second-guesses a vendor already on file.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vendor_match import load_aliases, match_vendor, vendor_index, vendor_token  # noqa: E402


def _read(store, name):
    p = os.path.join(store, name)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def plan(store):
    """Every leg without a vendor_id, with the token it carries and what the
    rule makes of it. Pure: reads the store, writes nothing."""
    shipments = _read(store, "shipments.json")
    vendors = _read(store, "vendors.json")
    aliases = load_aliases(store)
    idx = vendor_index(vendors)
    rows = []
    for s in shipments:
        if not isinstance(s, dict):
            continue
        if s.get("vendor_id"):
            continue                       # never second-guessed
        token = vendor_token(s.get("vendor_po_raw"))
        vid, how = match_vendor(token, vendors, aliases, idx)
        rows.append({"shipment_id": s.get("shipment_id"), "po": s.get("vendor_po_raw"),
                     "token": token, "vendor_id": vid, "how": how})
    return {"legs": len([s for s in shipments if isinstance(s, dict)]),
            "with_vendor": len([s for s in shipments
                                if isinstance(s, dict) and s.get("vendor_id")]),
            "rows": rows}


def format_report(p):
    L = []
    rows = p["rows"]
    L.append(f"{p['legs']} legs; {p['with_vendor']} already carry a vendor_id "
             f"(left alone); {len(rows)} without one.\n")
    for r in rows:
        tok = r["token"] if r["token"] is not None else "(no parenthetical)"
        if r["vendor_id"]:
            verdict = f"-> {r['vendor_id']}  [{r['how']}]"
        else:
            verdict = {"no_token": "NO TOKEN", "unmatched": "UNMATCHED",
                       "ambiguous": "AMBIGUOUS (two vendors share this name)",
                       "alias_unknown": "ALIAS NAMES NO VENDOR"}[r["how"]]
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
    L.append("Report mode: nothing was written.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", required=True, help="store directory")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.store):
        print(f"not a directory: {args.store}", file=sys.stderr)
        return 2
    print(format_report(plan(args.store)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

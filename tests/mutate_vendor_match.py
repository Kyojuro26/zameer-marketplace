#!/usr/bin/env python3
"""Mutation-test tests/regression/test_vendor_match.py against
pipeline/vendor_match.py and pipeline/backfill_leg_vendors.py -- two passes.

The subject is one rule and its discipline: the LAST non-payment parenthetical
is the token, a match is exact on the normalised name or an alias the operator
wrote, and nothing else matches. Every mutant is the tempting shortcut: take
the first parenthetical, let "(PAID)" be a vendor, match on a prefix, pick
one of two colliding names, use an alias that names nobody, or list a leg
that already has its vendor.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_vendor_match.py"

RULE = [
 ("the first parenthetical is taken, not the last",
  "    return cands[-1] if cands else None", "    return cands[0] if cands else None"),
 ("(PAID) is a vendor",
  "    cands = [c for c in cands if c and not PAYMENT_RE.search(c)]",
  "    cands = [c for c in cands if c]"),
 ("a percentage note is a vendor",
  'PAYMENT_RE = re.compile(r"paid|%", re.IGNORECASE)',
  'PAYMENT_RE = re.compile(r"paid", re.IGNORECASE)'),
 ("a prefix of a vendor's name is a match",
  "    ids = idx.get(n)\n",
  "    ids = next((v for k, v in idx.items() if k.startswith(n)), None)\n"),
 ("a name two vendors share is matched to the first",
  '        return (ids[0], "exact") if len(ids) == 1 else (None, "ambiguous")',
  '        return (ids[0], "exact")'),
 ("an alias naming no vendor record is used anyway",
  '        return (target, "alias") if target in known else (None, "alias_unknown")',
  '        return (target, "alias")'),
 ("normalisation keeps punctuation, so Save-ty and SaveTy are two vendors",
  '    return re.sub(r"[^a-z0-9]", "", str(s).lower())',
  '    return str(s).lower().replace(" ", "")'),
 ("a numeric PO cell is stringified into a token",
  "    if po_raw is None or isinstance(po_raw, bool):\n        return None\n    s = str(po_raw)",
  "    if po_raw is None:\n        return None\n    s = str(po_raw) + ' (' + str(po_raw) + ')'"),
]

SCRIPT = [
 ("a leg that already carries a vendor_id is reported too",
  '        if s.get("vendor_id"):\n            continue                       # never second-guessed\n', ""),
 ("report mode writes the plan back to the store",
  "    print(format_report(plan(args.store)))\n",
  "    p = plan(args.store)\n"
  "    with open(os.path.join(args.store, 'shipments.json'), 'w') as f:\n"
  "        json.dump(p['rows'], f)\n"
  "    print(format_report(p))\n"),
]


def main():
    worst = 0
    for title, target, mutants in (("RULE -- pipeline/vendor_match.py", "pipeline/vendor_match.py", RULE),
                                   ("SCRIPT -- pipeline/backfill_leg_vendors.py",
                                    "pipeline/backfill_leg_vendors.py", SCRIPT)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, TEST, target, mutants))
    return worst


sys.exit(main())

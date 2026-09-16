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
  '        vid, how = (ids[0], "exact") if len(ids) == 1 else (None, "ambiguous")',
  '        vid, how = (ids[0], "exact")'),
 ("an alias naming no vendor record is used anyway",
  '            vid, how = (target, "alias") if target in known else (None, "alias_unknown")',
  '            vid, how = (target, "alias")'),
 ("normalisation keeps punctuation, so Save-ty and SaveTy are two vendors",
  '    return re.sub(r"[^a-z0-9]", "", str(s).lower())',
  '    return str(s).lower().replace(" ", "")'),
 ("a container holding a parenthetical is stringified into a token",
  "    if not isinstance(po_raw, str):\n        return None\n    s = po_raw",
  "    if po_raw is None or isinstance(po_raw, bool):\n        return None\n    s = str(po_raw)"),
 ("an archived vendor is matched anyway",
  '    if vid is not None and str(vid).strip() in arch:\n        return None, "vendor_archived"\n', ""),
 ("a BOM voids the alias file",
  '        with open(path, "r", encoding="utf-8-sig") as f:', '        with open(path, "r", encoding="utf-8") as f:'),
 ("an archived id is compared raw, so a padded one is not archived",
  '    arch = {str(a).strip() for a in (archived or ()) if a is not None}\n    if vid is not None and str(vid).strip() in arch:',
  '    arch = set(archived or ())\n    if vid is not None and vid in arch:'),
 ("two spellings of one token: the last silently wins",
  '    for nk in conflicts:\n        out.pop(nk, None)\n', '    for nk in ():\n        out.pop(nk, None)\n'),
 ("an unreadable alias file is silently empty",
  '        if problems is not None:\n            problems.append(f"{ALIASES_FILE} could not be read ({e}); no aliases applied")\n', ""),
]

SCRIPT = [
 ("a leg that already carries a vendor_id is reported too",
  '        if s.get("vendor_id"):\n            continue                       # never second-guessed\n', ""),
 # RETIRED, deliberately: "--apply overwrites a vendor already on the leg",
 # dropping apply()'s own `if s.get("vendor_id"): continue`. plan() is
 # re-computed under the same lock and never lists a leg that carries a
 # vendor, so apply's guard is a second line of defence with no reachable
 # effect of its own; the mutant survived, and that is the information. The
 # plan-side guard is graded above ("a leg that already carries a vendor_id is
 # reported too"), against a leg whose PO names an aliased vendor.
 ("--apply skips the changelog, so a re-import reverts every vendor it set",
  '                with open(clog, "a", encoding="utf-8") as f:\n'
  '                    for e in entries:\n'
  '                        f.write(json.dumps(e, default=str) + "\\n")\n', ""),
 ("--apply writes the token itself when nothing matched",
  '        for r in p["rows"]:\n            if not r["vendor_id"]:\n                continue\n',
  '        for r in p["rows"]:\n            if r["token"] is None:\n                continue\n'
  '            r = dict(r, vendor_id=r["vendor_id"] or r["token"])\n'),
 ("--apply writes a vendor whose company is archived",
  '        vid, how = match_vendor(token, vendors, aliases, idx, archived)',
  '        vid, how = match_vendor(token, vendors, aliases, idx)'),
 ("a store file that cannot be read is a traceback, not a warning",
  '    try:\n        with open(p, "r", encoding="utf-8") as f:\n            data = json.load(f)\n    except (OSError, ValueError) as e:\n        if problems is not None:\n            problems.append(f"{name} could not be read ({e}); treated as empty")\n        return []\n',
  '    with open(p, "r", encoding="utf-8") as f:\n        data = json.load(f)\n'),
 ("a changelog that is a directory is written past",
  '        if os.path.exists(clog) and not os.path.isfile(clog):\n', '        if False:\n'),
 ("--apply creates the changelog on a store that has none",
  "            if os.path.exists(clog):\n", "            if True:\n"),
 ("the alias warning is dropped from the report",
  '    for msg in p.get("problems", []):\n        L.append(f"WARNING: {msg}")\n', ""),
 ("report mode writes the plan back to the store",
  "    print(format_report(plan(args.store)))\n",
  "    p = plan(args.store)\n"
  "    with open(os.path.join(args.store, 'shipments.json'), 'w') as f:\n"
  "        json.dump(p['rows'], f)\n"
  "    print(format_report(p))\n"),
]


IMPORTER = [
 ("the importer writes no review entry for an unmatched token",
  '        if token is not None and vid is None and not _prior_vendor_by_sid.get(sid):\n'
  '            review.append({"type": "vendor_token_unmatched", "token": token, "why": how,\n'
  '                           "shipment_id": sid, "vendor_po_raw": po_val,\n'
  '                           "project_no": primary, "company_id": company_id})\n', ""),
 ("the importer files the leg under the token when nothing matched",
  '            "vendor_id": vid,\n', '            "vendor_id": vid or token,\n'),
 ("the importer ignores the operator's aliases",
  "    _aliases = _vm.load_aliases(str(outdir), _alias_problems)\n", "    _aliases = {}\n"),
 ("the importer ignores the store's archived vendors",
  "        vid, how = _vm.match_vendor(token, pool, _aliases, None, _archived_vendor_ids)",
  "        vid, how = _vm.match_vendor(token, pool, _aliases, None, set())"),
 ("the importer matches the sheet's vendors only",
  "        pool = list(vendors.values()) + _prior_vendors\n",
  "        pool = list(vendors.values())\n"),
 ("a store record the sheet also names is dropped from the pool, so a renamed vendor's name matches nowhere",
  "        pool = list(vendors.values()) + _prior_vendors\n",
  "        pool = list(vendors.values()) + [v for v in _prior_vendors if v.get(\"company_id\") not in vendors]\n"),
 ("a leg whose vendor is on file is reviewed again on every import",
  "        if token is not None and vid is None and not _prior_vendor_by_sid.get(sid):",
  "        if token is not None and vid is None:"),
 ("an unreadable alias file raises no review entry",
  '    for _msg in _alias_problems:\n        review.append({"type": "vendor_aliases_unreadable", "detail": _msg})\n', ""),
]

SERVER = [
 ("update_shipment accepts a vendor no record carries",
  '                      "shipment")\n            if fields.get("vendor_id") is not None:\n                fields["vendor_id"] = _require_vendor(fields["vendor_id"])\n',
  '                      "shipment")\n'),
 ("create_shipment accepts a vendor no record carries",
  '            _validate(fields, SHIPMENT_FIELDS, "shipment")\n            if fields.get("vendor_id") is not None:\n                fields["vendor_id"] = _require_vendor(fields["vendor_id"])\n',
  '            _validate(fields, SHIPMENT_FIELDS, "shipment")\n'),
 ("a padded vendor id is stored as given",
  '                fields["vendor_id"] = _require_vendor(fields["vendor_id"])\n            if "company_id" in fields:',
  '                _require_vendor(fields["vendor_id"])\n            if "company_id" in fields:'),
 ("a vendor at an archived company is accepted",
  '    if vid in {_key(c) for c in _archived_ids()}:\n'
  '        raise StoreError(f"vendor \'{vendor_id}\' is archived -- restore it first")\n', ""),
 ("list_shipments ignores vendor_id",
  '    if vendor_id:\n        out = [s for s in out if _key(s.get("vendor_id")) == _key(vendor_id)]\n', ""),
 ("get_vendor lists delivered legs as open",
  '                 and s.get("stage") not in ("Delivered", "Installed", "Cancelled")\n', ""),
]


def main():
    worst = 0
    for title, target, mutants in (("RULE -- pipeline/vendor_match.py", "pipeline/vendor_match.py", RULE),
                                   ("SCRIPT -- pipeline/backfill_leg_vendors.py",
                                    "pipeline/backfill_leg_vendors.py", SCRIPT),
                                   ("IMPORTER -- pipeline/normalize.py", "pipeline/normalize.py", IMPORTER),
                                   ("SERVER -- mcp/server.py", "mcp/server.py", SERVER)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, TEST, target, mutants))
    return worst


sys.exit(main())

"""The vendor a shipment leg's PO text names -- parsed by one rule, matched
exactly or by an operator-written alias, never guessed.

182 of 187 legs on the August sheet carry a vendor short name in parentheses
in vendor_po_raw -- "PO # 1252 (FS)", "PO # 1220 (Baihu Designs) (PAID)" --
spelled inconsistently ("J&L Wire" / "JnL" / "J and L Wire") and often
matching no vendor record by name. vendor_on_time read 0 of 213 because no
leg carried a vendor_id.

ONE rule, shared by the backfill script and the importer, so the two can
never disagree about which vendor a PO names:

  token   the LAST parenthetical in vendor_po_raw that is not a payment note
          (contains "paid" or "%"), trimmed. None when there is none.
  match   normalise (lowercase, non-alphanumerics stripped) and look the token
          up against vendors.json by normalised display_name EXACTLY; else in
          vendor_aliases.json, an operator-edited file of normalised token ->
          vendor company_id. No prefix match, no fuzzy match, no guess. A
          token with no match is REPORTED, never written; so is a token two
          vendors' names collapse onto, and an alias naming no vendor record.
"""
import json
import os
import re

PAREN_RE = re.compile(r"\(([^()]*)\)")
PAYMENT_RE = re.compile(r"paid|%", re.IGNORECASE)
ALIASES_FILE = "vendor_aliases.json"


def vendor_token(po_raw):
    """The vendor short name a PO string names, or None.

    The LAST parenthetical that is not a payment note: "(70% Paid)", "(PAID)"
    and "(Paid)" are skipped, an empty "( )" is skipped, and of two vendor-
    looking parentheticals the last wins. Anything that is not text -- None, a
    bool, a number the sheet stored -- names no vendor."""
    if po_raw is None or isinstance(po_raw, bool):
        return None
    s = str(po_raw)
    cands = [m.group(1).strip() for m in PAREN_RE.finditer(s)]
    cands = [c for c in cands if c and not PAYMENT_RE.search(c)]
    return cands[-1] if cands else None


def norm_token(s):
    """The comparison form of a vendor name or token: lowercase, letters and
    digits only. "Save-ty Yellow", "SaveTy Yellow" and "saveTy yellow" are one
    key; "J&L Wire" and "J and L Wire" are two, and stay two."""
    if s is None or isinstance(s, bool):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def load_aliases(store_dir):
    """vendor_aliases.json as {normalised token: vendor_id}. Keys are
    normalised on load so the operator may write "FS" or "fs" and mean the
    same thing. Absent file, or a file that is not an object: no aliases."""
    path = os.path.join(store_dir, ALIASES_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        nk = norm_token(k)
        if nk and isinstance(v, str) and v.strip():
            out[nk] = v.strip()
    return out


def vendor_index(vendors):
    """{normalised display_name: [company_id, ...]} -- a list, so a name two
    vendor records collapse onto is visible as ambiguous rather than picked."""
    idx = {}
    for v in vendors or []:
        if not isinstance(v, dict):
            continue
        k = norm_token(v.get("display_name"))
        cid = v.get("company_id")
        if k and isinstance(cid, str) and cid:
            idx.setdefault(k, [])
            if cid not in idx[k]:
                idx[k].append(cid)
    return idx


def match_vendor(token, vendors, aliases, index=None):
    """(vendor_id, how) for a token, or (None, why).

    how: "exact" (normalised display_name equals the normalised token) or
    "alias" (the operator's file names it). why: "no_token", "unmatched",
    "ambiguous" (two vendors' names normalise to the token), "alias_unknown"
    (the alias names a company_id no vendor record has). Exact wins over an
    alias; nothing else matches."""
    n = norm_token(token)
    if not n:
        return None, "no_token"
    idx = index if index is not None else vendor_index(vendors)
    ids = idx.get(n)
    if ids:
        return (ids[0], "exact") if len(ids) == 1 else (None, "ambiguous")
    target = (aliases or {}).get(n)
    if target:
        known = {cid for lst in idx.values() for cid in lst}
        return (target, "alias") if target in known else (None, "alias_unknown")
    return None, "unmatched"

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
    # text only: a list or a dict holding "(FS)" is not a PO, and str() of one
    # would hand its parenthetical to the rule as though it were
    if not isinstance(po_raw, str):
        return None
    s = po_raw
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


def load_aliases(store_dir, problems=None):
    """vendor_aliases.json as {normalised token: vendor_id}. Keys are
    normalised on load so the operator may write "FS" or "fs" and mean the
    same thing. An absent file is no aliases. A file that is PRESENT but
    cannot be read -- a JSON slip, or not an object -- is no aliases too,
    and is NAMED in `problems` when a list is given: read silently as empty
    it told the operator every answered token was still unmatched. Opened as
    utf-8-sig, so a BOM (Notepad's default) does not void the file."""
    path = os.path.join(store_dir, ALIASES_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        if problems is not None:
            problems.append(f"{ALIASES_FILE} could not be read ({e}); no aliases applied")
        return {}
    if not isinstance(raw, dict):
        if problems is not None:
            problems.append(f"{ALIASES_FILE} is not an object of token -> vendor id; "
                            f"no aliases applied")
        return {}
    out, conflicts = {}, set()
    for k, v in raw.items():
        nk = norm_token(k)
        if nk and isinstance(v, str) and v.strip():
            if nk in out and out[nk] != v.strip():
                conflicts.add(nk)       # two spellings of one token, two vendors
            out[nk] = v.strip()
    # a token the file answers twice, differently, is answered by NEITHER:
    # "the last wins" is a guess about which line the operator meant
    for nk in conflicts:
        out.pop(nk, None)
        if problems is not None:
            problems.append(f"{ALIASES_FILE}: two spellings of '{nk}' name different "
                            f"vendors; neither is used until one is removed")
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


def match_vendor(token, vendors, aliases, index=None, archived=()):
    """(vendor_id, how) for a token, or (None, why).

    how: "exact" (normalised display_name equals the normalised token) or
    "alias" (the operator's file names it). why: "no_token", "unmatched",
    "ambiguous" (two vendors' names normalise to the token), "alias_unknown"
    (the alias names a company_id no vendor record has), "vendor_archived"
    (the vendor's company is archived: the tools refuse it, so the rule does
    too, whichever caller asks). Exact wins over an alias; nothing else
    matches."""
    n = norm_token(token)
    if not n:
        return None, "no_token"
    idx = index if index is not None else vendor_index(vendors)
    ids = idx.get(n)
    vid, how = None, "unmatched"
    if ids:
        vid, how = (ids[0], "exact") if len(ids) == 1 else (None, "ambiguous")
    else:
        target = (aliases or {}).get(n)
        if target:
            known = {cid for lst in idx.values() for cid in lst}
            vid, how = (target, "alias") if target in known else (None, "alias_unknown")
    # compared as keys -- trimmed -- as the tools compare them
    arch = {str(a).strip() for a in (archived or ()) if a is not None}
    if vid is not None and str(vid).strip() in arch:
        return None, "vendor_archived"
    return vid, how

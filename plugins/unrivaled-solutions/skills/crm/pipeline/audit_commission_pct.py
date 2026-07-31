#!/usr/bin/env python3
"""
audit_commission_pct.py -- find records whose collection/payment status was
mis-imported from a COMMISSION percentage by pipeline/normalize.py BEFORE the
v0.1.23 COMMISSION_RE guard shipped.

STRICTLY READ-ONLY. Every store file is opened 'r'; the report is written to
--out, which is refused if it resolves inside the store.

Background
----------
Pre-0.1.23, normalize.py applied PCT_RE (r"(\\d{1,3})\\s*%") with no check for
whether the percentage was a commission / rep-split rate. "10% comm to D"
became a payment or collection status. v0.1.23 added COMMISSION_RE as a guard
in BOTH call sites. That fix only changes what a FUTURE re-migration produces;
it does not repair records already written. This script finds those.

THE TWO CALL SITES ARE NOT SYMMETRIC -- this matters
-----------------------------------------------------
  invoice loop      : paid -> "paid"; else pct -> "partial:N%"; else "open"
  parse_project_key : paid -> "paid"; else pct -> "paid" IF N >= 100
                      else "partial:N%"; else "open" if an INV number is
                      present; else None

So a project key cell reading "100% comm to D" was stored as **paid** -- a
mis-import in the most dangerous direction for a receivables review. Each site
is replayed with its own semantics below; do not collapse them.

Coverage -- read before trusting a clean result
------------------------------------------------
INVOICES: `payment_status_raw` and `payment_notes` are both persisted and are
exactly the blob the detector consumed, so the original decision is
reconstructable -- EXCEPT that `payment_notes` is user-editable
(INVOICE_EDITABLE_FIELDS). A note tidied after import can erase the evidence.
This script reads changelog.jsonl and reports any invoice whose payment_notes
were edited as UNVERIFIABLE rather than silently skipping it.

PROJECTS: the key cell is not a project field. It survives only in
needs_review.json entries of type "project_key", and only for rows that
already had a review reason (multi-project / non-numeric keys). Where the raw
cell is available the verdict is definitive; otherwise the project is reported
as UNVERIFIABLE with a confidence ranking, never silently cleared.

Verdicts
--------
  CORRECTION_NEEDED  the stored status came from a commission %, and still
                     equals what the old code produced. Nobody has fixed it.
  ALREADY_CHANGED    same origin, but the stored value has since diverged.
  FLAG_ONLY          commission mention where old and new agree. No data is
                     wrong; the record only lacks a needs_review entry.
  UNVERIFIABLE       cannot be settled from the store. Ranked high/low.
"""

import argparse
import json
import os
import re
import sys

# --- verbatim from pipeline/normalize.py @ 072ad2f (v0.1.24) -----------------
PCT_RE = re.compile(r"(\d{1,3})\s*%")
COMMISSION_RE = re.compile(r"\bcomm(?:ission)?\b", re.IGNORECASE)
PAID_RE = re.compile(r"\bpaid\b", re.IGNORECASE)
INV_RE = re.compile(r"INV[\s#-]*(\d+)", re.IGNORECASE)
LEADING_NUMS_RE = re.compile(r"^\s*(\d{2,6})(?:\s*(?:and|&|,|/)\s*(\d{2,6}))*")
ONE_NUM_RE = re.compile(r"\d{2,6}")

STORE_MARKERS = ("companies.json", "projects.json", "invoices.json")


def st(v):
    """Case-preserving string coercion. Identifier fields may be stored as JSON
    numbers in stores written before the v0.1.24 _coerce_text fix."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\.0$", "", str(v)) if isinstance(v, (int, float)) else str(v)


def load(store, name, required):
    """Read one store file. FATALs rather than returning [] for a missing
    required file -- a tool whose job is not missing records must never report
    'clean' because it was pointed at the wrong directory."""
    path = os.path.join(store, name)
    if not os.path.exists(path):
        if required:
            sys.exit(f"FATAL: {name} not found in {store}. Refusing to report "
                     f"a clean result from an incomplete store.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"FATAL: {name} is not valid JSON ({e}). Aborted rather "
                     f"than reporting a partial result as clean.")
    if not isinstance(data, list):
        sys.exit(f"FATAL: {name} is {type(data).__name__}, expected a list.")
    return data


def load_changelog(store):
    """Invoice keys whose payment_notes were edited after import, and whether
    the store shows any post-fix migration marker. Tolerates torn lines."""
    edited = set()
    path = os.path.join(store, "changelog.jsonl")
    if not os.path.exists(path):
        return edited
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue                       # torn tail line; skip, not fatal
            if not isinstance(e, dict):
                continue
            if e.get("entity") != "invoice":
                continue
            fields = e.get("fields")
            if isinstance(fields, dict) and "payment_notes" in fields:
                key = e.get("key")
                if isinstance(key, (list, tuple)):
                    edited.add(tuple(st(k) for k in key))
                else:
                    edited.add((st(key),))
    return edited


# --------------------------------------------------------------- replay: sites
def replay_invoice(blob):
    """Return (pre_fix, post_fix, commission_seen) for the invoice loop."""
    if PAID_RE.search(blob):
        return "paid", "paid", False
    if COMMISSION_RE.search(blob):
        pct = PCT_RE.search(blob)
        return (f"partial:{pct.group(1)}%" if pct else "open"), "open", True
    pct = PCT_RE.search(blob)
    v = f"partial:{pct.group(1)}%" if pct else "open"
    return v, v, False


def replay_project_key(s):
    """Return (pre_fix, post_fix, commission_seen) for parse_project_key.
    Note the n >= 100 -> 'paid' branch, which the invoice loop does NOT have,
    and the 'None unless an INV number is present' fallback."""
    if PAID_RE.search(s):
        return "paid", "paid", False
    inv = bool(INV_RE.search(s))
    pct = PCT_RE.search(s)
    if pct:
        n = int(pct.group(1))
        pre = "paid" if n >= 100 else f"partial:{n}%"
    elif inv:
        pre = "open"
    else:
        pre = None
    if COMMISSION_RE.search(s):
        return pre, ("open" if inv else None), True
    return pre, pre, False


def key_project_nos(s):
    m = LEADING_NUMS_RE.match(s)
    return ONE_NUM_RE.findall(m.group(0)) if m else []


# ------------------------------------------------------------------- the audit
def audit(store):
    invoices = load(store, "invoices.json", required=True)
    projects = load(store, "projects.json", required=True)
    review = load(store, "needs_review.json", required=False)
    notes_edited = load_changelog(store)

    # Provenance: a post-fix migration leaves these markers behind. Without
    # them we cannot tell a post-fix-correct record from a hand-edited one.
    post_fix_store = any(
        isinstance(r, dict) and r.get("type") == "commission_percent_ignored"
        for r in review)

    findings = []

    # --- invoices ----------------------------------------------------------
    # Keyed by (company_id, invoice_no) -> LIST, because normalize.py appends
    # without dedupe and two rows can share a number. Order is table order,
    # and the project back-fill used the FIRST one.
    inv_index = {}
    for inv in invoices:
        raw = st(inv.get("payment_status_raw"))
        notes = st(inv.get("payment_notes"))
        blob = f"{raw} {notes}"
        pre, post, commission = replay_invoice(blob)
        stored = st(inv.get("payment_status"))
        cid, ino = st(inv.get("company_id")), st(inv.get("invoice_no"))
        rec = {"pre": pre, "post": post, "commission": commission,
               "blob": blob.strip(), "stored": stored,
               "project_no": st(inv.get("project_no")), "company_id": cid,
               "invoice_no": ino, "sheet_row": inv.get("sheet_row")}
        inv_index.setdefault((cid, ino), []).append(rec)

        was_edited = (cid, ino) in notes_edited or (ino,) in notes_edited
        if was_edited and not commission:
            findings.append({
                "kind": "invoice", "verdict": "UNVERIFIABLE", "rank": "high",
                "company_id": cid, "invoice_no": ino, "stored_status": stored,
                "source_text": blob.strip(), "sheet_row": inv.get("sheet_row"),
                "note": ("payment_notes were edited after import "
                         "(changelog.jsonl), so the original blob is gone. A "
                         "commission mention may have been tidied away. Check "
                         "this invoice against the source tracker."),
                "fix": None})
            continue
        if not commission:
            continue
        if pre == post:
            verdict = "FLAG_ONLY"
        elif stored == pre:
            verdict = "CORRECTION_NEEDED"
        elif post_fix_store and stored == post:
            verdict = "FLAG_ONLY"      # imported post-fix; already correct
        else:
            verdict = "ALREADY_CHANGED"
        findings.append({
            "kind": "invoice", "verdict": verdict, "rank": None,
            "company_id": cid, "invoice_no": ino, "stored_status": stored,
            "old_code_produced": pre, "correct_status": post,
            "source_text": blob.strip(), "sheet_row": inv.get("sheet_row"),
            "fix": (f'update_invoice(company_id="{cid}", invoice_no="{ino}", '
                    f'fields={{"payment_status": "{post}"}})')
                   if verdict == "CORRECTION_NEEDED" else None})

    # --- raw project key cells rescued from needs_review --------------------
    raw_key_by_project = {}
    for r in review:
        if not isinstance(r, dict) or r.get("type") != "project_key":
            continue
        raw = st(r.get("raw"))
        if not raw:
            continue
        for pno in key_project_nos(raw):
            raw_key_by_project.setdefault(pno, raw)

    # --- projects ----------------------------------------------------------
    by_project = {}
    for recs in inv_index.values():
        for rec in recs:
            if rec["project_no"]:
                by_project.setdefault(rec["project_no"], []).append(rec)

    for p in projects:
        cs = st(p.get("collection_status"))
        # "open" can never diverge (both paths produce it identically), and an
        # empty status has nothing to correct. Everything else is in scope --
        # including "paid", which a ">=100% comm" key cell could have produced.
        if cs in ("", "open"):
            continue
        pno = st(p.get("project_no"))
        cid = st(p.get("company_id"))
        linked = by_project.get(pno, []) if pno else []
        base = {"kind": "project", "project_no": pno or "(unnumbered)",
                "company_id": cid, "stored_status": cs}

        # 1. Definitive: we have the actual key cell.
        raw = raw_key_by_project.get(pno)
        if raw:
            pre, post, commission = replay_project_key(raw)
            if commission and pre != post:
                verdict = ("CORRECTION_NEEDED" if cs == st(pre)
                           else ("FLAG_ONLY" if post_fix_store and cs == st(post)
                                 else "ALREADY_CHANGED"))
                findings.append({**base, "verdict": verdict, "rank": None,
                    "old_code_produced": st(pre), "correct_status": st(post),
                    "source_text": raw,
                    "note": "key cell recovered from needs_review.json",
                    "fix": (f'update_project(project_no="{pno}", fields='
                            f'{{"collection_status": "{st(post)}"}})')
                           if verdict == "CORRECTION_NEEDED" else None})
            continue          # settled either way -- no guessing needed

        # 2. Derived: a linked invoice whose blob carries a commission % and
        #    whose old-code output matches this status. Origin is ambiguous
        #    (key cell vs back-fill) but the conclusion is the same.
        hit = next((r for r in linked
                    if r["commission"] and r["pre"] != r["post"]
                    and cs == r["pre"]), None)
        if hit:
            findings.append({**base, "verdict": "CORRECTION_NEEDED",
                "rank": None, "old_code_produced": hit["pre"],
                "correct_status": hit["post"], "source_text": hit["blob"],
                "derived_from_invoice": hit["invoice_no"],
                "fix": (f'update_project(project_no="{pno}", fields='
                        f'{{"collection_status": "{hit["post"]}"}})')})
            continue

        # 3. Unverifiable. A matching CLEAN invoice does NOT clear the project:
        #    parse_project_key runs first and the back-fill is skipped when a
        #    status is already set, so an equal value proves nothing.
        if cs.startswith("partial:"):
            rank, note = "high", (
                "a stray percentage drove this status and the key cell is not "
                "persisted. Check this project's key in the source tracker "
                "for a commission mention.")
        else:                                   # "paid"
            corroborated = any(PAID_RE.search(r["blob"]) for r in linked)
            if corroborated:
                continue     # a linked invoice independently says paid
            rank, note = "low", (
                "'paid' can also come from a key cell reading '>=100% comm', "
                "which the old code resolved to paid. No linked invoice "
                "corroborates it. Low priority, but not provably clean.")
        findings.append({**base, "verdict": "UNVERIFIABLE", "rank": rank,
                         "old_code_produced": None, "correct_status": None,
                         "source_text": None, "note": note, "fix": None})

    return findings, len(invoices), len(projects), post_fix_store


# ------------------------------------------------------------------ rendering
ORDER = ["CORRECTION_NEEDED", "UNVERIFIABLE", "ALREADY_CHANGED", "FLAG_ONLY"]


def render(findings, n_inv, n_proj, post_fix_store, store):
    rank_w = {"high": 0, "low": 1, None: 0}
    findings.sort(key=lambda f: (ORDER.index(f["verdict"]),
                                 rank_w.get(f.get("rank"), 0),
                                 st(f.get("invoice_no") or f.get("project_no"))))
    counts = {}
    for f in findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

    L = ["# Commission-% mis-import audit", "",
         f"Store: `{store}`",
         f"Scanned: {n_inv} invoices, {n_proj} projects.",
         f"Store migration provenance: "
         f"{'post-0.1.23 (commission markers present)' if post_fix_store else 'pre-0.1.23 or unknown (no commission markers in needs_review)'}",
         "", "Both `normalize.py` call sites are replayed with their own "
         "semantics over each", "record's stored source text. Read-only; "
         "nothing was modified.", "", "## Summary", ""]
    if not findings:
        L += ["**No findings.** Read the coverage limits below before treating "
              "this as an all-clear.", ""]
    else:
        for v in ORDER:
            if counts.get(v):
                L.append(f"- **{v}** — {counts[v]}")
        L.append("")

    for v in ORDER:
        rows = [f for f in findings if f["verdict"] == v]
        if not rows:
            continue
        L += [f"## {v} ({len(rows)})", ""]
        for f in rows:
            ident = (f'invoice {f["invoice_no"]} (company `{f["company_id"]}`)'
                     if f["kind"] == "invoice" else f'project {f["project_no"]}')
            if f.get("rank"):
                ident += f' — {f["rank"]} priority'
            L.append(f"### {ident}")
            L.append(f"- stored status: `{f['stored_status']}`")
            if f.get("correct_status"):
                L.append(f"- should be: `{f['correct_status']}`")
            if f.get("source_text"):
                L.append(f"- source text: `{f['source_text']}`")
            if f.get("derived_from_invoice"):
                L.append(f"- back-filled from invoice {f['derived_from_invoice']}")
            if f.get("sheet_row"):
                L.append(f"- tracker row: {f['sheet_row']}")
            if f.get("note"):
                L.append(f"- {f['note']}")
            if f.get("fix"):
                L.append(f"- proposed fix (NOT applied): `{f['fix']}`")
            L.append("")

    L += ["## Coverage limits", "",
          "1. **Invoice findings rest on `payment_notes`, which is editable.** "
          "An invoice whose notes were changed after import is reported as "
          "UNVERIFIABLE, but only if the edit is recorded in "
          "`changelog.jsonl`; a store missing that file cannot be checked.",
          "2. **Project key cells are mostly not persisted.** Only rows that "
          "already had a review reason (multi-project / non-numeric keys) keep "
          "their raw cell. Everything else is UNVERIFIABLE, not clean.",
          "3. **A clean linked invoice does not clear a project.** "
          "`parse_project_key` runs before the invoice back-fill, so an equal "
          "value proves nothing about origin.",
          "4. **Detection inherits `COMMISSION_RE`'s blind spots.** "
          "`commision` (typo), `comm'n`, `cmsn`, or a bare `10% to D` are not "
          "matched by the shipped fix and so are not matched here. A clean "
          "result means the current regex sees no commission — not that none "
          "exists.", "",
          "No correction was applied. Every `fix` line is a proposal for a "
          "person to run and confirm.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="CRM store directory")
    ap.add_argument("--out", required=True,
                    help="report path (must be OUTSIDE the store)")
    a = ap.parse_args()

    store = os.path.realpath(a.store)
    out = os.path.realpath(a.out)
    if not os.path.isdir(store):
        sys.exit(f"FATAL: no such store directory: {store}")
    if not any(os.path.exists(os.path.join(store, m)) for m in STORE_MARKERS):
        sys.exit(f"FATAL: {store} has none of {', '.join(STORE_MARKERS)}. "
                 f"This does not look like a CRM store.")
    try:
        inside = os.path.commonpath([out, store]) == store
    except ValueError:
        inside = False                     # different drives (Windows): fine
    if inside:
        sys.exit("FATAL: --out resolves inside the store. This audit never "
                 "writes into a live store. Choose a path outside it.")

    findings, n_inv, n_proj, post_fix = audit(store)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(findings, n_inv, n_proj, post_fix, store))

    tally = {v: sum(1 for f in findings if f["verdict"] == v) for v in ORDER}
    print(f"Scanned {n_inv} invoices, {n_proj} projects.")
    print("  " + "   ".join(f"{v}: {tally[v]}" for v in ORDER))
    print(f"Report: {out}")
    print("Read-only: no store file was modified.")


if __name__ == "__main__":
    main()

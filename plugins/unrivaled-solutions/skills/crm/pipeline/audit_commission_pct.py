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
PAID_QUALIFIER_RE = re.compile(
    r"\b(?:not|never|non|no|isn'?t|wasn'?t|aren'?t|won'?t|"
    r"will|shall|should|would|expect(?:ed|ing|s)?|due|pending|awaiting|chas(?:e|ing)|"
    r"partial(?:ly)?|part|half|balance|remaining|outstanding|short|"
    r"if|unless|when|once|after|before|upon|assuming|"
    r"to\s+be|yet\s+to|going\s+to|supposed\s+to)\b", re.IGNORECASE)


def says_paid(text):
    """True (paid) / False (no mention) / None (qualified -- do not guess).

    Must stay in step with normalize.py's says_paid. A checker that reproduces
    the importer's own parsing cannot catch the importer's mistake: this file
    and audit_workbook_vs_store.py both carried the bare \\bpaid\\b and so
    certified "NOT PAID" as paid for five releases.
    """
    t = "" if text is None else str(text)
    if not PAID_RE.search(t):
        return False
    return None if PAID_QUALIFIER_RE.search(t) else True

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
    # .strip() to match server._key(), which strips: a padded " 7001 " is
    # logged as "acme:7001", so an unstripped lookup key never matched it.
    return (re.sub(r"\.0$", "", str(v)) if isinstance(v, (int, float))
            else str(v)).strip()


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


def from_importer(rec):
    """True if this invoice came through pipeline/normalize.py.

    Since v0.1.26 an invoice can be typed in by hand (create_invoice). Such a
    record's `blob` would be the operator's own free-text payment_notes, and
    replaying the pre-0.1.23 importer regexes over prose the importer never saw
    can produce a confident CORRECTION_NEEDED whose proposed fix overwrites a
    correct, deliberately-entered status. This audit only has jurisdiction over
    records the importer wrote.

    The primary test is POSITIVE -- create_invoice stamps source="manual"
    (v0.1.28+). The absence test below is a FALLBACK, not the primary: on its
    own it silently skipped genuinely-imported invoices written by an older
    pipeline that didn't set those fields, hiding real money errors behind an
    "out of scope" line. Absence of evidence is not evidence.

    But it cannot be dropped either. create_invoice shipped in v0.1.26 without
    the stamp, so every invoice hand-entered under 0.1.26 or 0.1.27 has no
    source at all. Judged on the positive test alone those records read as
    imported, and the audit then replays the importer's regexes over the
    operator's own free text and proposes a destructive "fix" to a status they
    deliberately typed. Keeping both tests costs only the original false-skip
    risk on a record that has NEITHER a payment_status_raw NOR a sheet_row --
    a record the importer has no evidence it ever wrote.
    """
    if st(rec.get("source")).strip().lower() == "manual":
        return False
    if not st(rec.get("payment_status_raw")).strip() \
            and not st(rec.get("sheet_row")).strip():
        return False
    return True


def load_changelog(store):
    """Invoice keys whose payment_notes were EDITED after import.

    Two bugs lived here. The key was rebuilt as a tuple while Store.log writes
    a single joined string ("acme:7001"), so no lookup ever matched and the
    UNVERIFIABLE branch was dead code -- the printed coverage promise was
    false. And the op was never filtered, so once create_invoice began logging
    a whole record (payment_notes included) every hand-created invoice would
    have been reported as "edited after import". Fixing either alone turns a
    silent false negative into a loud false positive; both are fixed together.
    """
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
            if e.get("op") == "rename" and isinstance(fields, dict):
                # An edit is recorded under the number the invoice had AT THE
                # TIME. rename_invoice then moves it, so a lookup by the current
                # number missed the edit and an invoice whose evidence had been
                # overwritten was reported CLEAN instead of UNVERIFIABLE.
                #
                # Applied SEQUENTIALLY, in log order, to the set of keys edited
                # SO FAR -- not as a closure over a timestamp-free old->new map.
                # That map applied every rename to every edit regardless of
                # order, which was worse than not chaining at all: an undone
                # renumber (A->B->A) landed on B and lost the finding, and a
                # number later reused by a different invoice moved the edit onto
                # that innocent record, whose report then proposed overwriting a
                # payment status somebody had deliberately typed.
                key = st(e.get("key"))                       # "<company>:<old>"
                new_no = st(fields.get("new_invoice_no")).strip()
                cid = key.rsplit(":", 1)[0] if ":" in key else ""
                if new_no and cid and key in edited:
                    edited.discard(key)
                    edited.add(f"{cid}:{new_no}")
                continue
            if e.get("op") != "update":
                continue
            if isinstance(fields, dict) and "payment_notes" in fields:
                # Store.log writes key as the joined string "<company>:<invoice>".
                edited.add(st(e.get("key")))
    return edited


# --------------------------------------------------------------- replay: sites
def replay_invoice(blob):
    """Return (pre_fix, post_fix, commission_seen) for the invoice loop."""
    # bare PAID_RE ON PURPOSE: this REPLAYS the pre-0.1.23 importer to
    # discover what it produced. Using the corrected says_paid() here
    # would replay a decision that never happened and invalidate every
    # verdict. The corrected form is used for current-truth judgements
    # (see the corroboration test below) and by find_qualified_paid().
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
    if PAID_RE.search(s):   # replay, not current truth -- see replay_invoice
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
    hand_entered = 0
    for inv in invoices:
        if not from_importer(inv):
            hand_entered += 1
            continue
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

        was_edited = f"{cid}:{ino}" in notes_edited
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
    # Only importer-written invoices may corroborate or condemn a project's
    # collection_status -- inv_index already excludes hand-entered ones.
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
                    # post is None when the replay says the cell implies no
                    # collection status at all. st(None) is "", and
                    # update_project REFUSES "" (collection_status must be
                    # paid|open|partial[:detail]) -- so the report handed the
                    # operator a remedy that errors. null is what clears it.
                    "fix": (f'update_project(project_no="{pno}", fields='
                            f'{{"collection_status": '
                            f'{json.dumps(st(post) or None)}}})')
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
            corroborated = any((says_paid(r["blob"]) is True) for r in linked)
            if corroborated:
                continue     # a linked invoice independently says paid
            rank, note = "low", (
                "'paid' can also come from a key cell reading '>=100% comm', "
                "which the old code resolved to paid. No linked invoice "
                "corroborates it. Low priority, but not provably clean.")
        findings.append({**base, "verdict": "UNVERIFIABLE", "rank": rank,
                         "old_code_produced": None, "correct_status": None,
                         "source_text": None, "note": note, "fix": None})

    return findings, len(invoices), len(projects), post_fix_store, hand_entered


# ------------------------------------------------------------------ rendering
ORDER = ["CORRECTION_NEEDED", "UNVERIFIABLE", "ALREADY_CHANGED", "FLAG_ONLY"]


def render(findings, n_inv, n_proj, post_fix_store, hand_entered, store):
    rank_w = {"high": 0, "low": 1, None: 0}
    findings.sort(key=lambda f: (ORDER.index(f["verdict"]),
                                 rank_w.get(f.get("rank"), 0),
                                 st(f.get("invoice_no") or f.get("project_no"))))
    counts = {}
    for f in findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

    L = ["# Commission-% mis-import audit", "",
         f"Store: `{store}`",
         f"Scanned: {n_inv - hand_entered} imported invoices, "
         f"{n_proj} projects."
         + (f" Skipped {hand_entered} hand-entered invoice(s) — out of scope, see below." if hand_entered else ""),
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
            if f.get("correct_status") is not None:
                # not `if f.get(...)`: an empty correct_status means "no
                # collection status", which is a real answer. Testing
                # truthiness suppressed the one line that says what is right.
                L.append(f"- should be: "
                         f"`{f['correct_status'] or '(no collection status)'}`")
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
          "0. **Hand-entered invoices are out of scope and are skipped.** "
          "An invoice created with `create_invoice` (v0.1.26+) carries no "
          "importer decision to replay. Judging one would mean running the "
          "importer's regexes over the operator's own free text, which can "
          "manufacture a confident correction that overwrites a "
          "deliberately-entered status. Such records are neither reported nor "
          "allowed to corroborate a project's collection status. Detection is "
          "`source == \"manual\"` (stamped from v0.1.28), OR -- for records "
          "hand-entered under 0.1.26/0.1.27, before the stamp existed -- the "
          "absence of both `payment_status_raw` and `sheet_row`. The fallback "
          "can in principle skip a genuinely-imported invoice written by a "
          "pipeline old enough to have set neither field; that is the known "
          "cost of not mis-judging an unstamped hand-entry.",
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

    findings, n_inv, n_proj, post_fix, hand_entered = audit(store)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(findings, n_inv, n_proj, post_fix, hand_entered, store))

    tally = {v: sum(1 for f in findings if f["verdict"] == v) for v in ORDER}
    print(f"Scanned {n_inv - hand_entered} imported invoices, {n_proj} projects."
          + (f"  ({hand_entered} hand-entered, out of scope)" if hand_entered else ""))
    print("  " + "   ".join(f"{v}: {tally[v]}" for v in ORDER))
    print(f"Report: {out}")
    print("Read-only: no store file was modified.")


if __name__ == "__main__":
    main()

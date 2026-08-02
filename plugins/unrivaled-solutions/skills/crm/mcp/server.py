#!/usr/bin/env python3
"""Unrivaled CRM MCP — v0.1

The single read/write interface over the maintained store (schema §8 of
crm-data-schema.md). The interactive view, PO automation, and the sales
engine call this; nothing touches the JSON files directly.

Store location is parameterized — never hard-coded:
    UNRIVALED_CRM_STORE=/path/to/store python3 server.py
    python3 server.py --store /path/to/store

Contract rules (crm-hybrid-build-plan.md):
- Reads are side-effect-free.
- Writes are explicit, validated, atomic (temp file + os.replace), and
  logged append-only to changelog.jsonl.
- needs_review flags are preserved and surfaced, never dropped.
- Outlook actions (draft_email, sync_outlook) are Phase 5 — gated on
  graph_write_spike.py — and not exposed here yet.
"""

import argparse
import contextlib
import functools
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

def _launch_log(msg):
    try:
        p = Path(tempfile.gettempdir()) / "unrivaled-crm-launch.log"
        # Cap growth: truncate if it passes ~256KB. Diagnostic tail only.
        if p.exists() and p.stat().st_size > 262144:
            tail = p.read_text(encoding="utf-8", errors="replace")[-32768:]
            p.write_text(tail, encoding="utf-8")
        with open(p, "a", encoding="utf-8") as _f:
            _f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except Exception:
        pass


_launch_log(f"launch python={sys.executable} argv={sys.argv!r} "
            f"UNRIVALED_CRM_STORE={os.environ.get('UNRIVALED_CRM_STORE')!r}")

try:
    from mcp.server.fastmcp import FastMCP
except Exception as _e:
    _launch_log(f"FATAL: mcp import failed: {_e!r}")
    raise

VERSION = "0.1"

# ---------------------------------------------------------------- store

ENTITY_FILES = {
    "companies": "companies.json",
    "contacts": "contacts.json",
    "projects": "projects.json",
    "shipments": "shipments.json",
    "invoices": "invoices.json",
    "vendors": "vendors.json",
    "needs_review": "needs_review.json",
}

ENRICHMENT_FILE = "enrichment.json"
ENRICHMENT_FIELDS = {"last_contact", "threads", "meetings", "refreshed_at", "source"}

PROJECT_STATUSES = {"won", "pending", "lost"}
SHIPMENT_STAGES = {"Ordered", "Shipped", "Delivered", "Installed", "On Hold", "Cancelled"}
COLLECTION_RE = re.compile(r"^(paid|open|partial(:.+)?)$")

PROJECT_FIELDS = {
    "project_no", "company_id", "company_name", "owner", "date", "description",
    "location", "annotations", "status", "po_flag", "client_po_no", "invoice_no",
    "collection_status", "revenue", "total_cost", "gross_profit", "margin",
    "notes", "year", "archived", "archived_at",
}
SHIPMENT_FIELDS = {
    "shipment_id", "project_no", "all_project_nos", "vendor_po_raw", "ship_date",
    "stage", "company_id", "client_name", "linked_to_project",
    "open_orders_notes", "start_date", "vendor_id", "eta",
}
# Full invoice/customer-order record shape, as produced by pipeline/normalize.py.
# Most of these come straight from the source billing documents (the tracker's
# CLIENT Invoices table) and are deliberately NOT editable here -- only the
# fields a person would actually need to correct or update post-ingestion are.
INVOICE_FIELDS = {
    "invoice_no", "client_po_raw", "invoice_date", "payment_status",
    "payment_status_raw", "pay_date", "client_name", "company_id",
    "payment_notes", "vendor_notes", "project_no", "sheet_row", "due_on",
    # Provenance, set to "manual" by create_invoice and never by the importer.
    # A POSITIVE marker: pipeline/audit_commission_pct.py must not infer
    # hand-entry from a missing payment_status_raw/sheet_row, because an
    # invoice imported by an older pipeline can also lack those -- and
    # skipping one of those would hide a real, money-affecting correction
    # behind a confident "out of scope" claim.
    "source",
}
# due_on is a manual override -- when absent, get_company/list_invoices report
# an effective_due_on computed as invoice_date + DEFAULT_NET_TERMS_DAYS (Net 30)
# instead. Editing due_on here sets the override; it never overwrites the
# underlying invoice_date.
INVOICE_EDITABLE_FIELDS = {"payment_status", "pay_date", "payment_notes",
                          "client_po_raw", "due_on",
                          # Opened up in v0.1.26, when create_invoice made
                          # hand-entered invoices possible. The old lock was
                          # justified by "these come from the source billing
                          # documents" -- true when every invoice arrived via
                          # normalize.py, but a typo'd invoice_date on an
                          # invoice a person typed would otherwise be
                          # permanently uncorrectable, and it silently drives
                          # the Net-30 effective_due_on.
                          "invoice_date", "project_no"}
# Settable at creation. company_id arrives as its own argument, and
# payment_status_raw / sheet_row are importer provenance -- they record what
# the source workbook literally said, so a hand-created invoice legitimately
# has neither. payment_status_raw in particular is the evidence base
# pipeline/audit_commission_pct.py replays; letting it be written by hand
# would erode an audit trail that already cannot be reconstructed.
INVOICE_CREATE_FIELDS = (INVOICE_FIELDS
                         - {"company_id", "payment_status_raw", "sheet_row",
                            "source"})
DEFAULT_NET_TERMS_DAYS = 30
CONTACT_FIELDS = {
    "company_id", "company_name", "name", "email", "phone", "title", "location",
    "action_notes", "last_action",
}
COMPANY_FIELDS = {
    "company_id", "display_name", "role", "domains", "locations", "primary_location",
    "archived", "archived_at", "notes",
}
VENDOR_FIELDS = {
    "company_id", "display_name", "hq_location", "rep", "email", "phone",
    "offerings", "notes", "po_routing", "invoice_routing", "po_routing_source",
    "archived", "archived_at",
}
# "lead" is a prospect that hasn't become real business yet -- it's a plain
# company record like customer/vendor (same entity, same fields), just a
# distinct role for the search/filter segment. convert_lead() flips one to
# "customer" once it closes; there's no lead->vendor path since a vendor
# relationship isn't something that "converts" the same way.
COMPANY_ROLES = {"customer", "vendor", "lead"}

LOCK_FILENAME = ".store.lock"
LOCK_STALE_SECONDS = 30   # far longer than any single tool call should take
LOCK_WAIT_SECONDS = 10    # give up and surface a clear error rather than hang


SERVER_VERSION = "0.1.28"


class StoreError(Exception):
    pass


class Store:
    """Owns the JSON files. All mutation goes through save() (atomic) and log()."""

    def __init__(self, root: Path):
        self.root = root
        missing = [f for f in ENTITY_FILES.values() if not (root / f).exists()]
        if missing and "companies.json" not in missing:
            # Real store, newer schema: create the missing entity files empty
            # rather than dying (the invoices.json lesson, 2026-07-14). Goes
            # through self._write — the same atomic-temp-file + os.replace
            # Windows-lock retry as every other store write (v0.1.9). A bare
            # write_text here defeated the exact lesson this code exists to
            # apply: it could still throw an unhandled PermissionError and
            # take the whole server down at boot.
            for f in missing:
                self._write(f, [])
            _launch_log(f"auto-created missing store files: {missing}")
            missing = []
        if missing:
            raise StoreError(f"store at {root} is missing: {missing}")
        # Sweep atomic-write temp files orphaned by a hard kill mid-write
        # (power loss, force-quit): nothing else ever removes them, and the
        # OneDrive backup mirrors them forever. Age-gated one hour so another
        # live server's in-flight temp (lifetime: milliseconds) is never hit.
        cutoff = time.time() - 3600
        for tmpf in self.root.glob(".~*.tmp"):
            try:
                if tmpf.stat().st_mtime < cutoff:
                    tmpf.unlink()
                    _launch_log(f"swept orphaned temp file {tmpf.name}")
            except OSError:
                pass

    def load(self, entity):
        return self._read_json(self.root / ENTITY_FILES[entity], [])

    @staticmethod
    def _read_json(path, default):
        """Tolerant read: utf-8-sig (survives a BOM), and a clear StoreError
        rather than a raw JSONDecodeError if a file is corrupt/half-written
        (OneDrive conflicted copy, crash mid-write, hand-edit typo)."""
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise StoreError(f"{path.name} is unreadable ({e}); restore it from "
                             f"a backup or fix the JSON") from e

    def save(self, entity, records):
        """Atomic write: temp file in the same dir, then os.replace."""
        self._write(ENTITY_FILES[entity], records)

    def _write(self, filename, data):
        target = self.root / filename
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".~", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False, default=str)
                f.flush()
                os.fsync(f.fileno())
            # os.replace raises PermissionError on Windows when the target is
            # momentarily held open by OneDrive sync, robocopy, or Defender.
            # Retry with backoff before giving up.
            last = None
            for delay in (0, 0.15, 0.4, 0.8, 1.5):
                if delay:
                    time.sleep(delay)
                try:
                    os.replace(tmp, target)
                    return
                except PermissionError as e:
                    last = e
            raise StoreError(
                f"could not save {filename}: the file is locked by another "
                f"process (OneDrive/backup/antivirus). Change not written — "
                f"retry in a moment. ({last})")
        except BaseException:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    # Outlook read-signal overlay (Phase 4). Optional file; never part of
    # the core records — the store stays the source of truth.
    def load_enrichment(self):
        return self._read_json(self.root / ENRICHMENT_FILE, {})

    def save_enrichment(self, data):
        self._write(ENRICHMENT_FILE, data)

    def log(self, op, entity, key, fields):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": op, "entity": entity, "key": key, "fields": fields,
            "interface_version": VERSION,
        }
        # Best-effort: the data write already succeeded and is the source of
        # truth. A locked changelog (OneDrive/AV) must not fail the operation
        # or double-raise after a successful save.
        try:
            with open(self.root / "changelog.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError as e:
            _launch_log(f"changelog append failed (non-fatal): {e}")

    @contextlib.contextmanager
    def write_lock(self):
        """Exclusive lock across the whole store, held for one write tool's
        full read-modify-write (v0.1.10). Each open Cowork chat window spawns
        its own server.py process against the same store; without this, two
        windows can each load a file before either saves, and whichever save
        lands second silently discards the other's change — ok:true returned
        to both callers, no error anywhere. Implemented with atomic exclusive
        file creation (O_CREAT|O_EXCL), which behaves the same on Windows and
        POSIX, unlike fcntl/msvcrt — no extra dependency needed. Self-heals:
        a lock file older than LOCK_STALE_SECONDS is treated as an orphan
        from a crashed process and taken over, rather than deadlocking the
        store forever."""
        lock_path = self.root / LOCK_FILENAME
        deadline = time.time() + LOCK_WAIT_SECONDS
        acquired = False
        while not acquired:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} "
                             f"{datetime.now(timezone.utc).isoformat()}".encode())
                os.close(fd)
                acquired = True
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except OSError:
                    age = 0  # vanished between the failed create and stat; retry
                if age > LOCK_STALE_SECONDS:
                    # Takeover must have exactly one winner. A bare unlink()
                    # here let two waiters both see the same stale lock, A
                    # unlink+recreate, then B unlink A's FRESH lock — two
                    # holders. os.replace is atomic: the second waiter's
                    # rename finds lock_path gone and just re-enters the
                    # O_CREAT|O_EXCL race. Re-stat right before taking over
                    # so a lock refreshed since the age check isn't stolen.
                    grave = lock_path.with_name(
                        f"{LOCK_FILENAME}.stale-{os.getpid()}")
                    try:
                        if time.time() - lock_path.stat().st_mtime > LOCK_STALE_SECONDS:
                            os.replace(lock_path, grave)
                            grave.unlink()
                    except OSError:
                        pass  # lost the takeover race; compete for the create
                    continue
                if time.time() >= deadline:
                    raise StoreError(
                        "store is locked by another operation (another "
                        "Cowork window may be mid-save) — try again in a "
                        "moment")
                time.sleep(0.1)
        try:
            yield
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass


STORE: Store = None  # set in main()

# ------------------------------------------------------------- helpers


def _norm(s):
    return (s or "").strip().lower()


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", _norm(name)).strip("-")
    return s or None


def _company_by_ref(companies, ref):
    """Find a company by company_id or (loosely) by display name."""
    r = _norm(ref)
    for c in companies:
        if c["company_id"] == ref or c["company_id"] == r:
            return c
    for c in companies:
        if _norm(c["display_name"]) == r:
            return c
    matches = [c for c in companies if r and r in _norm(c["display_name"])]
    return matches[0] if len(matches) == 1 else None


def _review_flags(needs_review, **match):
    out = []
    for item in needs_review:
        if all(str(item.get(k, "")).lower() == str(v).lower() for k, v in match.items() if v):
            out.append(item)
    return out


# Identifier-ish fields that must be stored as strings even when the caller sends
# a number. A tool caller can perfectly reasonably pass project_no=1234; stored as
# an int it survives every check here (the duplicate test str()-normalises before
# comparing) and then breaks the visual app, which calls string methods on it.
# Coerce once, centrally, at the only door every create/update goes through.
# Deliberately EXCLUDED, and it matters: revenue, total_cost, gross_profit,
# margin, sheet_row and especially year are genuinely numeric. Stringifying
# `year` would silently zero every KPI in the visual app, which tests it with
# a strict `p.year === thisYear`.
TEXT_FIELDS = {
    # identifiers
    "project_no", "invoice_no", "client_po_no", "client_po_raw", "vendor_po_raw",
    "shipment_id", "company_id", "vendor_id",
    # names and free text
    "company_name", "client_name", "display_name", "description", "name",
    "email", "phone", "title", "notes", "payment_notes", "vendor_notes",
    "open_orders_notes", "action_notes", "offerings", "rep", "po_routing",
    "invoice_routing", "po_routing_source",
    # locations
    "location", "primary_location", "hq_location",
    # dates: stored as ISO strings and read with .slice()/.localeCompare()/
    # lexical `<` comparisons in the view. A numeric one blanks the detail pane
    # and, before that, silently mis-buckets an overdue invoice as "due later".
    "date", "invoice_date", "pay_date", "due_on", "ship_date", "start_date",
    "eta", "last_action",
}


def _num_to_str(v):
    """1234 -> '1234', and 1234.0 -> '1234', not '1234.0'.

    JSON-RPC callers and LLMs routinely emit an integer as a float. Persisting
    "1234.0" as an identifier is worse than the bug this coercion fixes: it
    displays wrong everywhere and never matches an operator typing "1234", so
    the duplicate check mints a phantom record instead of rejecting it.
    """
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _canon(v):
    """The canonical form of an identifier ENTERING the system.

    Apply to caller input only -- a lookup argument, or a value about to be
    persisted -- and NEVER to a value read back off disk. Folds the string
    form of a de-floated number ("7002.0" -> "7002") so an operator or an LLM
    that types "7002.0" still reaches the record stored as "7002", and so
    nothing can persist a ".0" key in the first place. pipeline/normalize.py
    has always done exactly this at its own import boundary.

    Deliberately NOT symmetric with _key, and this is the point. The first
    unpublished fix attempt folded BOTH sides, which made an archived "4521.0" and a live "4521" the
    same key: get_company then dropped the live project's invoices as
    archived, and real receivables vanished with ok:true and no error
    anywhere. Folding one side leaves a mismatch the operator can see; folding
    both silently merges two records and loses money. Reproduced both ways
    before choosing.

    The residual: a project stored as "4521.0" by an older version is not
    findable by typing "4521". That is a visible "not found", not a silent
    merge, and normalize.py cannot produce such a key -- project numbers come
    from a digits-only regex and all three invoice-number sites already strip
    a trailing ".0".
    """
    k = _key(v)
    return k[:-2] if k.endswith(".0") and k[:-2].lstrip("-").isdigit() else k


def _coerce_text(fields):
    """Stringify numeric values in identifier/text/date fields, in place."""
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    # Stringify only -- deliberately NOT _canon. This is the door every create
    # AND update goes through, and most identifiers arriving here are LINKS to
    # an existing record (an invoice's project_no), not new numbers. Folding
    # them here rewrote a link to the project stored as "4521.0" into a link to
    # the different project "4521", on a save that only meant to change a
    # payment status. Canonicalization belongs at the two places an identifier
    # is genuinely minted -- create_project and create_invoice -- and those
    # call _canon explicitly.
    for k, v in list(fields.items()):
        if k in TEXT_FIELDS and num(v):
            fields[k] = _num_to_str(v)
        elif k == "all_project_nos":
            # coerce the SHAPE as well as the members: a scalar here reached
            # disk and then raised a raw TypeError out of every read.
            fields[k] = [_num_to_str(x) if num(x) else x for x in _as_list(v)]


def _validate(fields, allowed, entity):
    unknown = set(fields) - allowed
    if unknown:
        raise StoreError(f"unknown {entity} field(s): {sorted(unknown)}")
    _coerce_text(fields)
    if "status" in fields and fields["status"] is not None \
            and fields["status"] not in PROJECT_STATUSES:
        raise StoreError(f"status must be one of {sorted(PROJECT_STATUSES)}")
    if "role" in fields and fields["role"] is not None \
            and fields["role"] not in COMPANY_ROLES:
        raise StoreError(f"role must be one of {sorted(COMPANY_ROLES)}")
    if "stage" in fields and fields["stage"] not in SHIPMENT_STAGES:
        raise StoreError(f"stage must be one of {sorted(SHIPMENT_STAGES)}")
    if "collection_status" in fields and fields["collection_status"] is not None \
            and not COLLECTION_RE.match(str(fields["collection_status"])):
        raise StoreError("collection_status must be paid | open | partial[:detail]")
    if "payment_status" in fields and fields["payment_status"] is not None \
            and not COLLECTION_RE.match(str(fields["payment_status"])):
        raise StoreError("payment_status must be paid | open | partial[:detail]")


def _key(v):
    """The comparison form of an identifier ALREADY IN THE STORE. Exact.

    Every project_no / invoice_no comparison against a value read from disk
    MUST go through this. v0.1.27's first attempt normalized inside the new
    link guards but left the archive filters on bare str(), so " 4700 " read
    as live in one place and archived in another and the invoice vanished
    anyway. One definition, used everywhere, is the only version of this that
    stays true.

    This does NOT fold a trailing ".0", and that asymmetry with _canon is the
    whole design -- see _canon.
    """
    if v is None or isinstance(v, bool):
        return ""          # _num_to_str(None) is the STRING "None" -- truthy,
                           # and it would match a record whose id is literally
                           # null as well as one reading "None".
    return _num_to_str(v).strip()


def _resolve(wanted, stored_keys):
    """The stored key that `wanted` addresses. EXACT match wins.

    Only when nothing matches exactly do we fall back to the canonical form, so
    a caller who types "7600.0" still reaches the invoice stored as "7600".

    This exists because a lookup argument is NOT necessarily fresh input. The
    view round-trips stored identifiers straight back as lookup keys --
    openEditInvoice passes `v.invoice_no` verbatim, saveInvoice passes it on to
    update_invoice -- so canonicalizing an argument unconditionally addressed a
    record's numerically-shaped twin instead of the record itself: editing the
    invoice stored as "7001.0" marked the *other* invoice, "7001", paid and
    overwrote its notes. Preferring the exact match makes that impossible.

    The fallback cannot merge two records, because it only runs when the exact
    form matched nothing at all -- it can never take a record away from a key
    that genuinely exists.
    """
    w = _key(wanted)
    if w in stored_keys:
        return w
    c = _canon(wanted)
    return c if c in stored_keys else w


def _project_keys(projects=None):
    """Every project_no on disk, in stored (exact) form."""
    return {_key(p.get("project_no"))
            for p in (projects if projects is not None else STORE.load("projects"))}


def _invoice_key(invoices, company_id, wanted):
    """Resolve `wanted` against the invoice numbers of ONE company."""
    return _resolve(wanted, {_key(i.get("invoice_no")) for i in invoices
                             if i.get("company_id") == company_id})


def _live_project(pno):
    """The project a link may point at, or None.

    Archived projects still sit in projects.json -- archive only flags them
    (_set_project_archived). But every default read drops invoices whose
    project_no is archived (get_company, list_invoices), so linking to one
    writes a record that is invisible everywhere while returning ok:true.
    That is exactly the outcome the link guards exist to prevent, so an
    archived project is NOT a valid link target.

    An AMBIGUOUS key is refused too. A legacy store can hold two records under
    one project_no, one archived and one live: this used to return the live one
    (so the link guard passed) while _archived_project_nos still contained the
    key (so every default read hid the record anyway). The result was a
    receivable created with ok:true that was invisible the moment it was
    written. update_invoice and rename_invoice already refuse an ambiguous
    invoice number for the same reason; this is the project-side equivalent.
    """
    projects = STORE.load("projects")
    key = _resolve(pno, _project_keys(projects))
    if not key:
        return None
    matches = [p for p in projects if _key(p.get("project_no")) == key]
    if len(matches) > 1:
        raise StoreError(
            f"{len(matches)} projects share the number '{key}' "
            f"(archived: {[bool(m.get('archived')) for m in matches]}). "
            f"Linking to it would create a record that is hidden by the "
            f"archived twin -- resolve the duplicate before linking.")
    return matches[0] if matches and not matches[0].get("archived") else None


def _same_invoice(rec, company_id, invoice_key):
    """Identity test for an invoice, used by every path that looks one up.

    `invoice_key` must ALREADY be a stored-form key -- resolve a caller's
    argument with _invoice_key() first. Passing a raw argument here is what let
    a lookup for "7001.0" land on the record stored as "7001".

    (company_id, invoice_no) is the key, but the two sides were once compared
    with different normalizations -- a candidate through _num_to_str against a
    stored value through bare str(). A store holding invoice_no as the JSON
    number 7001.0 then failed the duplicate check and minted a second record
    for the same receivable, after which marking one paid left the other open.
    """
    return (rec.get("company_id") == company_id
            and _key(rec.get("invoice_no")) == invoice_key)


def _require_company(company_id):
    companies = STORE.load("companies")
    if not any(c["company_id"] == company_id for c in companies):
        raise StoreError(f"company_id '{company_id}' does not exist")


def _archived_ids():
    """Set of company_ids currently archived (soft-deleted)."""
    return {c["company_id"] for c in STORE.load("companies") if c.get("archived")}


def _archived_project_nos():
    """Set of project_no (as str) currently archived (soft-deleted).

    Falsy keys are dropped, and that is load-bearing. _key(None/True/"  ") is
    "", and an invoice with no project keys to "" too -- so a single archived
    project with a missing or non-string project_no put "" in this set and
    every UNLINKED invoice in the store vanished from get_company and
    list_invoices, across all companies, with ok:true. normalize.py leaves
    project_no null whenever an invoice has no tracker link, so those are
    ordinary records, not edge cases. _shipment_project_nos already filtered
    falsy; this did not.
    """
    return {k for p in STORE.load("projects") if p.get("archived")
            and (k := _key(p.get("project_no")))}


def _as_list(v):
    """A stored list-shaped field, coerced. The Python twin of the view's arr().

    all_project_nos is a list in everything the importer and the tools write,
    but _coerce_text only validates it WHEN it is already a list, so a scalar
    or a string passes straight through create_shipment/update_shipment. Then
    `for n in v` either raises TypeError on an int -- a RAW exception, not
    {ok:false}, because @_store_errors only catches StoreError, which killed
    get_company, get_project and list_shipments for the whole store -- or,
    worse, silently iterates a string's CHARACTERS, so "100" became {"1","0"}
    and the leg disappeared from its own project.
    """
    if isinstance(v, list):
        return v
    if v is None or isinstance(v, bool) or v == "":
        return []
    if v == 0:
        # not [0]: a truthy list here suppressed the project_no fallback, and
        # the `if n` filter downstream then dropped the 0 anyway, so the leg
        # vanished from its own project.
        return []
    return [v]


def _shipment_project_nos(s):
    """A shipment's linked project numbers, as strings -- all_project_nos when
    present, else its own project_no. Mirrors the lookup in get_project."""
    nos = _as_list(s.get("all_project_nos")) \
        or ([s.get("project_no")] if s.get("project_no") else [])
    return {_key(n) for n in nos if n}


def _parse_date_loose(s):
    """Best-effort parse of the date-ish strings normalize.py produces
    (openpyxl datetimes stringified as "2026-03-14 00:00:00", or plain
    "3/14/2026"/"3/14/26"). Returns None rather than guessing on anything
    that doesn't cleanly match -- an unknown invoice_date must not silently
    become a wrong due date."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _effective_due_on(inv):
    """due_on if a manual override is on file; else invoice_date plus the
    default Net terms window. Never mutates the stored record -- this is
    computed fresh on every read so it reflects DEFAULT_NET_TERMS_DAYS
    immediately if that ever changes, and a missing/unparseable invoice_date
    reports None rather than a fabricated date."""
    if inv.get("due_on"):
        return inv["due_on"]
    d = _parse_date_loose(inv.get("invoice_date"))
    if not d:
        return None
    from datetime import timedelta
    return (d + timedelta(days=DEFAULT_NET_TERMS_DAYS)).strftime("%Y-%m-%d")


def _with_due_on(invoices):
    """Return copies of invoice records enriched with effective_due_on --
    used only in tool responses, never persisted."""
    return [dict(i, effective_due_on=_effective_due_on(i)) for i in invoices]


def _err(e):
    return {"ok": False, "error": str(e), "interface_version": VERSION}


def _store_errors(fn):
    """Read tools don't take the write lock, but they can still hit a corrupt
    entity file (OneDrive conflicted copy). Convert StoreError into the same
    {ok:false, error} payload the write tools return, instead of letting a
    raw exception cross the MCP wire."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StoreError as e:
            return _err(e)
    return wrapper

# ------------------------------------------------------------------ mcp

mcp = FastMCP("unrivaled-crm")

# --------- reads (side-effect-free) ---------


@mcp.tool()
@_store_errors
def get_company(ref: str) -> dict:
    """Company by id or name, with nested contacts, projects, open shipments,
    and any needs_review flags."""
    companies = STORE.load("companies")
    c = _company_by_ref(companies, ref)
    if not c:
        return _err(f"no unique company match for '{ref}'")
    cid = c["company_id"]
    contacts = [x for x in STORE.load("contacts") if x["company_id"] == cid]
    projects = [x for x in STORE.load("projects")
                if x["company_id"] == cid and not x.get("archived")]
    arch_pnos = _archived_project_nos()
    shipments = [x for x in STORE.load("shipments")
                 if x["company_id"] == cid
                 and not (_shipment_project_nos(x) & arch_pnos)]
    invoices = [x for x in STORE.load("invoices")
                if x.get("company_id") == cid
                and _key(x.get("project_no")) not in arch_pnos]
    flags = [x for x in STORE.load("needs_review")
             if cid in (x.get("company_ids") or []) or x.get("company_id") == cid]
    return {"ok": True, "interface_version": VERSION, "company": c,
            "contacts": contacts, "projects": projects,
            "shipments": shipments, "invoices": _with_due_on(invoices),
            "needs_review": flags,
            "enrichment": STORE.load_enrichment().get(cid)}


@mcp.tool()
@_store_errors
def list_companies(role: str = None, query: str = None,
                   include_archived: bool = False) -> dict:
    """Companies, optionally filtered by role (customer|vendor|lead) and/or a
    name substring. Archived (soft-deleted) companies are excluded unless
    include_archived=True."""
    out = STORE.load("companies")
    if not include_archived:
        out = [c for c in out if not c.get("archived")]
    if role:
        out = [c for c in out if c.get("role") == role]
    if query:
        q = _norm(query)
        out = [c for c in out if q in _norm(c["display_name"])]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "companies": out}


@mcp.tool()
@_store_errors
def get_project(project_no: str) -> dict:
    """Project card with its shipments, company, and contacts."""
    projects = STORE.load("projects")
    want = _resolve(project_no, _project_keys(projects))
    pr = [p for p in projects if _key(p.get("project_no")) == want] if want else []
    if not pr:
        return _err(f"project '{project_no}' not found")
    p = pr[0]
    shipments = [s for s in STORE.load("shipments")
                 if want in _shipment_project_nos(s)]
    companies = STORE.load("companies")
    company = next((c for c in companies if c["company_id"] == p["company_id"]), None)
    contacts = [c for c in STORE.load("contacts") if c["company_id"] == p["company_id"]]
    flags = _review_flags(STORE.load("needs_review"), project_no=project_no)
    return {"ok": True, "interface_version": VERSION, "project": p,
            "company": company, "contacts": contacts,
            "shipments": shipments, "needs_review": flags}


@mcp.tool()
@_store_errors
def list_projects(status: str = None, owner: str = None, year: int = None,
                  collection_status: str = None, include_archived: bool = False) -> dict:
    """Project cards filtered by status (won|pending|lost), owner initial,
    year, and/or collection_status (paid|open|partial). Projects of archived
    companies are excluded unless include_archived=True."""
    out = STORE.load("projects")
    if not include_archived:
        arch = _archived_ids()
        out = [p for p in out if p.get("company_id") not in arch and not p.get("archived")]
    if status:
        out = [p for p in out if p.get("status") == status]
    if owner:
        out = [p for p in out if owner in (p.get("owner") or [])]
    if year:
        out = [p for p in out if p.get("year") == year]
    if collection_status:
        out = [p for p in out
               if str(p.get("collection_status") or "").startswith(collection_status)]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "projects": out}


@mcp.tool()
@_store_errors
def list_shipments(stage: str = None, company: str = None, vendor_po: str = None,
                   overdue: bool = None, include_archived: bool = False) -> dict:
    """Shipment legs, filtered by stage, company (id or name), vendor_po
    (exact or substring match against vendor_po_raw -- use this to find
    which project a vendor's PO number belongs to), and/or overdue (ship_date
    past but not Delivered/Installed). Legs of archived companies are
    excluded unless include_archived=True."""
    out = STORE.load("shipments")
    if not include_archived:
        arch = _archived_ids()
        arch_pnos = _archived_project_nos()
        out = [s for s in out if s.get("company_id") not in arch
               and not (_shipment_project_nos(s) & arch_pnos)]
    if stage:
        out = [s for s in out if s.get("stage") == stage]
    if company:
        c = _company_by_ref(STORE.load("companies"), company)
        if not c:
            return _err(f"no unique company match for '{company}'")
        out = [s for s in out if s.get("company_id") == c["company_id"]]
    if vendor_po:
        q = str(vendor_po).strip().lower()
        out = [s for s in out if q in str(s.get("vendor_po_raw") or "").lower()]
    if overdue:
        today = datetime.now().strftime("%Y-%m-%d")
        out = [s for s in out
               if s.get("ship_date") and str(s["ship_date"])[:10] < today
               and s.get("stage") not in ("Delivered", "Installed", "Cancelled")]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "shipments": out}


@mcp.tool()
@_store_errors
def get_vendor(ref: str) -> dict:
    """Vendor by id or name, with offerings and PO/invoice routing."""
    vendors = STORE.load("vendors")
    r = _norm(ref)
    v = next((x for x in vendors
              if x["company_id"] == ref or _norm(x["display_name"]) == r), None)
    if not v:
        matches = [x for x in vendors if r and r in _norm(x["display_name"])]
        v = matches[0] if len(matches) == 1 else None
    if not v:
        return _err(f"no unique vendor match for '{ref}'")
    return {"ok": True, "interface_version": VERSION, "vendor": v}


@mcp.tool()
@_store_errors
def list_invoices(payment_status: str = None, company: str = None,
                  invoice_no: str = None, overdue: bool = None,
                  include_archived: bool = False) -> dict:
    """Client invoices / customer orders (the receivables ledger from the
    tracker's CLIENT Invoices table). Filter by payment_status (paid|open|
    partial), company (id or name), invoice_no (exact or substring), and/or
    overdue (effective_due_on has passed and payment_status isn't paid).
    Every invoice carries effective_due_on: the due_on override if one was
    set, else invoice_date + Net 30. Invoices of archived companies are
    excluded unless include_archived=True."""
    out = STORE.load("invoices")
    if not include_archived:
        arch = _archived_ids()
        arch_pnos = _archived_project_nos()
        out = [i for i in out if i.get("company_id") not in arch
               and _key(i.get("project_no")) not in arch_pnos]
    if payment_status:
        out = [i for i in out
               if str(i.get("payment_status") or "").startswith(payment_status)]
    if company:
        c = _company_by_ref(STORE.load("companies"), company)
        if not c:
            return _err(f"no unique company match for '{company}'")
        out = [i for i in out if i.get("company_id") == c["company_id"]]
    if invoice_no:
        q = str(invoice_no).strip().lower()
        out = [i for i in out if q in str(i.get("invoice_no") or "").lower()]
    out = _with_due_on(out)
    if overdue:
        today = datetime.now().strftime("%Y-%m-%d")
        out = [i for i in out
               if i.get("effective_due_on") and i["effective_due_on"] < today
               and not str(i.get("payment_status") or "").startswith("paid")]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "invoices": out}


@mcp.tool()
@_store_errors
def find_contacts(company: str = None, query: str = None,
                  include_archived: bool = False) -> dict:
    """Contacts, filtered by company (id or name) and/or a substring of
    name/email/title. Contacts of archived companies are excluded unless
    include_archived=True."""
    out = STORE.load("contacts")
    if not include_archived:
        arch = _archived_ids()
        out = [x for x in out if x.get("company_id") not in arch]
    if company:
        c = _company_by_ref(STORE.load("companies"), company)
        if not c:
            return _err(f"no unique company match for '{company}'")
        out = [x for x in out if x["company_id"] == c["company_id"]]
    if query:
        q = _norm(query)
        out = [x for x in out
               if q in _norm(x.get("name")) or q in _norm(x.get("email"))
               or q in _norm(x.get("title"))]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "contacts": out}


# --------- writes (validated, atomic, logged) ---------


@mcp.tool()
def update_project(project_no: str, fields: dict) -> dict:
    """Edit a project card (status, owner, revenue, collection_status, notes, ...).
    Validated against the v0.1 schema; persists atomically."""
    try:
        with STORE.write_lock():
            _validate(fields, PROJECT_FIELDS - {"project_no"}, "project")
            if "company_id" in fields:
                _require_company(fields["company_id"])
            projects = STORE.load("projects")
            want = _resolve(project_no, _project_keys(projects))
            target = [p for p in projects
                      if _key(p.get("project_no")) == want] if want else []
            if not target:
                return _err(f"project '{project_no}' not found")
            target[0].update(fields)
            STORE.save("projects", projects)
            STORE.log("update", "project", want, fields)
            return {"ok": True, "interface_version": VERSION, "project": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def rename_project(old_project_no: str, new_project_no: str) -> dict:
    """Change a project's number/key. Updates every shipment and invoice that
    references the old number so nothing gets silently orphaned -- a plain
    field edit can't do this safely, since project_no is a lookup key other
    records point at, not just a display value. Fails if new_project_no is
    empty or already used by a different project. (Ingestion-time
    needs_review entries referencing the old number are left as-is -- they're
    a historical note about the original migration, not a live pointer.)"""
    try:
        with STORE.write_lock():
            # _canon, not str: a caller sending 9999.0 would otherwise persist
            # "9999.0" and cascade it into every referencing shipment and
            # invoice. rename_project is the ONLY way to change a project_no,
            # so this path cannot rely on _validate/_coerce_text.
            new_pn = _canon(new_project_no)
            if not new_pn:
                raise StoreError("new_project_no cannot be empty")
            projects = STORE.load("projects")
            old_pn = _resolve(old_project_no, _project_keys(projects))
            if not old_pn:
                # Without this an empty old number matches every project whose
                # own key is falsy (_key(None/True/"  ") is ""), and the
                # cascades below then repoint EVERY unlinked invoice and
                # shipment in the store -- across all companies -- onto the new
                # number. rename_invoice guards this; this one did not.
                raise StoreError("old_project_no cannot be empty")
            target = [p for p in projects if _key(p.get("project_no")) == old_pn]
            if not target:
                return _err(f"project '{old_project_no}' not found")
            if new_pn != old_pn and any(_key(p.get("project_no")) == new_pn
                                        for p in projects):
                raise StoreError(f"project '{new_pn}' already exists")
            target[0]["project_no"] = new_pn
            STORE.save("projects", projects)

            shipments = STORE.load("shipments")
            touched_shipments = 0
            for s in shipments:
                changed = False
                if _key(s.get("project_no")) == old_pn:
                    s["project_no"] = new_pn
                    changed = True
                all_pnos = _as_list(s.get("all_project_nos"))
                if any(_key(n) == old_pn for n in all_pnos):
                    s["all_project_nos"] = [new_pn if _key(n) == old_pn else n
                                             for n in all_pnos]
                    changed = True
                touched_shipments += 1 if changed else 0
            if touched_shipments:
                STORE.save("shipments", shipments)

            invoices = STORE.load("invoices")
            touched_invoices = 0
            for i in invoices:
                if _key(i.get("project_no")) == old_pn:
                    i["project_no"] = new_pn
                    touched_invoices += 1
            if touched_invoices:
                STORE.save("invoices", invoices)

            STORE.log("rename", "project", old_pn,
                      {"new_project_no": new_pn, "shipments_updated": touched_shipments,
                       "invoices_updated": touched_invoices})
            return {"ok": True, "interface_version": VERSION, "project": target[0],
                    "shipments_updated": touched_shipments,
                    "invoices_updated": touched_invoices}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def update_shipment(shipment_id: str, fields: dict) -> dict:
    """Edit a shipment leg — advance stage (Ordered|Shipped|Delivered|Installed|
    On Hold|Cancelled), set ship_date/eta/notes.

    Cannot re-link the leg to another project: pass project_no/all_project_nos
    to reassign_shipment, which validates the target and keeps project_no,
    all_project_nos and linked_to_project consistent in one write."""
    try:
        with STORE.write_lock():
            # The link fields are refused here rather than silently accepted.
            # SHIPMENT_FIELDS contains them, so this tool used to write them
            # with NO liveness check at all -- the one door left open after
            # create_shipment and reassign_shipment were both hardened. It
            # could park a leg on an archived project (invisible everywhere,
            # ok:true), put a ".0" key on disk, or store project_no as a
            # boolean. The docstring and interface-v0.1.md already described
            # this tool as stage/dates only; prose is not a guard.
            link_fields = {"project_no", "all_project_nos", "linked_to_project"}
            offered = link_fields & set(fields)
            if offered:
                raise StoreError(
                    f"update_shipment cannot change {sorted(offered)} -- use "
                    f"reassign_shipment, which checks the target project still "
                    f"exists and keeps the leg's links consistent")
            _validate(fields, SHIPMENT_FIELDS - {"shipment_id"} - link_fields,
                      "shipment")
            shipments = STORE.load("shipments")
            target = [s for s in shipments if s.get("shipment_id") == shipment_id]
            if not target:
                return _err(f"shipment '{shipment_id}' not found")
            target[0].update(fields)
            STORE.save("shipments", shipments)
            STORE.log("update", "shipment", shipment_id, fields)
            return {"ok": True, "interface_version": VERSION, "shipment": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def reassign_shipment(shipment_id: str, new_project_no: str = None,
                      also_project_nos: list = None) -> dict:
    """Move a shipment to a different project number -- for when it was
    logged under the wrong deal. Unlike a plain update_shipment field edit,
    this validates the target project exists and keeps project_no,
    all_project_nos, and linked_to_project consistent with each other in one
    write. Pass new_project_no=None or "" to unlink the shipment entirely
    (vendor-PO-keyed, no project attached) instead of reassigning it.

    also_project_nos covers the one leg shape the importer can produce that a
    single new_project_no cannot express: a leg that genuinely serves several
    projects (all_project_nos with more than one entry). Every number listed
    must name a live project, and new_project_no stays the primary. Without
    this there was no tool left that could restore a multi-project link, since
    update_shipment refuses the link fields outright."""
    try:
        with STORE.write_lock():
            shipments = STORE.load("shipments")
            target = [s for s in shipments if s["shipment_id"] == shipment_id]
            if not target:
                return _err(f"shipment '{shipment_id}' not found")
            # _resolve, not _key: _key left a caller's "4521.0" un-canonicalized
            # while _live_project validated it against the project stored as
            # "4521". The leg then persisted "4521.0", was invisible on the
            # project page, and stopped being counted by the -L<n> counter --
            # so "+ Add shipment" failed permanently on a duplicate id.
            new_pn = _resolve(new_project_no, _project_keys()) or None
            if new_pn:
                if not _live_project(new_pn):
                    raise StoreError(f"project '{new_pn}' not found, or has "
                                     f"been deleted -- a shipment linked to it "
                                     f"would not appear anywhere")
            extra = []
            for n in _as_list(also_project_nos):
                k = _resolve(n, _project_keys()) or None
                if not k:
                    continue
                if not _live_project(k):
                    raise StoreError(f"project '{k}' not found, or has been "
                                     f"deleted -- a shipment linked to it "
                                     f"would not appear anywhere")
                if k != new_pn and k not in extra:
                    extra.append(k)
            if extra and not new_pn:
                raise StoreError("also_project_nos needs a new_project_no -- "
                                 "the primary project cannot be empty while "
                                 "the leg is linked to others")
            old_pn = target[0].get("project_no")
            target[0]["project_no"] = new_pn
            target[0]["all_project_nos"] = ([new_pn] + extra) if new_pn else []
            target[0]["linked_to_project"] = bool(new_pn)
            STORE.save("shipments", shipments)
            STORE.log("reassign", "shipment", shipment_id,
                      {"old_project_no": old_pn, "new_project_no": new_pn,
                       "also_project_nos": extra})
            return {"ok": True, "interface_version": VERSION, "shipment": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def upsert_contact(fields: dict) -> dict:
    """Create or update a contact. Match key: email if present, else
    (company_id, name). company_id must exist."""
    try:
        with STORE.write_lock():
            _validate(fields, CONTACT_FIELDS, "contact")
            if not fields.get("company_id") or not fields.get("name"):
                raise StoreError("contact needs at least company_id and name")
            _require_company(fields["company_id"])
            contacts = STORE.load("contacts")
            match = None
            if fields.get("email"):
                match = next((c for c in contacts
                              if _norm(c.get("email")) == _norm(fields["email"])), None)
            if match is None:
                match = next((c for c in contacts
                              if c["company_id"] == fields["company_id"]
                              and _norm(c.get("name")) == _norm(fields["name"])), None)
            if match:
                match.update(fields)
                op, record = "update", match
            else:
                record = {k: None for k in CONTACT_FIELDS}
                record.update(fields)
                contacts.append(record)
                op = "create"
            STORE.save("contacts", contacts)
            STORE.log(op, "contact", fields.get("email") or fields["name"], fields)
            return {"ok": True, "interface_version": VERSION, "op": op, "contact": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def update_company(company_id: str, fields: dict) -> dict:
    """Edit a company record (display_name, role, domains, locations)."""
    try:
        with STORE.write_lock():
            _validate(fields, COMPANY_FIELDS - {"company_id"}, "company")
            companies = STORE.load("companies")
            target = [c for c in companies if c["company_id"] == company_id]
            if not target:
                return _err(f"company '{company_id}' not found")
            target[0].update(fields)
            STORE.save("companies", companies)
            STORE.log("update", "company", company_id, fields)
            return {"ok": True, "interface_version": VERSION, "company": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_project(fields: dict) -> dict:
    """Add a project card. Requires project_no (unique) and an existing
    company_id."""
    try:
        with STORE.write_lock():
            _validate(fields, PROJECT_FIELDS, "project")
            # A MINT: this is one of only two places a project/invoice number is
            # created rather than looked up, so it canonicalizes explicitly.
            # _coerce_text deliberately does not (it also runs on updates, where
            # an identifier is a LINK and folding it silently relinks records).
            # The bool test comes first: _coerce_text skips bools, so a True
            # would survive as a project whose _key is "" -- which poisons the
            # archived-key set and the rename cascades.
            if isinstance(fields.get("project_no"), bool) \
                    or not fields.get("project_no") or not fields.get("company_id"):
                raise StoreError("create_project needs project_no and company_id")
            pn = _canon(fields["project_no"])
            if not pn:
                raise StoreError("create_project needs project_no and company_id")
            fields["project_no"] = pn
            _require_company(fields["company_id"])
            projects = STORE.load("projects")
            if any(_key(p.get("project_no")) == pn for p in projects):
                raise StoreError(f"project '{pn}' already exists")
            record = {k: None for k in PROJECT_FIELDS}
            record.update({"owner": [], "annotations": [], "po_flag": False, "archived": False})
            record.update(fields)
            projects.append(record)
            STORE.save("projects", projects)
            STORE.log("create", "project", str(pn), fields)
            return {"ok": True, "interface_version": VERSION, "project": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_shipment(project_no: str, fields: dict) -> dict:
    """Add a shipment leg to an existing project. shipment_id is derived
    (<project_no>-L<n>) unless supplied."""
    try:
        with STORE.write_lock():
            _validate(fields, SHIPMENT_FIELDS, "shipment")
            projects = STORE.load("projects")
            pr = _live_project(project_no)
            if not pr:
                raise StoreError(f"project '{project_no}' not found, or has "
                                 f"been deleted -- a shipment linked to it "
                                 f"would not appear anywhere")
            # The project's OWN stored key, so the leg links to it exactly.
            # v0.1.27 validated through _live_project (which normalizes) but
            # persisted the raw argument, so " 4521 " stored padded and the leg
            # was invisible on the project page.
            pno = _key(pr.get("project_no"))
            shipments = STORE.load("shipments")
            sid = fields.get("shipment_id")
            if not sid:
                # Find the first FREE suffix, don't count current links. The id
                # is a permanent global key but the count is a moving target:
                # reassigning 100-L1 to another project drops the count back to
                # 0, so the next "+ Add shipment" on project 100 re-derived
                # "100-L1", collided with the leg that still carries that id,
                # and the button stayed dead forever with no in-app way out.
                taken = {s.get("shipment_id") for s in shipments}
                n = 1
                while f"{pno}-L{n}" in taken:
                    n += 1
                sid = f"{pno}-L{n}"
            if any(s.get("shipment_id") == sid for s in shipments):
                raise StoreError(f"shipment '{sid}' already exists")
            record = {k: None for k in SHIPMENT_FIELDS}
            # Caller fields FIRST, then the authoritative identity -- the same
            # order create_invoice uses. Reversed, `fields` won: a caller could
            # pass project_no/all_project_nos/company_id/shipment_id and
            # overwrite the very values the _live_project guard above had just
            # validated, in the same call. That put legs on archived projects,
            # on other companies, and ".0" keys on disk, all with ok:true.
            record.update(fields)
            record.update({
                "shipment_id": sid, "project_no": pno,
                "all_project_nos": [pno], "stage": fields.get("stage") or "Ordered",
                "company_id": pr["company_id"], "client_name": pr.get("company_name"),
                "linked_to_project": True,
            })
            _validate({"stage": record["stage"]}, SHIPMENT_FIELDS, "shipment")
            shipments.append(record)
            STORE.save("shipments", shipments)
            STORE.log("create", "shipment", sid, fields)
            return {"ok": True, "interface_version": VERSION, "shipment": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_company(fields: dict) -> dict:
    """Add a customer, vendor, or lead company (pass role="lead" for a
    prospect that hasn't become real business yet -- convert_lead flips it
    to a customer once it does). Requires display_name; role defaults to
    'customer'. company_id is derived from the name unless supplied, and
    must be unique."""
    try:
        with STORE.write_lock():
            _validate(fields, COMPANY_FIELDS, "company")
            name = fields.get("display_name")
            if not name:
                raise StoreError("create_company needs display_name")
            role = fields.get("role") or "customer"
            if role not in COMPANY_ROLES:
                raise StoreError(f"role must be one of {sorted(COMPANY_ROLES)}")
            cid = fields.get("company_id") or _slug(name)
            if not cid:
                raise StoreError("could not derive a company_id from display_name")
            companies = STORE.load("companies")
            if any(c["company_id"] == cid for c in companies):
                raise StoreError(f"company '{cid}' already exists")
            record = {k: None for k in COMPANY_FIELDS}
            record.update({"company_id": cid, "display_name": name, "role": role,
                           "domains": [], "locations": [], "archived": False})
            record.update(fields)
            record["company_id"], record["role"] = cid, role
            if not record.get("primary_location") and record.get("locations"):
                record["primary_location"] = record["locations"][0]
            companies.append(record)
            STORE.save("companies", companies)
            STORE.log("create", "company", cid, {"display_name": name, "role": role})
            return {"ok": True, "interface_version": VERSION, "company": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_vendor(fields: dict) -> dict:
    """Add a vendor: creates (or reuses) its company record with role=vendor
    and a vendor detail record (rep, email, phone, offerings, PO/invoice
    routing). Requires display_name; company_id derived from the name unless
    supplied. Vendor detail must not already exist."""
    try:
        with STORE.write_lock():
            _validate(fields, VENDOR_FIELDS, "vendor")
            name = fields.get("display_name")
            if not name:
                raise StoreError("create_vendor needs display_name")
            cid = fields.get("company_id") or _slug(name)
            if not cid:
                raise StoreError("could not derive a company_id from display_name")
            # Check the vendor detail record FIRST, before mutating companies.json.
            # Ordering matters: if we flip a company's role / append a company row
            # and only then discover the vendor already exists, the raise leaves a
            # stray or mutated company record committed to disk while the caller is
            # told the op failed (partial write). Validate everything that can abort
            # up front, then perform both writes. (Hardened v0.1.14.)
            vendors = STORE.load("vendors")
            if any(v["company_id"] == cid for v in vendors):
                raise StoreError(f"vendor '{cid}' already exists")
            companies = STORE.load("companies")
            comp = next((c for c in companies if c["company_id"] == cid), None)
            if comp is None:
                comp = {k: None for k in COMPANY_FIELDS}
                comp.update({"company_id": cid, "display_name": name, "role": "vendor",
                             "domains": [], "locations": [], "archived": False})
                companies.append(comp)
            else:
                comp["role"] = "vendor"
            STORE.save("companies", companies)
            record = {k: None for k in VENDOR_FIELDS}
            record.update({"company_id": cid, "display_name": name, "archived": False,
                           "po_routing_source": fields.get("po_routing_source") or "manual"})
            record.update(fields)
            record["company_id"] = cid
            vendors.append(record)
            STORE.save("vendors", vendors)
            STORE.log("create", "vendor", cid, {"display_name": name})
            return {"ok": True, "interface_version": VERSION, "vendor": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def update_vendor(company_id: str, fields: dict) -> dict:
    """Edit a vendor detail record (rep, email, phone, offerings, PO/invoice
    routing, hq_location)."""
    try:
        with STORE.write_lock():
            _validate(fields, VENDOR_FIELDS - {"company_id"}, "vendor")
            vendors = STORE.load("vendors")
            target = [v for v in vendors if v["company_id"] == company_id]
            if not target:
                return _err(f"vendor '{company_id}' not found")
            target[0].update(fields)
            STORE.save("vendors", vendors)
            STORE.log("update", "vendor", company_id, fields)
            return {"ok": True, "interface_version": VERSION, "vendor": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def update_invoice(company_id: str, invoice_no: str, fields: dict) -> dict:
    """Edit an invoice / customer order: payment_status (paid|open|
    partial[:detail]), pay_date, payment_notes, client_po_raw, due_on, and
    (since v0.1.26) invoice_date and project_no. Matched by
    (company_id, invoice_no) -- invoice numbers aren't guaranteed unique
    across companies. The invoice's own number is not editable here: use
    rename_invoice, which also updates any shipment leg carrying it.
    company_id, payment_status_raw and sheet_row stay locked -- the latter two
    record what the source workbook literally said."""
    try:
        with STORE.write_lock():
            _validate(fields, INVOICE_EDITABLE_FIELDS, "invoice")
            # project_no became editable in v0.1.26. Normalize into `fields`,
            # not just into the check -- validating a stripped value while
            # persisting the raw one stored " 4521 ", which no exact-string
            # lookup downstream ever matches again (archive filters,
            # rename_project's cascade, the audit all silently skipped it).
            _pno = ""
            if "project_no" in fields:
                # _resolve, not _canon. The drawer re-sends project_no verbatim
                # on every save, so this argument is usually a value that came
                # OFF disk. Canonicalizing it rewrote a link to the project
                # stored as "4521.0" into a link to the different project
                # "4521" -- a silent relink on a save that only meant to change
                # the payment status.
                # Keep the RAW exact form too. An echo is an echo: if the
                # value the drawer sent back is byte-identical to what is
                # stored, this is not a relink no matter how it resolves.
                # Comparing a RESOLVED value against an EXACT stored one
                # made an unchanged ".0" link read as a change -- so the
                # liveness check fired on a project the operator never
                # touched and refused to mark the invoice paid.
                if isinstance(fields["project_no"], bool):
                    # _key(True) is "", which silently UNLINKED the invoice
                    # from its project and reported ok:true.
                    raise StoreError(
                        "project_no must be a number or text, not a boolean")
                _raw_pno = _key(fields["project_no"])
                _pno = _resolve(fields["project_no"], _project_keys())
            invoices = STORE.load("invoices")
            inv_key = _invoice_key(invoices, company_id, invoice_no)
            if not inv_key:
                # "" matches every record whose invoice_no is null, so an empty
                # argument would mark an unnumbered invoice paid. create_invoice
                # and rename_invoice both guard this.
                return _err("invoice_no cannot be empty")
            target = [i for i in invoices
                      if _same_invoice(i, company_id, inv_key)]
            if not target:
                return _err(f"invoice '{invoice_no}' for company '{company_id}' not found")
            if len(target) > 1:
                # A store written before the v0.1.27 identity fix can already
                # hold two records answering to one number (e.g. 7001.0 and
                # "7001"). Editing target[0] would mark one paid and leave the
                # other open, reporting ok:true either way -- the exact failure
                # the identity fix exists to prevent. Refuse and name them.
                return _err(f"{len(target)} invoices share number '{invoice_no}' "
                            f"for company '{company_id}' (sheet_rows: "
                            f"{[t.get('sheet_row') for t in target]}). Nothing "
                            f"here can tell them apart, so this needs the "
                            f"duplicate resolved in the store directly -- "
                            f"rename_invoice refuses for the same reason and "
                            f"is not a way around this.")
            # Liveness is enforced only on an ACTUAL relink. The edit drawer
            # re-sends project_no on every save, so checking any value present
            # made "mark this paid" fail whenever the invoice's existing
            # project happened to be archived -- an error naming a field the
            # operator never touched.
            _stored_pno = _key(target[0].get("project_no"))
            _echoed = "project_no" in fields and _raw_pno == _stored_pno
            if _echoed:
                # leave the stored spelling exactly as it is
                fields["project_no"] = target[0].get("project_no")
            elif "project_no" in fields:
                fields["project_no"] = _pno or None   # one form of "unlinked"
            if _pno and not _echoed and _pno != _stored_pno:
                if not _live_project(_pno):
                    raise StoreError(f"project '{_pno}' not found, or has been "
                                     f"deleted -- an invoice linked to it "
                                     f"would not appear anywhere")
            target[0].update(fields)
            STORE.save("invoices", invoices)
            STORE.log("update", "invoice",
                      f"{company_id}:{inv_key}", fields)
            # _with_due_on: the view replaces its local record with this
            # response, so returning the undecorated record dropped
            # effective_due_on and an overdue invoice fell out of the
            # Overdue bucket until the next full refresh.
            return {"ok": True, "interface_version": VERSION,
                    "invoice": _with_due_on([target[0]])[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_invoice(company_id: str, fields: dict) -> dict:
    """Add a client invoice / customer order by hand, for one that never came
    through the tracker workbook. fields must include invoice_no; the useful
    rest are invoice_date, project_no, client_po_raw, payment_status
    (open|paid|partial[:detail], defaults to open), payment_notes and due_on.

    (company_id, invoice_no) is the identity update_invoice matches on, so a
    duplicate for the same company is refused -- use rename_invoice to
    renumber an existing one. A supplied project_no must name a real project;
    linking an invoice to a project that does not exist would leave it
    invisible on that project's page with no error anywhere."""
    try:
        with STORE.write_lock():
            _validate(fields, INVOICE_CREATE_FIELDS, "invoice")
            _require_company(company_id)
            inv_no = _canon(fields.get("invoice_no"))
            if not inv_no:
                raise StoreError("invoice_no is required")
            invoices = STORE.load("invoices")
            if any(_same_invoice(i, company_id, inv_no) for i in invoices):
                return _err(f"invoice '{inv_no}' already exists for company "
                            f"'{company_id}' -- use update_invoice to edit it, "
                            f"or rename_invoice to renumber it")
            pno = _resolve(fields.get("project_no"), _project_keys()) or None
            if pno and not _live_project(pno):
                raise StoreError(f"project '{pno}' not found, or has been "
                                 f"deleted -- an invoice linked to it would "
                                 f"not appear anywhere")
            companies = STORE.load("companies")
            co = next((c for c in companies if c["company_id"] == company_id), None)
            record = {k: None for k in INVOICE_FIELDS}
            record.update(fields)
            record.update({
                "invoice_no": inv_no,
                "company_id": company_id,
                "project_no": pno,
                "payment_status": fields.get("payment_status") or "open",
                "source": "manual",
                "client_name": fields.get("client_name")
                               or (co.get("display_name") if co else None),
            })
            invoices.append(record)
            STORE.save("invoices", invoices)
            STORE.log("create", "invoice", f"{company_id}:{inv_no}", record)
            return {"ok": True, "interface_version": VERSION,
                    "invoice": _with_due_on([record])[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def rename_invoice(company_id: str, old_invoice_no: str, new_invoice_no: str) -> dict:
    """Change an invoice's own number. Like rename_project, this is not a
    plain field edit: (company_id, invoice_no) is the lookup key
    update_invoice matches on, and a shipment leg ingested from the CLIENT
    Invoices table can also carry this invoice_no -- both are updated
    atomically so nothing stops matching. Fails if new_invoice_no is empty
    or already used by a different invoice for the same company."""
    try:
        with STORE.write_lock():
            # new_no is MINTED, so it is canonicalized -- that is what keeps a
            # ".0" key off disk. old_no is a LOOKUP, so it is resolved against
            # what is actually stored, exact form first.
            new_no = _canon(new_invoice_no)
            if not new_no:
                raise StoreError("new_invoice_no cannot be empty")
            invoices = STORE.load("invoices")
            old_no = _invoice_key(invoices, company_id, old_invoice_no)
            if not old_no:
                # Without this, old_no == "" matches every record whose
                # invoice_no is null (_key(None) is ""), and the cascade below
                # then repoints every unnumbered shipment leg in the company.
                raise StoreError("old_invoice_no cannot be empty")
            target = [i for i in invoices
                      if _same_invoice(i, company_id, old_no)]
            if not target:
                return _err(f"invoice '{old_invoice_no}' for company '{company_id}' not found")
            if len(target) > 1:
                # update_invoice refuses a duplicate pair and tells the
                # operator to renumber one with rename_invoice. Doing that
                # unguarded renamed an ARBITRARY twin and repointed every
                # shipment leg carrying the old number -- including the other
                # twin's legs. Following the error message corrupted data, so
                # this path has to refuse for the same reason update_invoice
                # does. Breaking the tie needs a direct edit, not a rename.
                return _err(f"{len(target)} invoices share number '{old_no}' "
                            f"for company '{company_id}' (sheet_rows: "
                            f"{[t.get('sheet_row') for t in target]}). "
                            f"rename_invoice cannot tell them apart -- resolve "
                            f"the duplicate in the store before renumbering.")
            if new_no != old_no and any(
                    _same_invoice(i, company_id, new_no)
                    for i in invoices):
                raise StoreError(f"invoice '{new_no}' already exists for this company")
            target[0]["invoice_no"] = new_no
            STORE.save("invoices", invoices)

            shipments = STORE.load("shipments")
            touched = 0
            for s in shipments:
                if (s.get("company_id") == company_id
                        and _key(s.get("invoice_no")) == old_no):
                    s["invoice_no"] = new_no
                    touched += 1
            if touched:
                STORE.save("shipments", shipments)

            STORE.log("rename", "invoice", f"{company_id}:{old_no}",
                      {"new_invoice_no": new_no, "shipments_updated": touched})
            return {"ok": True, "interface_version": VERSION,
                    "invoice": _with_due_on([target[0]])[0],
                    "shipments_updated": touched}
    except StoreError as e:
        return _err(e)


def _set_archived(company_id: str, archived: bool) -> dict:
    """Soft-delete/restore a company (customer or vendor). Nothing is destroyed:
    the record is flagged and hidden from default reads; its projects, contacts,
    shipments, and invoices are preserved and reappear on restore."""
    try:
        with STORE.write_lock():
            companies = STORE.load("companies")
            target = [c for c in companies if c["company_id"] == company_id]
            if not target:
                return _err(f"company '{company_id}' not found")
            target[0]["archived"] = archived
            target[0]["archived_at"] = (
                datetime.now(timezone.utc).isoformat() if archived else None)
            STORE.save("companies", companies)
            # mirror onto the vendor detail record if this company is a vendor
            vendors = STORE.load("vendors")
            if any(v["company_id"] == company_id for v in vendors):
                for v in vendors:
                    if v["company_id"] == company_id:
                        v["archived"] = archived
                STORE.save("vendors", vendors)
            STORE.log("archive" if archived else "restore", "company", company_id,
                      {"archived": archived})
            return {"ok": True, "interface_version": VERSION, "company": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def archive_company(company_id: str) -> dict:
    """Soft-delete a customer or vendor: it disappears from the CRM but nothing
    is destroyed. Its projects/contacts/shipments/invoices are preserved and
    restored intact with restore_company. Use for deleting customers/vendors."""
    return _set_archived(company_id, True)


@mcp.tool()
def restore_company(company_id: str) -> dict:
    """Un-archive a previously deleted customer or vendor, bringing it and all
    its records back into the CRM."""
    return _set_archived(company_id, False)


@mcp.tool()
def convert_lead(company_id: str) -> dict:
    """Convert a lead into a customer once it becomes real business. Fails
    if the company isn't currently role=lead -- use update_company's role
    field directly for any other role change. There's no lead->vendor
    conversion; a vendor relationship isn't something that "closes" the
    same way a sale does."""
    try:
        with STORE.write_lock():
            companies = STORE.load("companies")
            target = [c for c in companies if c["company_id"] == company_id]
            if not target:
                return _err(f"company '{company_id}' not found")
            if target[0].get("role") != "lead":
                return _err(f"company '{company_id}' is not currently a lead "
                            f"(role={target[0].get('role')!r})")
            target[0]["role"] = "customer"
            STORE.save("companies", companies)
            STORE.log("convert", "company", company_id,
                      {"from": "lead", "to": "customer"})
            return {"ok": True, "interface_version": VERSION, "company": target[0]}
    except StoreError as e:
        return _err(e)


def _set_project_archived(project_no: str, archived: bool) -> dict:
    """Soft-delete/restore a single project. Nothing is destroyed: the project
    record is flagged and hidden from default reads, and so are its shipments
    and invoices (matched by their own project_no/all_project_nos fields) --
    they're left completely unmodified on disk and reappear the moment the
    project is restored."""
    try:
        with STORE.write_lock():
            projects = STORE.load("projects")
            want = _resolve(project_no, _project_keys(projects))
            target = [p for p in projects
                      if _key(p.get("project_no")) == want] if want else []
            if not target:
                return _err(f"project '{project_no}' not found")
            target[0]["archived"] = archived
            target[0]["archived_at"] = (
                datetime.now(timezone.utc).isoformat() if archived else None)
            STORE.save("projects", projects)
            STORE.log("archive" if archived else "restore", "project", want,
                      {"archived": archived})
            return {"ok": True, "interface_version": VERSION, "project": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def archive_project(project_no: str) -> dict:
    """Soft-delete a single project within a customer record: it, its
    shipments, and its invoices disappear from the CRM but nothing is
    destroyed -- restore with restore_project. Use this for deleting a
    project (as opposed to archive_company, which deletes the whole
    customer/vendor)."""
    return _set_project_archived(project_no, True)


@mcp.tool()
def restore_project(project_no: str) -> dict:
    """Un-archive a previously deleted project, bringing it and its
    shipments/invoices back into the CRM."""
    return _set_project_archived(project_no, False)


@mcp.tool()
def set_enrichment(company_id: str, data: dict) -> dict:
    """Attach Outlook read-signal to a company (Phase 4): last_contact,
    threads (subject/with/date/webLink), meetings, refreshed_at, source.
    A non-destructive overlay — core records are never touched. The runner
    (the CRM skill, via the read-only Outlook MCP) computes the data; this
    tool only persists it."""
    try:
        with STORE.write_lock():
            _require_company(company_id)
            unknown = set(data) - ENRICHMENT_FIELDS
            if unknown:
                raise StoreError(f"unknown enrichment field(s): {sorted(unknown)}")
            enrichment = STORE.load_enrichment()
            entry = dict(data)
            # set_enrichment rolls its own field check and never reaches
            # _validate, so coerce here too — last_contact is a date string
            # the view reads as one.
            _coerce_text(entry)
            entry.setdefault("refreshed_at", datetime.now(timezone.utc).isoformat())
            enrichment[company_id] = entry
            STORE.save_enrichment(enrichment)
            STORE.log("enrich", "company", company_id,
                      {"threads": len(data.get("threads") or []),
                       "meetings": len(data.get("meetings") or []),
                       "last_contact": data.get("last_contact")})
            return {"ok": True, "interface_version": VERSION,
                    "company_id": company_id, "enrichment": entry}
    except StoreError as e:
        return _err(e)


# --------- Outlook actions (Phase 5 — spike passed 2026-07-02) ---------


def _graph():
    """Lazy Graph client; raises StoreError with the fallback story when
    Outlook writes aren't configured or signed in."""
    import graph
    try:
        _auth, client = graph.from_env(STORE.root)
        return graph, client
    except graph.GraphError as e:
        raise StoreError(str(e))


@mcp.tool()
def draft_email(contact_email: str, subject: str = None, body: str = None) -> dict:
    """Create a REAL Outlook draft addressed to a store contact (never sends).
    Returns the draft's webLink for one-click open. Contact is identified by
    email (the store's stable contact key)."""
    try:
        contact = next((c for c in STORE.load("contacts")
                        if _norm(c.get("email")) == _norm(contact_email)), None)
        if not contact:
            return _err(f"no store contact with email '{contact_email}'")
        first = (contact.get("name") or "there").split(" ")[0]
        _g, client = _graph()
        try:
            draft = client.create_draft(
                to_email=contact["email"], to_name=contact.get("name"),
                subject=subject or "Following up — Unrivaled Solutions",
                body=body or f"Hi {first},\n\n")
        except Exception as e:
            return _err(e)
        STORE.log("outlook_draft", "contact", contact["email"],
                  {"draft_id": draft["id"], "subject": subject or "(default)"})
        return {"ok": True, "interface_version": VERSION, "draft": draft,
                "contact": {"name": contact.get("name"), "email": contact["email"]}}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def draft_reply(company_id: str, message_id: str, comment: str = None,
                 reply_all: bool = False) -> dict:
    """Create a REAL Outlook draft that replies to one specific message from
    a company's enrichment threads (never sends) -- a genuine reply, not a
    blank new email: Graph auto-populates the correct recipient(s) and
    quotes the original message. message_id comes from that company's
    enrichment data (get_company's enrichment.threads[].message_id -- only
    present on threads captured after this feature shipped; re-run
    enrichment to backfill older ones). Returns the draft's webLink for
    one-click open. reply_all=True replies to everyone on the original
    thread instead of just the sender."""
    try:
        _require_company(company_id)
        _g, client = _graph()
        try:
            draft = client.reply_draft(message_id, comment=comment or "",
                                       reply_all=reply_all)
        except Exception as e:
            return _err(e)
        STORE.log("outlook_reply_draft", "company", company_id,
                  {"draft_id": draft["id"], "message_id": message_id,
                   "reply_all": reply_all})
        return {"ok": True, "interface_version": VERSION, "draft": draft}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def sync_outlook(company_id: str, dry_run: bool = False) -> dict:
    """Write a company's people/status layer natively into Outlook:
    upsert each store contact (company field set) and tag it with the
    company's CRM status categories (from its projects). Idempotent —
    re-running creates no duplicates. Never deletes; existing non-CRM
    categories are preserved. dry_run=True returns the plan without writing."""
    try:
        _require_company(company_id)
        companies = STORE.load("companies")
        company = next(c for c in companies if c["company_id"] == company_id)
        contacts = [c for c in STORE.load("contacts")
                    if c["company_id"] == company_id and c.get("email")
                    and c["email"] not in ("?",)]
        statuses = {p.get("status") for p in STORE.load("projects")
                    if p["company_id"] == company_id and p.get("status")}
        import graph as graph_mod
        cats = [graph_mod.CRM_CATEGORIES[s] for s in sorted(statuses)
                if s in graph_mod.CRM_CATEGORIES]
        plan = {"company": company["display_name"],
                "categories": [c[0] for c in cats],
                "contacts": [{"name": c.get("name"), "email": c["email"]}
                             for c in contacts]}
        if dry_run:
            return {"ok": True, "interface_version": VERSION,
                    "dry_run": True, "plan": plan}
        _g, client = _graph()
        results = []
        try:
            for name, color in cats:
                client.ensure_category(name, color)
            for c in contacts:
                r = client.upsert_contact(
                    email=c["email"], name=c.get("name"),
                    company=company["display_name"], title=c.get("title"),
                    phone=c.get("phone"),
                    add_categories=[n for n, _ in cats])
                results.append({"email": c["email"], "op": r["op"]})
        except Exception as e:
            return _err(e)
        STORE.log("outlook_sync", "company", company_id,
                  {"contacts": len(results), "categories": [n for n, _ in cats]})
        return {"ok": True, "interface_version": VERSION,
                "plan": plan, "results": results}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def crm_info() -> dict:
    """Interface version, store location, record counts, and needs_review summary."""
    # Per-file tolerance: one unreadable file reports as an error string for
    # that entity instead of taking down the whole health check.
    counts, problems = {}, {}
    for e in ENTITY_FILES:
        try:
            counts[e] = len(STORE.load(e))
        except StoreError as ex:
            counts[e] = None
            problems[e] = str(ex)
    out = {"ok": not problems, "interface_version": VERSION,
           "server_version": SERVER_VERSION,
           "store": str(STORE.root), "counts": counts}
    try:
        out["archived_companies"] = len(_archived_ids())
        out["enriched_companies"] = len(STORE.load_enrichment())
    except StoreError as ex:
        problems["enrichment/archive"] = str(ex)
    if problems:
        out["problems"] = problems
    return out


# ----------------------------------------------------------------- main


def main():
    global STORE
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("UNRIVALED_CRM_STORE"))
    args = ap.parse_args()
    if args.store and args.store.lstrip().startswith("${"):
        _launch_log(f"store arg is an unexpanded placeholder {args.store!r}; using env fallback")
        args.store = os.environ.get("UNRIVALED_CRM_STORE")
    if not args.store:
        _cfg = Path.home() / ".unrivaled-crm-store"
        if _cfg.exists():
            # utf-8-sig strips a BOM; Windows PowerShell writes UTF-16 by
            # default, so fall back to that. Strip stray quotes/whitespace.
            try:
                _raw = _cfg.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                _raw = _cfg.read_text(encoding="utf-16")
            args.store = _raw.strip().strip('"').strip("'").strip() or None
            _launch_log(f"store from pointer file {_cfg}: {args.store!r}")
    if not args.store:
        _launch_log("FATAL: no store configured")
        sys.exit("no store: pass --store, set UNRIVALED_CRM_STORE, "
                 "or write the store path into ~/.unrivaled-crm-store")
    try:
        STORE = Store(Path(args.store).resolve())
    except StoreError as e:
        _launch_log(f"FATAL: {e}")
        sys.exit(str(e))
    _launch_log(f"store ok: {Path(args.store).resolve()}")
    mcp.run()  # stdio


if __name__ == "__main__":
    main()

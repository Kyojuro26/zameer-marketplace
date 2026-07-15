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
    "notes", "year",
}
SHIPMENT_FIELDS = {
    "shipment_id", "project_no", "all_project_nos", "vendor_po_raw", "ship_date",
    "stage", "company_id", "client_name", "linked_to_project",
    "open_orders_notes", "start_date", "vendor_id", "eta",
}
CONTACT_FIELDS = {
    "company_id", "company_name", "name", "email", "phone", "title", "location",
    "action_notes", "last_action",
}
COMPANY_FIELDS = {
    "company_id", "display_name", "role", "domains", "locations", "primary_location",
    "archived", "archived_at",
}
VENDOR_FIELDS = {
    "company_id", "display_name", "hq_location", "rep", "email", "phone",
    "offerings", "po_routing", "invoice_routing", "po_routing_source",
    "archived", "archived_at",
}
COMPANY_ROLES = {"customer", "vendor"}


SERVER_VERSION = "0.1.8"


class StoreError(Exception):
    pass


class Store:
    """Owns the JSON files. All mutation goes through save() (atomic) and log()."""

    def __init__(self, root: Path):
        self.root = root
        missing = [f for f in ENTITY_FILES.values() if not (root / f).exists()]
        if missing and "companies.json" not in missing:
            # Real store, newer schema: create the missing entity files empty
            # rather than dying (the invoices.json lesson, 2026-07-14).
            for f in missing:
                (root / f).write_text("[]\n", encoding="utf-8")
            _launch_log(f"auto-created missing store files: {missing}")
            missing = []
        if missing:
            raise StoreError(f"store at {root} is missing: {missing}")

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


def _validate(fields, allowed, entity):
    unknown = set(fields) - allowed
    if unknown:
        raise StoreError(f"unknown {entity} field(s): {sorted(unknown)}")
    if "status" in fields and fields["status"] is not None \
            and fields["status"] not in PROJECT_STATUSES:
        raise StoreError(f"status must be one of {sorted(PROJECT_STATUSES)}")
    if "stage" in fields and fields["stage"] not in SHIPMENT_STAGES:
        raise StoreError(f"stage must be one of {sorted(SHIPMENT_STAGES)}")
    if "collection_status" in fields and fields["collection_status"] is not None \
            and not COLLECTION_RE.match(str(fields["collection_status"])):
        raise StoreError("collection_status must be paid | open | partial[:detail]")


def _require_company(company_id):
    companies = STORE.load("companies")
    if not any(c["company_id"] == company_id for c in companies):
        raise StoreError(f"company_id '{company_id}' does not exist")


def _archived_ids():
    """Set of company_ids currently archived (soft-deleted)."""
    return {c["company_id"] for c in STORE.load("companies") if c.get("archived")}


def _err(e):
    return {"ok": False, "error": str(e), "interface_version": VERSION}

# ------------------------------------------------------------------ mcp

mcp = FastMCP("unrivaled-crm")

# --------- reads (side-effect-free) ---------


@mcp.tool()
def get_company(ref: str) -> dict:
    """Company by id or name, with nested contacts, projects, open shipments,
    and any needs_review flags."""
    companies = STORE.load("companies")
    c = _company_by_ref(companies, ref)
    if not c:
        return _err(f"no unique company match for '{ref}'")
    cid = c["company_id"]
    contacts = [x for x in STORE.load("contacts") if x["company_id"] == cid]
    projects = [x for x in STORE.load("projects") if x["company_id"] == cid]
    shipments = [x for x in STORE.load("shipments") if x["company_id"] == cid]
    invoices = [x for x in STORE.load("invoices") if x.get("company_id") == cid]
    flags = [x for x in STORE.load("needs_review")
             if cid in (x.get("company_ids") or []) or x.get("company_id") == cid]
    return {"ok": True, "interface_version": VERSION, "company": c,
            "contacts": contacts, "projects": projects,
            "shipments": shipments, "invoices": invoices,
            "needs_review": flags,
            "enrichment": STORE.load_enrichment().get(cid)}


@mcp.tool()
def list_companies(role: str = None, query: str = None,
                   include_archived: bool = False) -> dict:
    """Companies, optionally filtered by role (customer|vendor) and/or a
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
def get_project(project_no: str) -> dict:
    """Project card with its shipments, company, and contacts."""
    pr = [p for p in STORE.load("projects") if str(p["project_no"]) == str(project_no)]
    if not pr:
        return _err(f"project '{project_no}' not found")
    p = pr[0]
    shipments = [s for s in STORE.load("shipments")
                 if str(project_no) in [str(n) for n in (s.get("all_project_nos") or [s.get("project_no")])]]
    companies = STORE.load("companies")
    company = next((c for c in companies if c["company_id"] == p["company_id"]), None)
    contacts = [c for c in STORE.load("contacts") if c["company_id"] == p["company_id"]]
    flags = _review_flags(STORE.load("needs_review"), project_no=project_no)
    return {"ok": True, "interface_version": VERSION, "project": p,
            "company": company, "contacts": contacts,
            "shipments": shipments, "needs_review": flags}


@mcp.tool()
def list_projects(status: str = None, owner: str = None, year: int = None,
                  collection_status: str = None, include_archived: bool = False) -> dict:
    """Project cards filtered by status (won|pending|lost), owner initial,
    year, and/or collection_status (paid|open|partial). Projects of archived
    companies are excluded unless include_archived=True."""
    out = STORE.load("projects")
    if not include_archived:
        arch = _archived_ids()
        out = [p for p in out if p.get("company_id") not in arch]
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
def list_shipments(stage: str = None, company: str = None, overdue: bool = None,
                   include_archived: bool = False) -> dict:
    """Shipment legs, filtered by stage, company (id or name), and/or
    overdue (ship_date past but not Delivered/Installed). Legs of archived
    companies are excluded unless include_archived=True."""
    out = STORE.load("shipments")
    if not include_archived:
        arch = _archived_ids()
        out = [s for s in out if s.get("company_id") not in arch]
    if stage:
        out = [s for s in out if s.get("stage") == stage]
    if company:
        c = _company_by_ref(STORE.load("companies"), company)
        if not c:
            return _err(f"no unique company match for '{company}'")
        out = [s for s in out if s.get("company_id") == c["company_id"]]
    if overdue:
        today = datetime.now().strftime("%Y-%m-%d")
        out = [s for s in out
               if s.get("ship_date") and str(s["ship_date"])[:10] < today
               and s.get("stage") not in ("Delivered", "Installed", "Cancelled")]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "shipments": out}


@mcp.tool()
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
def list_invoices(payment_status: str = None, company: str = None,
                  include_archived: bool = False) -> dict:
    """Client invoices / customer orders (the receivables ledger from the
    tracker's CLIENT Invoices table). Filter by payment_status (paid|open|
    partial) and/or company (id or name). Invoices of archived companies are
    excluded unless include_archived=True."""
    out = STORE.load("invoices")
    if not include_archived:
        arch = _archived_ids()
        out = [i for i in out if i.get("company_id") not in arch]
    if payment_status:
        out = [i for i in out
               if str(i.get("payment_status") or "").startswith(payment_status)]
    if company:
        c = _company_by_ref(STORE.load("companies"), company)
        if not c:
            return _err(f"no unique company match for '{company}'")
        out = [i for i in out if i.get("company_id") == c["company_id"]]
    return {"ok": True, "interface_version": VERSION,
            "count": len(out), "invoices": out}


@mcp.tool()
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
        _validate(fields, PROJECT_FIELDS - {"project_no"}, "project")
        if "company_id" in fields:
            _require_company(fields["company_id"])
        projects = STORE.load("projects")
        target = [p for p in projects if str(p["project_no"]) == str(project_no)]
        if not target:
            return _err(f"project '{project_no}' not found")
        target[0].update(fields)
        STORE.save("projects", projects)
        STORE.log("update", "project", str(project_no), fields)
        return {"ok": True, "interface_version": VERSION, "project": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def update_shipment(shipment_id: str, fields: dict) -> dict:
    """Edit a shipment leg — advance stage (Ordered|Shipped|Delivered|Installed|
    On Hold|Cancelled), set ship_date/eta/notes."""
    try:
        _validate(fields, SHIPMENT_FIELDS - {"shipment_id"}, "shipment")
        shipments = STORE.load("shipments")
        target = [s for s in shipments if s["shipment_id"] == shipment_id]
        if not target:
            return _err(f"shipment '{shipment_id}' not found")
        target[0].update(fields)
        STORE.save("shipments", shipments)
        STORE.log("update", "shipment", shipment_id, fields)
        return {"ok": True, "interface_version": VERSION, "shipment": target[0]}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def upsert_contact(fields: dict) -> dict:
    """Create or update a contact. Match key: email if present, else
    (company_id, name). company_id must exist."""
    try:
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
        _validate(fields, PROJECT_FIELDS, "project")
        pn = fields.get("project_no")
        if not pn or not fields.get("company_id"):
            raise StoreError("create_project needs project_no and company_id")
        _require_company(fields["company_id"])
        projects = STORE.load("projects")
        if any(str(p["project_no"]) == str(pn) for p in projects):
            raise StoreError(f"project '{pn}' already exists")
        record = {k: None for k in PROJECT_FIELDS}
        record.update({"owner": [], "annotations": [], "po_flag": False})
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
        _validate(fields, SHIPMENT_FIELDS, "shipment")
        projects = STORE.load("projects")
        pr = next((p for p in projects if str(p["project_no"]) == str(project_no)), None)
        if not pr:
            raise StoreError(f"project '{project_no}' not found")
        shipments = STORE.load("shipments")
        sid = fields.get("shipment_id")
        if not sid:
            n = 1 + sum(1 for s in shipments
                        if str(s.get("project_no")) == str(project_no))
            sid = f"{project_no}-L{n}"
        if any(s["shipment_id"] == sid for s in shipments):
            raise StoreError(f"shipment '{sid}' already exists")
        record = {k: None for k in SHIPMENT_FIELDS}
        record.update({
            "shipment_id": sid, "project_no": str(project_no),
            "all_project_nos": [str(project_no)], "stage": "Ordered",
            "company_id": pr["company_id"], "client_name": pr.get("company_name"),
            "linked_to_project": True,
        })
        record.update(fields)
        _validate({"stage": record["stage"]}, SHIPMENT_FIELDS, "shipment")
        shipments.append(record)
        STORE.save("shipments", shipments)
        STORE.log("create", "shipment", sid, fields)
        return {"ok": True, "interface_version": VERSION, "shipment": record}
    except StoreError as e:
        return _err(e)


@mcp.tool()
def create_company(fields: dict) -> dict:
    """Add a customer or vendor company. Requires display_name; role defaults
    to 'customer'. company_id is derived from the name unless supplied, and
    must be unique."""
    try:
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
        _validate(fields, VENDOR_FIELDS, "vendor")
        name = fields.get("display_name")
        if not name:
            raise StoreError("create_vendor needs display_name")
        cid = fields.get("company_id") or _slug(name)
        if not cid:
            raise StoreError("could not derive a company_id from display_name")
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
        vendors = STORE.load("vendors")
        if any(v["company_id"] == cid for v in vendors):
            raise StoreError(f"vendor '{cid}' already exists")
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


def _set_archived(company_id: str, archived: bool) -> dict:
    """Soft-delete/restore a company (customer or vendor). Nothing is destroyed:
    the record is flagged and hidden from default reads; its projects, contacts,
    shipments, and invoices are preserved and reappear on restore."""
    try:
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
def set_enrichment(company_id: str, data: dict) -> dict:
    """Attach Outlook read-signal to a company (Phase 4): last_contact,
    threads (subject/with/date/webLink), meetings, refreshed_at, source.
    A non-destructive overlay — core records are never touched. The runner
    (the CRM skill, via the read-only Outlook MCP) computes the data; this
    tool only persists it."""
    try:
        _require_company(company_id)
        unknown = set(data) - ENRICHMENT_FIELDS
        if unknown:
            raise StoreError(f"unknown enrichment field(s): {sorted(unknown)}")
        enrichment = STORE.load_enrichment()
        entry = dict(data)
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

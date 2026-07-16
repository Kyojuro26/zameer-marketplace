# Unrivaled CRM Interface — v0.1 (pinned contract)

The stable read/write API exposed by the custom **Unrivaled CRM MCP**
(`mcp/server.py`). The interactive view, PO automation, and the sales engine
call this and pin to this version. Per the build sequence, this contract must
not break once downstream skills start building against it.

**Run:** `UNRIVALED_CRM_STORE=/path/to/store python3 server.py` (stdio).
The store path is always a parameter — never hard-coded (Dylan owns his data).

Every response carries `ok` and `interface_version`. Failures return
`{ok: false, error: "..."}` — never exceptions across the wire.

## Reads (side-effect-free)

| Tool | Args | Returns |
|---|---|---|
| `get_company` | `ref` (id or name) | company + nested contacts, projects, shipments, needs_review flags |
| `list_companies` | `role?` (customer\|vendor), `query?` | filtered companies + count |
| `get_project` | `project_no` | project + company, contacts, shipments, needs_review flags |
| `list_projects` | `status?` (won\|pending\|lost), `owner?`, `year?`, `collection_status?` | filtered project cards + count |
| `list_shipments` | `stage?`, `company?`, `overdue?` | shipment legs + count |
| `get_vendor` | `ref` (id or name) | vendor with offerings + PO/invoice routing |
| `find_contacts` | `company?`, `query?` | contacts + count |
| `list_invoices` | `payment_status?` (paid\|open\|partial), `company?` | the receivables ledger (CLIENT Invoices table); invoices also attached to `get_company` |
| `crm_info` | — | version, store path, record counts, archived- and enriched-company counts |

Reads that scan companies (`list_companies`, `list_projects`, `list_shipments`,
`list_invoices`, `find_contacts`) exclude **archived** (soft-deleted) companies
and their records by default; pass `include_archived=true` to see them.
`get_company` always returns the record (archived or not) so it can be restored.

## Enrichment overlay (Phase 4)

| Tool | Args | Notes |
|---|---|---|
| `set_enrichment` | `company_id`, `data` | persists Outlook read-signal: `last_contact`, `threads[]` (subject/with/date/webLink), `meetings[]`, `source`; `refreshed_at` auto-set. Stored in `enrichment.json` as a non-destructive overlay — core records never touched. Attached to `get_company` responses. |

The **runner** is the CRM skill: it queries the read-only Outlook MCP
(email/calendar search per contact email), computes the signal, and persists
it via `set_enrichment`. The store never talks to Outlook for reads itself.

## Writes (validated, atomic, logged)

| Tool | Args | Notes |
|---|---|---|
| `update_project` | `project_no`, `fields` | status/owner/revenue/collection/notes…; enums enforced |
| `update_shipment` | `shipment_id`, `fields` | advance `stage`; set `ship_date`/`eta` |
| `upsert_contact` | `fields` | match by email, else (company_id, name); company must exist |
| `update_company` | `company_id`, `fields` | display_name, role, domains, locations |
| `create_project` | `fields` | requires unique `project_no` + existing `company_id` |
| `create_shipment` | `project_no`, `fields` | `shipment_id` auto-derived `<project_no>-L<n>`; defaults stage=Ordered |
| `create_company` | `fields` | add a customer or vendor; requires `display_name`, `role` defaults customer; `company_id` derived from name unless supplied, must be unique |
| `create_vendor` | `fields` | add a vendor: creates/reuses the company (role=vendor) + a vendor detail record (rep, email, phone, offerings, PO/invoice routing) |
| `update_vendor` | `company_id`, `fields` | edit vendor detail |
| `update_invoice` | `company_id`, `invoice_no`, `fields` | edit an invoice / customer order: `payment_status`, `pay_date`, `payment_notes`, `client_po_raw`. Matched by (company_id, invoice_no) — invoice numbers aren't guaranteed unique across companies. `invoice_date`/`project_no` and other identifying fields are not editable — they come from the original billing documents. |
| `rename_project` | `old_project_no`, `new_project_no` | change a project's number/key, cascading the update to every shipment (`project_no`/`all_project_nos`) and invoice (`project_no`) that references it — atomic, one write-locked operation. Fails if the new number is empty or already used by a different project. |
| `archive_company` | `company_id` | **soft-delete** a customer/vendor — hidden from the CRM, nothing destroyed; its projects/contacts/shipments/invoices are preserved |
| `restore_company` | `company_id` | un-archive a previously deleted customer/vendor, bringing it and its records back |
| `archive_project` | `project_no` | **soft-delete** a single project within a customer record — hidden from the CRM (`get_company`, `list_projects`, `list_shipments`, `list_invoices`), along with any shipment/invoice linked to it (`project_no`/`all_project_nos`); nothing destroyed |
| `restore_project` | `project_no` | un-archive a previously deleted project, bringing it and its linked shipments/invoices back |

**Delete = archive (reversible).** There is no hard-delete tool. Deleting a
customer, vendor, or single project sets `archived=true` (+ `archived_at`,
logged); the record and everything under it stay in the store and reappear on
`restore_company`/`restore_project`. The audit trail is never rewritten.

**Validation:** unknown fields rejected; `status` ∈ won|pending|lost;
`stage` ∈ Ordered|Shipped|Delivered|Installed|On Hold|Cancelled;
`collection_status` / `payment_status` ∈ paid|open|partial[:detail]; referential
integrity enforced (project→company, shipment→project).

**Write mechanics:** atomic temp-file + `os.replace`; every mutation appended
to `store/changelog.jsonl` with UTC timestamp, op, entity, key, fields.

**needs_review:** flags are surfaced on `get_company`/`get_project` and never
dropped by any write.

## Outlook actions (Phase 5 — live; spike passed 2026-07-02)

| Tool | Args | Notes |
|---|---|---|
| `draft_email` | `contact_email`, `subject?`, `body?` | creates a REAL Outlook draft (never sends); returns `webLink`. Contact keyed by email (the store's stable contact key). |
| `sync_outlook` | `company_id`, `dry_run?` | upserts the company's contacts natively into Outlook + tags CRM status categories (from its projects). Idempotent; never deletes; non-CRM categories preserved. `dry_run` returns the plan without writing. |

**Auth:** MSAL device-code with a persistent token cache
(`graph_login.py` once; silent thereafter). Config via `GRAPH_CLIENT_ID` /
`GRAPH_TENANT_ID` / `GRAPH_TOKEN_CACHE`. When unconfigured or signed out the
tools return a clear `ok:false` and the view falls back to compose links —
store writes are never affected.

**Guardrails:** the graph module physically cannot issue DELETE; drafts only,
never send; upserts keyed by email (no duplicates on re-run).

## Versioning

This is `v0.1`. Additive changes (new optional args, new fields) do not bump
the version. Renames, removals, or semantic changes require `v0.2` and a
migration note to every downstream consumer.

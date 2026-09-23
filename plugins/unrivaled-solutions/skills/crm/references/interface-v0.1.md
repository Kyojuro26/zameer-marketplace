# Unrivaled CRM Interface — v0.1 (pinned contract)

The stable read/write API exposed by the custom **Unrivaled CRM MCP**
(`mcp/server.py`). The interactive view, PO automation, and the sales engine
call this and pin to this version. Per the build sequence, this contract must
not break once downstream skills start building against it.

**Run:** `UNRIVALED_CRM_STORE=/path/to/store python3 server.py` (stdio).
The store path is always a parameter — never hard-coded (the operator owns
their data).

Every response carries `ok` and `interface_version`. Failures return
`{ok: false, error: "..."}` — never exceptions across the wire.

## Reads (side-effect-free)

| Tool | Args | Returns |
|---|---|---|
| `get_company` | `ref` (id or name) | company + nested contacts, projects, shipments, needs_review flags |
| `list_companies` | `role?` (customer\|vendor\|lead), `query?` | filtered companies + count |
| `get_project` | `project_no`, `company_id?` | project + company, contacts, shipments, needs_review flags. When two customers hold one number, `company_id` narrows the number to that customer's project before the ambiguity check: exactly one of theirs is used, none is "not found" (never the other customer's record), and the same customer holding the number twice is still refused; without it the call behaves exactly as before. With `company_id` the shipments listed leave out the other customer's legs on the number when two customers hold it (a leg with no company, or filed under a third, is listed); on a number one customer holds, every leg carrying it, as without. |
| `list_projects` | `status?` (won\|pending\|lost), `owner?`, `year?`, `collection_status?`, `next_action_due?` | filtered project cards + count. `next_action_due=true` keeps only projects whose `next_action_on` is today or earlier, not archived, status not lost — "what is due back today". |
| `list_shipments` | `stage?`, `company?`, `overdue?`, `vendor_po?`, `vendor_id?` | shipment legs + count. `vendor_id` keeps the legs filed under that vendor (exact id). A leg is hidden only when EVERY project it links to is archived, so deleting one deal does not hide a leg another live deal still owns. |
| `get_vendor` | `ref` (id or name) | vendor with offerings + PO/invoice routing, plus `open_legs`: the shipment legs filed under it (`vendor_id`) that are not Delivered, Installed or Cancelled |
| `find_contacts` | `company?`, `query?` | contacts + count |
| `list_invoices` | `payment_status?` (paid\|open\|partial), `company?`, `invoice_no?`, `overdue?` | the receivables ledger (CLIENT Invoices table); invoices also attached to `get_company`. Every invoice carries a computed `effective_due_on` — the `due_on` override if set, else `invoice_date` + Net 30. It is response-only and never stored; an `invoice_date` the server cannot parse yields `null` rather than a guessed date. |
| `list_tracker` | — | the Live Tracker's importer-written files: `tracker_buckets` (the status buckets, named from the sheet's own legend) and `tracker_unlinked` (rows the importer could not match to a project). Both are rewritten wholesale by every import. Each unlinked row carries a `fingerprint` — a hash of its own content, stamped by the importer and the only handle a dismissal is keyed on — plus `dismissed`/`reason_dismissed`, which are DERIVED here from `tracker_dismissed.json` and never stored authoritatively on the row. Neither file is an entity file, so their absence is normal on a store seeded before the tracker and returns empty lists rather than an error; a *corrupt* one still reports `ok:false`. |
| `dismiss_tracker_row` | `fingerprint`, `reason?` (`not_a_job` \| `already_adopted`) | takes a row off the "Not in the CRM yet" list. Adoption needs no tool of its own: `create_project` is enough, because a row whose number is now a live project is retired by the next import. The row is not deleted — it stays on screen under "Dismissed" with a count and a way back. Refuses a fingerprint that is not on the **current** sheet. |
| `restore_tracker_row` | `fingerprint` | undo a dismissal |
| `renumber_duplicate_shipments` | `shipment_id` | give each leg sharing one id its own id, so they can be edited again. Stores migrated before v0.1.28 can hold several legs under one `shipment_id` — the importer restarted its leg counter per row, so a project number on two open-order rows minted the same id twice. `update_shipment` and `reassign_shipment` refuse such a leg outright (they cannot tell which one you mean) and the app opens whichever comes first, so there was no way to edit them at all. The first leg keeps the id; the rest take free `-L<n>` suffixes. Nothing else changes, and each leg's vendor PO is reported so you can tell them apart. |
| `crm_info` | — | version, store path, record counts, archived- and enriched-company counts |
| `lookup_number` | `n` | every typed record answering to the number `n` (v0.1.38): `project` (with company), `crm_invoice` (the number after `INV` in a composite like `1342 (INV 1191-PAID)`; the leading number is the quote), `vendor_po_on_leg` (digits OUTSIDE the leg's parentheses; with the leg's job and vendor), and from the QuickBooks snapshots `qbo_invoice`, `qbo_po` and `qbo_bill` (one per vendor and number, lines summed; a bill's Num is the vendor's own invoice number, not a PO). Each labelled by `type`; nothing collapsed. `snapshot_errors` when a snapshot cannot be read. Read-only. |
| `qbo_snapshot_info` | — | per kind (`invoices`, `vendor_transactions`, `cash_balances`): `loaded`, `source`, `as_of`, `window_start`/`window_end`, `rows`, `loaded_at`, `age_days`, `stale` (> 7 days); an unreadable snapshot is `loaded: false` with `error`. |
| `crm_metrics` | `report?` (customer_concentration\|receivables_ageing\|vendor_on_time\|qbo_drift), `year?` | cross-record metrics (v0.1.36). Every derived number here — and every `metrics` object attached to a project or company by `get_project`, `list_projects`, `get_company`, `list_companies` — is one shape: `{value, unit, counted, population, excluded: {reason: n}, basis, as_of?}`. `counted + Σexcluded == population`; `value` is `null` exactly when `counted` is 0 (a denominator of zero never renders as $0; a fully paid customer is a real 0); each record is excluded for ONE reason from a closed vocabulary (`no_project_link`, `no_revenue_on_project`, `multiple_invoices_on_project` — a project carrying more than one invoice is excluded rather than priced at its full revenue once per invoice; `receivables_ageing` lists those projects under `multiple_invoices` — `paid`, `no_date`, `no_vendor_on_leg`, `ship_date_is_estimate`, …); anything derived from revenue minus cost says `quoted`. Per-record: `project.metrics.cycle_time_days`; `company.metrics.{revenue_won_usd, quoted_gross_profit_usd, exposure_open_receivable_usd, oldest_overdue_days}`. Computed on read, never stored; `metrics` is refused by every create and update. `year` applies to `customer_concentration` only. |

Reads that scan companies (`list_companies`, `list_projects`, `list_shipments`,
`list_invoices`, `find_contacts`) exclude **archived** (soft-deleted) companies
and their records by default; pass `include_archived=true` to see them.
`get_company` always returns the record (archived or not) so it can be restored.

## Enrichment overlay (Phase 4)

| Tool | Args | Notes |
|---|---|---|
| `set_enrichment` | `company_id`, `data` | persists Outlook read-signal: `last_contact`, `threads[]` (subject/with/date/webLink/message_id — the last field is what `draft_reply` targets; older or unenriched-since threads simply won't have it), `meetings[]`, `source`; `refreshed_at` auto-set. Stored in `enrichment.json` as a non-destructive overlay — core records never touched. Attached to `get_company` responses. |

The **runner** is the CRM skill: it queries the read-only Outlook MCP
(email/calendar search per contact email), computes the signal, and persists
it via `set_enrichment`. The store never talks to Outlook for reads itself.

## QuickBooks snapshots (v0.1.38 — outside the store)

Nothing here talks to QuickBooks. Data arrives as a file the operator exported,
or as rows a chat session read from the Intuit connector. Each kind is one
JSON file in `qbo-snapshots`, a SIBLING of the store folder, replaced wholesale
on every load (`kind`, `source` export|connector, `as_of`, `window_start`,
`window_end`, `loaded_at`, `rows`; amounts in integer cents). Loading writes no
store file and no changelog line; the store backup does not include it.

| Tool | Args | Notes |
|---|---|---|
| `load_qbo_export` | `path` | an Invoice List by Date or Transaction List by Vendor `.xlsx`, told apart by its header row. Returns `kind`, `rows`, `by_type`, `as_of` (the report's run time from its footer), `window_start`/`window_end` (title row 3). A file that is neither is refused with `found_header`; nothing is loaded partially. |
| `load_qbo_rows` | `kind`, `rows`, `as_of`, `window_start`, `window_end` | the connector path. Dates ISO (`YYYY-MM-DD`). Refused whole on the first bad row: unknown fields, non-integer cents, a missing required field, a duplicate. Row schema below — **provisional until the connector's real output has been checked.** |

Row schema (`?` = may be null; *optional* fields may be omitted and never come from an export):

- `invoices`: `type`, `num`, `date`, `due_date?`, `name?`, `amount_cents`, `open_cents`; optional `id`, `memo?`. `(type, num)` unique through the server's key.
- `vendor_transactions`: `vendor`, `date`, `type`, `num?`, `posting?` (bool), `account?`, `split_account?` (null = split across several accounts, never guessed), `amount_cents?`; optional `id`, `memo?`, `track_1099?`, `linked_po?` (Bill only), `customer_ref?` (Expense only), `open_status?` (`open`\|`closed`, Purchase Order only).
- `cash_balances`: `account`, `balance_cents`; optional `id`, `account_type?`. `account` unique.

Joined at read time, never stored: `company.metrics.invoiced_usd` and
`qbo_open_receivable_usd` (QuickBooks basis, beside — never blended into — the
quoted `exposure_open_receivable_usd`; `value_cents` exact, plus
`snapshot_as_of`, window, `age_days`, `stale`), `company.metrics.qbo_invoices`
and per invoice in `get_company`/`list_invoices`: `qbo_amount_usd`,
`qbo_open_usd`. The key is `(Invoice, number)`; reasons `no_qbo_snapshot`,
`ambiguous_qbo_match` (two rows, never one picked), `partial_qbo_match` (a CRM invoice numbered as exactly two invoices joined by `and`/`&`, e.g. `1152 and 1153`, prices as the sum of both only when BOTH are in the snapshot; one alone prices nothing), `qbo_match_shared` (one QuickBooks invoice claimed by more than one live CRM invoice — e.g. two customers each holding a "7001"; counted for neither, never twice), `outside_snapshot_window`
(never read as missing), `not_in_qbo_snapshot`. `crm_metrics(report="qbo_drift")`
is the two-way drift list: QuickBooks invoices no CRM invoice carries, and CRM
invoices in the window QuickBooks lacks, with counts and dollars.

## Writes (validated, atomic, logged)

| Tool | Args | Notes |
|---|---|---|
| `update_project` | `project_no`, `fields`, `company_id?` | status/owner/revenue/collection/notes…; enums enforced. `next_action` (text) and `next_action_on` (a date, stored as given) are the operator's own "by when": a re-import never overwrites them; a non-date `next_action_on` is refused. When two customers hold one number, `company_id` narrows the number to that customer's project before the ambiguity check: exactly one of theirs is used, none is "not found" (never the other customer's record), and the same customer holding the number twice is still refused; without it the call behaves exactly as before. A `company_id` inside `fields` still MOVES the project, and is refused when the destination customer already holds the number. |
| `update_shipment` | `shipment_id`, `fields` | advance `stage`; set `ship_date`/`eta`/notes/vendor PO/`vendor_id` (must name a vendor record at a live company, or null to clear; a leg's vendor is set at import from the PO text by `pipeline/vendor_match.py` -- exact name or `vendor_aliases.json`, never a guess -- and `pipeline/backfill_leg_vendors.py` does the same for legs already in the store). **Cannot re-link the leg** — `project_no`, `all_project_nos` and `linked_to_project` are refused here; use `reassign_shipment`, which validates the target project is live and keeps the three consistent. |
| `reassign_shipment` | `shipment_id`, `new_project_no`, `also_project_nos` | move a leg to another project, or pass `new_project_no=None`/`""` to unlink it entirely. `also_project_nos` sets the secondary links for a leg that genuinely serves several projects; every number must name a live project. |
| `rename_invoice` | `company_id`, `old_invoice_no`, `new_invoice_no` | change an invoice's own number, cascading to any shipment leg carrying it. Refused if the new number is empty or already used by another invoice for the same company, **or if two invoices already share the old number** — it cannot tell them apart, and renaming one would drag the other's legs along. |
| `upsert_contact` | `fields` | add or update a contact. Matched **within that customer** by email, else by name — an address another customer already uses no longer moves their contact record. The company must exist and must not be archived. |
| `update_company` | `company_id`, `fields` | display_name, role, domains, locations |
| `create_project` | `fields` | requires unique `project_no` + existing `company_id`; may carry `next_action` / `next_action_on` |
| `create_shipment` | `project_no`, `fields`, `company_id?` | `shipment_id` auto-derived `<project_no>-L<n>`; defaults stage=Ordered. When two customers hold one number, `company_id` narrows the number to that customer's project before the ambiguity check: exactly one of theirs is used, none is "not found" (never the other customer's record), and the same customer holding the number twice is still refused; without it the call behaves exactly as before. |
| `create_company` | `fields` | add a customer, vendor or lead; requires `display_name`, `role` defaults customer; `company_id` derived from name unless supplied, must be unique |
| `create_vendor` | `fields` | add a vendor: creates/reuses the company (role=vendor) + a vendor detail record (rep, email, phone, offerings, PO/invoice routing) |
| `update_vendor` | `company_id`, `fields` | edit vendor detail |
| `create_invoice` | `company_id`, `fields` | add a client invoice that never came through the tracker workbook. `invoice_no` required and unique for that customer; a supplied `project_no` must name a live (non-archived) project; `payment_status` defaults to `open`. `payment_status_raw`/`sheet_row` are importer provenance and cannot be set. |
| `update_invoice` | `company_id`, `invoice_no`, `fields` | edit an invoice / customer order: `payment_status`, `pay_date`, `payment_notes`, `client_po_raw`, `due_on`, and (v0.1.26+) `invoice_date`, `project_no`. Matched by (company_id, invoice_no) — invoice numbers aren't guaranteed unique across companies. A `project_no` must name a live project. The invoice's own number is changed with `rename_invoice`. `payment_status_raw`/`sheet_row` stay locked — they record what the source workbook said. Setting a `project_no` that is also a vendor PO (on a leg, or a PO in the QuickBooks snapshot) still writes, and the response carries `warnings: [{code: "number_is_also_vendor_po", source, vendor, job, message}]`; `create_invoice` does the same. |
| `rename_project` | `old_project_no`, `new_project_no`, `company_id?` | change a project's number/key, cascading the update to every shipment (`project_no`/`all_project_nos`) and invoice (`project_no`) that references it — atomic, one write-locked operation. Fails if the new number is empty or already used by a different project. When two customers hold one number, `company_id` narrows the number to that customer's project before the ambiguity check: exactly one of theirs is used, none is "not found" (never the other customer's record), and the same customer holding the number twice is still refused; without it the call behaves exactly as before. With `company_id` the cascade leaves behind the other customer's shipments and invoices when two customers hold the number, live or archived, and carries everything else on it (a record with no company, or filed under a third); on a number one customer holds it carries every record on it, as without. The new number must still be unused store-wide. |
| `convert_lead` | `company_id` | promote a lead to a customer (role lead -> customer); everything already recorded against it is kept |
| `archive_company` | `company_id` | **soft-delete** a customer/vendor — hidden from the CRM, nothing destroyed; its projects/contacts/shipments/invoices are preserved |
| `restore_company` | `company_id` | un-archive a previously deleted customer/vendor, bringing it and its records back |
| `archive_project` | `project_no`, `company_id?` | **soft-delete** a single project within a customer record — hidden from the CRM (`get_company`, `list_projects`, `list_shipments`, `list_invoices`), along with any shipment/invoice linked to it (`project_no`/`all_project_nos`); nothing destroyed. When two customers hold the number and one twin is archived, only records filed under that customer hide; the live twin's stay |
| `restore_project` | `project_no`, `company_id?` | un-archive a previously deleted project, bringing it and its linked shipments/invoices back. When two customers hold one number, `company_id` narrows the number to that customer's project before the ambiguity check: exactly one of theirs is used, none is "not found" (never the other customer's record), and the same customer holding the number twice is still refused; without it the call behaves exactly as before. (`archive_project` takes the same optional `company_id`, with the same rule.) |

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
| `draft_reply` | `company_id`, `message_id`, `comment?`, `reply_all?` | creates a REAL Outlook draft reply to one specific message (never sends) -- Graph auto-fills the correct recipient(s) and quotes the original, unlike `draft_email`'s blank new message. `message_id` comes from that company's `enrichment.threads[].message_id` (only present on threads enriched after this feature shipped). Returns `webLink`. `reply_all` uses createReplyAll instead of createReply. |
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

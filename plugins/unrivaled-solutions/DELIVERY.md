# Delivery Note — CRM v0.1.0 (plugin release 1 of 5)

_Prepared 2026-07-02. Engineering contact: Zeeshan (Zameer)._

## What was built

An Outlook-based CRM over the Unrivaled sales tracker: a normalization
pipeline (workbook → clean records), a maintained store fronted by a custom
MCP (the `unrivaled-crm` server — 14 tools, read + write, interface v0.1,
atomic writes, append-only changelog), native Outlook integration (real
email drafts, contact/category sync, per-company activity enrichment), and
an interactive visual app (navigate, edit-in-place, create records, advance
shipment stages, click-to-draft).

## Verification status

- Interface suite: **40/40** (round-trips, validation, referential
  integrity, changelog) — runs against a scratch copy, never live data.
- Outlook write layer: **20/20** mocked (idempotency, payloads, no-delete
  guardrail) + **live smoke passed** on the sandbox tenant 2026-07-02
  (draft created & verified in mailbox, sync idempotent, cleanup clean).
- Visual app end-to-end: **23/23** (headless browser driving the real UI;
  every save verified on disk; demo mode provably cannot touch data).

## Acceptance test (run at install, Phase 8)

1. Open a company → drill into a project's details.
2. Edit the project (status/notes) → reload → the edit persisted.
3. Advance a shipment stage → visible in the store + changelog.
4. Create a project, a contact, a shipment from the UI.
5. Click a contact → a real draft appears in Outlook Drafts.
6. `sync_outlook` a company → contacts + categories appear in Outlook;
   re-run → no duplicates.
7. Counts reconcile against the workbook analysis; walk the
   `needs_review` list together.

## Known gaps & flagged items

- **Company creation** isn't in the visual app yet (new projects attach to
  existing companies); planned for the next update.
- **Saved views** (open receivables, stalled shipments) — next update.
- **Duplicate companies**: 27 clusters awaiting Dylan's A/B/C labels
  (doc delivered 2026-07-02); merges apply after labeling.
- **Rep legend** (D/G → names) still pending from Dylan — owners display
  as initials until then.
- Two records flagged `needs_review` with no company: project 1395
  ("31W Insulation" with a pickup note glued on) and contact Matt Kannapel.
- 143 of 182 shipments have no project link — **by design** (shipments are
  keyed by vendor PO; confirmed with Dylan 2026-07-02), shown as
  "unlinked" in the app.

## Delivery-day runbook (engineer)

1. Fresh migration: `normalize.py` on Dylan's current workbook → his store
   folder (OneDrive-synced), apply duplicate labels + rep legend.
2. Outlook contacts ingest + changelog replay (delivery kit — to be built).
3. Entra app registration in Dylan's tenant + `graph_login.py` on his
   machine; connect the M365 connector.
4. Install plugin from the private marketplace; set env vars.
5. Run the acceptance test above on his real data.

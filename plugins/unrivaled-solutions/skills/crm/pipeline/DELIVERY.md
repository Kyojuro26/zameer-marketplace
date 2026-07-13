# Phase 1 — Normalization pipeline · delivery note

**What was built.** `normalize.py` — a deterministic, re-runnable pipeline that reads the legacy `US-Sales Tracker-2026.xlsx` and emits the normalized store (`store/*.json`): companies, contacts, projects, shipments, vendors, and a `needs_review.json`. Workbook path and output dir are parameters; nothing is hard-coded to Dylan's data.

**Run.**
```
python3 pipeline/normalize.py --workbook "US-Sales Tracker-2026 .xlsx" --out ./store
```

**What it produces (against the real workbook).**

- 426 companies (49 vendors), 369 contacts, 189 numbered projects (+28 without a number), 182 shipments, 49 vendors.
- Both 2025 and 2026 deal history migrated. Won 132 / Pending 70.
- The messy Project Tracker key is parsed into three fields: `1318 (INV 1107-PAID)` → project# 1318, invoice# 1107, collection `paid`; `1351 (INV 1137-50%)` → `partial:50%` (real receivable).
- Rep tags → `owner` (D×16, G×6). Descriptive parentheticals are NOT treated as reps.
- Vendor PO + ship-date pairs exploded into 182 shipments; stage derived (Ordered/Shipped/On Hold).

**Acceptance checks passed.**

- Referential integrity: projects→company 188/189, contacts→company 368/369, shipments→company 174/182, **0 junk/date companies**.
- Parsing spot-checks correct on 1318, 1351, 1341, 1269, 1296, 1406.
- Shipment count (182) reconciles exactly with the source vendor-PO slot distribution.

**Known data realities (flagged in `needs_review.json`, not hidden).**

- **Only 39/182 shipments share a project# with the deal log.** Open-orders and deal-log numbers largely don't overlap in the source — a real workbook issue. The other 135 shipments are attached to a company by client name; 8 had no clean name and are unlinked.
- **28 possible-duplicate company clusters** from spelling drift (e.g. Vibracoustic appears several ways). Surfaced for merge review, never auto-merged.
- **21 projects without a project number**; 7 duplicate project numbers (kept, suffixed by year).
- A few non-numeric keys (`Word Proposal`, `Check`) flagged for Dylan.

**Flaky / unknown.**

- Client-name recovery from the drifting Project Tracker columns is heuristic; edge cases may mis-pick and are worth a spot review.
- Rep legend still pending from Dylan (D/G confirmed; display names TBD).
- `Delivered`/`Installed` stages aren't auto-derived (no structured source) — set later in-app.

**Next (Phase 2/3).** Wrap this store in the custom **Unrivaled CRM MCP** (read + write) so the interactive view can read and mutate it.

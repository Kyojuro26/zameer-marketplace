---
name: crm
description: >
  This skill should be used when the user asks about their customers,
  projects, deals, shipments, vendors, or receivables — for example "pull up
  Ace Manufacturing", "what's the status of project 4521", "mark that shipment
  delivered", "add a new project for Meridian Corp", "draft an email to Alex",
  "what's shipping this week", "who owes us money", or "refresh Outlook
  activity". It operates the Unrivaled CRM: reading and updating the CRM
  records, creating drafts in Outlook, and syncing contacts and statuses
  into Outlook.
metadata:
  version: "0.1.17"
---

# Unrivaled CRM

Operate the CRM through the `unrivaled-crm` MCP server (interface v0.1).
The CRM's records live in the user's own store folder; the MCP is the only
thing that reads or writes them. Full tool reference:
`references/interface-v0.1.md`.

## Core rules

- **Never send email.** `draft_email` creates drafts only; the user reviews
  and sends. Do not attempt to send through any other tool either.
- **Never delete Outlook data.** The tools cannot; do not try elsewhere.
- **Never guess.** Anything uncertain is flagged `needs_review` by the
  system — surface those flags to the user, don't resolve them silently.
- **Company is the primary unit.** Contacts and projects hang off a
  company; shipments hang off projects.

## Answering questions (reads)

Use the read tools; they are side-effect-free:

- A company overview → `get_company` (returns nested contacts, projects,
  shipments, Outlook enrichment, and review flags).
- "What's pending / won / lost" → `list_projects` with `status`; filter by
  `owner`, `year`, or `collection_status` as asked.
- "Who owes us" → `list_projects` with `collection_status="open"` and
  `"partial"` (both), plus any project whose collection status isn't paid.
- Shipments by stage or lateness → `list_shipments` (`overdue=true` for
  slipped ship dates).
- People → `find_contacts`; vendor routing → `get_vendor`.

Project numbers are the user's QuickBooks quote numbers. Shipments are
keyed by vendor PO numbers, not project numbers — some legitimately have no
project link (`linked_to_project: false`); that is by design, not an error.

## Making changes (writes)

Writes are validated and logged; report failures honestly:

- Update a deal → `update_project` (status won|pending|lost, collection,
  owner reps, notes, revenue).
- Advance a shipment → `update_shipment` (stage: Ordered → Shipped →
  Delivered → Installed, plus On Hold / Cancelled; ship_date, eta).
- New records → `create_project` (needs a unique project number and an
  existing company), `create_shipment` (attaches to a project),
  `upsert_contact` (deduped by email — safe to re-run).
- New customers/vendors → `create_company` (customer or vendor; unique name)
  and `create_vendor` (a vendor plus its detail record: rep, email, offerings,
  PO/invoice routing). Company details → `update_company`; vendor detail →
  `update_vendor`.
- **Deleting a customer or vendor → `archive_company`** (and `restore_company`
  to undo). Delete is a reversible archive: the record is hidden from the CRM
  but nothing is destroyed, and its projects/contacts/shipments/invoices are
  preserved. There is no hard delete. Confirm with the user before archiving,
  and tell them it can be restored.

## Outlook actions

- **Draft an email** from a contact → `draft_email(contact_email, subject?,
  body?)`. Returns a `webLink` — give it to the user to open. If the tool
  reports Outlook isn't configured, fall back to suggesting a mailto/compose
  link and tell the user Outlook drafts need one-time setup (see plugin
  README).
- **Push a company into Outlook** → `sync_outlook(company_id)`: upserts its
  contacts natively and tags them with CRM status categories. Run with
  `dry_run=true` first and show the plan when the user hasn't explicitly
  confirmed. Safe to re-run — it never duplicates and never deletes.

## Refreshing Outlook activity (enrichment)

When asked to refresh a company's Outlook signal ("when did we last talk
to…", "refresh Outlook activity"):

1. Query the connected Microsoft 365 / Outlook connector (read-only):
   search email by each store contact's address (sender and recipient),
   and calendar events mentioning the company or its contacts.
2. Compute: `last_contact` (newest message date), up to 5 recent `threads`
   (subject, with, date, webLink), upcoming/recent `meetings`.
3. Persist via `set_enrichment(company_id, data)` with an honest `source`.
   If nothing was found, write empty results — never invent activity.

## Bulk enrichment protocol

Never enrich all companies in one pass (426 companies; most inactive).
Prioritize: `list_projects status="pending"` plus current-year won — enrich
those companies first, in batches of ~10 per conversation, persisting each
batch via `set_enrichment` before starting the next. Enrichment must run on
the machine whose Microsoft 365 connector is signed into the mailbox that
holds the actual correspondence (production: Dillon's PC). Keep it current
with a weekly scheduled task: "refresh Outlook activity for companies with
open projects."

## Version check

`crm_info` returns `server_version`. If a fix or feature seems missing,
compare that against the marketplace version and update the plugin in
Settings -> Capabilities. Plugin updates never touch the store; data is safe.
Production data lives in ONE store (Dillon's PC). Any other machine's store
is a dev fixture — edits there are throwaway and must never be copied over
the production store.

The visual app runs from its own stable copy at `C:\UnrivaledCRM\app\`, not
from the plugin's install path, so it does **not** auto-update when the
plugin does. After confirming a plugin update via `crm_info`, also re-copy
`skills/crm/mcp` and `skills/crm/view` into `C:\UnrivaledCRM\app\skills\crm\`
if the update touched either — otherwise the desktop shortcut keeps running
old code with no indication anything's stale.

## Setup & update instructions

`references/setup-runbook.md` is the full step-by-step production setup
guide (install, Python fix, moving the store off OneDrive, the backup task,
Outlook credentials, the visual app, and a troubleshooting section keyed off
the launch log). If the user asks how to set up, install, update, or
troubleshoot the CRM on a new or existing machine, read that file and walk
them through the relevant section rather than improvising steps from
memory — it's kept current with the shipped version and is more reliable
than reconstructing setup mechanics from general knowledge.

## The interactive view

The CRM's visual interface is a real local application, not a chat artifact.
It runs via `mcp/local_server.py` — a token-authenticated localhost server
(bound to 127.0.0.1 only, fresh random token every launch) that serves the
app and lets it call the same validated MCP writes as above over an
authenticated HTTP call, so edits persist exactly like a chat-driven change.

**Do not try to render it as a Cowork artifact or "open" a generated HTML
file directly.** That was tried and confirmed not to work (2026-07-16):
no tested Cowork rendering surface — chat-inline preview, a chat's Outputs
panel, a persisted artifact gallery entry — exposes a usable
`window.cowork.callMcpTool` bridge to this plugin's tools. A file opened
that way always renders in read-only "Demo" mode with session-only edits,
which looks like it's broken even though nothing is actually wrong.

If the user asks to "open the CRM":
- If they already have it open in a browser tab, tell them to just use that
  tab — it refreshes its own data live on every load and doesn't need to be
  regenerated or reopened.
- If it isn't running, tell them to double-click the **"Open Unrivaled
  CRM"** shortcut on the desktop (created during setup — see the plugin
  README's "Local app setup" section). Do not try to launch it yourself
  from chat; there's no reliable way to background a long-running local
  server from a Cowork tool call, and the shortcut already handles store
  resolution and browser launch correctly.
- If there's no shortcut yet, that's a one-time setup step, not something
  to improvise — point the user at the README's "Local app setup"
  instructions rather than guessing at a path.

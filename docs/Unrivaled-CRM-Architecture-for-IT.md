# Unrivaled CRM — Architecture & Data Handling (for IT)

_A one-page technical overview for Unrivaled Solutions' IT. Prepared by Zameer._

## Summary

The Unrivaled CRM is a **local, file-based application** that runs on the
operator's (Dylan's) own PC inside the Claude desktop app. There is **no
database server, no hosted backend, and no third-party service storing the CRM
data.** Nothing needs to be provisioned, hosted, or opened to the network.

## How it runs

- It installs as a plugin to the **Claude desktop app** and runs as a local
  Python subprocess on Dylan's machine.
- **No inbound network ports, no server, no listening service.** It is not
  reachable from the network.
- Software requirements: Windows + Python 3 (Microsoft Store build), the Claude
  desktop app with a paid seat. That's it.

## Where the data lives (no database)

- The system of record is a set of **plain JSON files** in a single folder that
  Dylan owns — recommended location: his **OneDrive** (e.g.
  `…\OneDrive\Unrivaled-CRM\store`).
- Files: customers, contacts, projects, shipments, invoices, vendors, plus an
  append-only change log for auditing.
- **Backup is handled by OneDrive** — the folder is covered by your existing
  Microsoft 365 backup/retention. No separate backup system is required.
- Data never leaves Dylan's environment. It is **not** stored in any cloud CRM,
  SaaS, or third-party database.

## Data integrity

- Every write is **atomic** (write-to-temp then replace), so an interruption
  cannot corrupt the store.
- Every change is recorded in an **append-only audit log** (who/what/when).

## Microsoft 365 / Outlook access (optional feature)

Two independent, least-privilege integrations — both act only on Dylan's own
mailbox, on his behalf:

**1. Outbound (creating drafts + syncing contacts) — Entra app registration.**
- **Delegated** Microsoft Graph permissions only: `Mail.ReadWrite`,
  `Contacts.ReadWrite`, `MailboxSettings.ReadWrite`.
- **No `Mail.Send`** — the app physically cannot send email; it only creates
  **drafts** that Dylan reviews and sends himself.
- Uses the **device-code (public client) flow — no client secret or certificate**
  to store or rotate. Sign-in honors your MFA / conditional access.
- Acts as the signed-in user on his own mailbox; no org-wide/application access.

**2. Inbound (recent activity per customer) — read-only M365 connector.**
- A separate, **read-only** Microsoft 365 connector (its own admin-consent
  prompt at connect time).
- Reads recent email/calendar activity to show, per customer, the last contact
  date, recent thread subjects/dates, and **links back to the real emails** in
  Outlook. It **does not copy message bodies** into the CRM, and it never
  modifies or deletes anything in Outlook.

## What is and isn't stored

- **Stored (locally):** the CRM records above, and lightweight Outlook *activity
  metadata* (subject, date, participant, a link).
- **Not stored:** full email bodies, attachments, or any Outlook content — those
  stay in Microsoft 365. No credentials are stored beyond a local, permission-
  restricted sign-in token cache on Dylan's machine.

## Software distribution

- The plugin **code** is delivered from a **private GitHub repository**
  (`Kyojuro26/zameer-marketplace`) that Dylan installs from with read access.
- The **data folder is never published** to GitHub or bundled in the plugin —
  code and data are strictly separated.

## Security posture, in brief

Local-only data · no database or server to harden · least-privilege delegated
Graph scopes · drafts-only (cannot send) · read-only inbound (cannot modify
Outlook) · no stored secret · atomic writes with an audit trail · anything the
system is unsure about is flagged for human review, never guessed.

_Questions: Zeeshan Bhatti — zeeshan@zameer.io_

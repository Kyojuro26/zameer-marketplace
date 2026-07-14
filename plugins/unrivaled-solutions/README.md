# Unrivaled Solutions Plugin

Operations plugin for Unrivaled Solutions. This release ships **skill #1 of 5:
the CRM** — an Outlook-based system over your sales tracker data. PO
automation, the AI sales engine, knowledge base, and bank reconciliation
arrive as updates to this same plugin.

## What the CRM does

- Navigate every customer: contacts, projects (deals), shipments, receivables.
- Edit records and have the edits **persist** — status, collection, owners,
  notes, shipment stages — with every change logged to an audit trail.
- Add new projects, contacts, and shipments.
- Click a contact to open a **real Outlook draft** (never auto-sent).
- Push a company's contacts + CRM status categories natively into Outlook.
- See per-company Outlook activity: last contact, recent threads, meetings.
- An interactive visual app (single HTML file) with search, drill-down,
  in-place editing, and a Live/Demo indicator.

## Components

| Component | What it is |
|---|---|
| `crm` skill | Teaches Claude to operate the CRM conversationally |
| `unrivaled-crm` MCP server | The only reader/writer of your CRM records (14 tools, interface v0.1) |

## Setup (one time, ~10 minutes)

**1. Requirements.** Python 3.10+ with three packages:

```bash
pip3 install mcp msal requests
```

**2. Your data folder.** Your CRM records live in a folder YOU own (it can
be inside OneDrive so it's backed up). Set its location as an environment
variable before starting Claude:

```bash
export UNRIVALED_CRM_STORE="$HOME/Unrivaled-CRM/store"
```

The initial records are migrated from your sales tracker workbook by the
delivery engineer (pipeline/normalize.py) — you don't run that yourself.

**3. Outlook drafts & sync (optional but recommended).** Requires a one-time
app registration in your Microsoft 365 tenant (your admin: ~2 minutes —
instructions in `skills/crm/mcp/graph_login.py` header and the delivery
note), then:

```bash
export GRAPH_CLIENT_ID="<your app's client id>"
export GRAPH_TENANT_ID="<your tenant id>"
python3 skills/crm/mcp/graph_login.py --store "$UNRIVALED_CRM_STORE"
```

Sign in once with the device code; after that everything is silent. Without
this step the CRM still fully works — click-to-draft just falls back to a
compose link.

**4. Outlook activity (optional).** Connect the Microsoft 365 connector in
Claude's connector settings (read-only) so Claude can refresh last-contact
dates, threads, and meetings per company.

## Usage

Just talk to Claude:

- "Pull up Vibracoustic" / "what's the status of project 1318"
- "Mark shipment 1352-L1 delivered"
- "Add a new project for Ford — racking install, $12k, rep D"
- "Draft an email to Jeff Haysley"
- "Sync Ford into my Outlook"
- "Open the CRM" — the visual app

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `UNRIVALED_CRM_STORE` | Yes | Path to your CRM data folder |
| `GRAPH_CLIENT_ID` | For Outlook writes | Your tenant's app registration |
| `GRAPH_TENANT_ID` | For Outlook writes | Your Microsoft 365 tenant |

## Guarantees

Your data stays yours (a folder you own; nothing hard-coded). Drafts only —
nothing is ever sent on your behalf. Outlook data is never deleted. Anything
the system isn't sure about is flagged for your review, never guessed.


## Dev/prod protocol (2026-07-14)

- **Production data = Dillon's store** (`C:\UnrivaledCRM\store`, pointed to by
  `~\.unrivaled-crm-store`; daily robocopy backup into OneDrive `CRM-Backups`).
  Zeeshan's Mac store is a dev fixture. Data never moves between machines.
- **Code flows one way:** edit build -> rsync into zameer-marketplace clone
  (publish.sh exclusions) -> bump `plugin.json` version -> push `main` ->
  Dillon updates in Settings -> verify with "crm info" (`server_version`).
- **Never ship store data.** Pipeline (`normalize.py`) output must never
  overwrite a live store. Schema changes ship as server migrations (e.g.
  v0.1.5 auto-creates missing entity files).
- **No env vars, ever.** Claude spawns plugin servers with a sanitized env.
  Store path: `~/.unrivaled-crm-store` pointer file. Graph/Outlook creds:
  `.graph_config.json` inside the store. Launch diagnostics:
  `unrivaled-crm-launch.log` in the OS temp dir.

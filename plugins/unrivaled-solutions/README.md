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
| Visual app (`local_server.py`) | Same records, in a real local web app — see setup step 5 |

## Setup (one time, ~10 minutes)

**1. Requirements.** Python 3.10+ with three packages:

```bash
pip3 install mcp msal requests
```

**2. Your data folder.** Your CRM records live in a folder YOU own. Keep the
live store OUTSIDE OneDrive (sync locks break saves); back it up INTO OneDrive
with a scheduled robocopy task instead — **excluding the `.secrets` subfolder**,
which holds your Outlook sign-in token, so a mailbox-access credential never
ends up in synced cloud storage:

```powershell
# Scheduled Task action — run daily. /XD excludes the whole .secrets directory.
robocopy "C:\UnrivaledCRM\store" "$env:OneDrive\CRM-Backups" /MIR /XD .secrets
```

Tell the plugin where the store is by writing its path into a pointer file in
your home directory (env vars never reach the server — Claude spawns it with a
sanitized environment):

```powershell
# Windows (PowerShell) — ASCII avoids BOM/UTF-16 surprises
Set-Content -Path "$HOME\.unrivaled-crm-store" -Value "C:\UnrivaledCRM\store" -Encoding Ascii
```

```bash
# macOS/Linux
printf '%s' "$HOME/Unrivaled-CRM/store" > ~/.unrivaled-crm-store
```

The initial records are migrated from your sales tracker workbook by the
delivery engineer (pipeline/normalize.py) — you don't run that yourself.

**3. Outlook drafts & sync (optional but recommended).** Requires a one-time
app registration in your Microsoft 365 tenant (your admin: ~2 minutes —
instructions in `skills/crm/mcp/graph_login.py` header and the delivery
note), then create `.graph_config.json` inside a `.secrets` subfolder of the
store (plain UTF-8 JSON — not `Out-File`, which writes UTF-16). This folder is
what the backup command above excludes, so create it explicitly:

```powershell
New-Item -ItemType Directory -Force -Path "C:\UnrivaledCRM\store\.secrets" | Out-Null
Set-Content -Path "C:\UnrivaledCRM\store\.secrets\.graph_config.json" -Encoding Ascii -Value '{"client_id": "<app client id>", "tenant_id": "<tenant id>"}'
```

(Upgrading from an older version? The server auto-migrates an existing
`.graph_config.json`/`.graph_token_cache.json` from the top of the store into
`.secrets/` the first time it runs — no action needed, but double-check your
scheduled backup task already has the `/XD .secrets` flag above, since that's
a one-time manual edit to the task itself.)

Then sign in once:

```bash
python3 skills/crm/mcp/graph_login.py --store "C:\UnrivaledCRM\store"
```

Sign in once with the device code; after that everything is silent. Without
this step the CRM still fully works — click-to-draft just falls back to a
compose link.

**4. Outlook activity (optional).** Connect the Microsoft 365 connector in
Claude's connector settings (read-only) so Claude can refresh last-contact
dates, threads, and meetings per company.

**5. The visual app (recommended, one-time setup, ~2 minutes).** The
interactive CRM view is a real local application, not a Cowork artifact —
Cowork does not currently expose a way for a rendered artifact to call back
into a plugin's tools, so this runs as its own token-authenticated localhost
server instead (bound to 127.0.0.1 only; a fresh random token every launch;
never reachable from the network or from any other page in your browser).

Copy the app files out of the plugin into a stable folder — ask Claude to
"copy the CRM plugin's skills/crm/mcp and skills/crm/view folders into
C:\UnrivaledCRM\app\skills\crm\{mcp,view}" (the plugin's own install path
moves around between updates, so Claude locating it live is more reliable
than a hardcoded path). Then create a desktop shortcut:

```powershell
# Save as "Open Unrivaled CRM.bat" on the Desktop
@"
@echo off
cd /d "C:\UnrivaledCRM\app\skills\crm\mcp"
python3 local_server.py
pause
"@ | Set-Content -Path "$env:USERPROFILE\Desktop\Open Unrivaled CRM.bat" -Encoding Ascii
```

Double-click it whenever you want the CRM open — it reads the same store
pointer file as everything else and opens your browser automatically. The
header shows **"Live · edits persist (local app)"** when it's working.
Leave the console window open while you use the app; closing it shuts the
server down. If the header ever says "Demo" instead, close and reopen from
the shortcut rather than the browser's back button — that means it didn't
find a live backend on that load.

## Usage

Just talk to Claude:

- "Pull up Ace Manufacturing" / "what's the status of project 4521"
- "Mark shipment 4521-L1 delivered"
- "Add a new project for Meridian Corp — racking install, $12k, rep D"
- "Draft an email to Alex Rivera"
- "Sync Meridian Corp into my Outlook"

Or use the visual app directly — double-click "Open Unrivaled CRM" on the
desktop (see setup step 5). Both talk to the same store; use whichever's
convenient.

## Configuration files (no env vars — see Dev/prod protocol)

| File | Required | Purpose |
|---|---|---|
| `~/.unrivaled-crm-store` | Yes | One line: path to your CRM data folder |
| `<store>/.secrets/.graph_config.json` | For Outlook writes | `{"client_id": ..., "tenant_id": ...}` — exclude `.secrets` from any backup |

## Guarantees

Your data stays yours (a folder you own; nothing hard-coded). Drafts only —
nothing is ever sent on your behalf. Outlook data is never deleted. Anything
the system isn't sure about is flagged for your review, never guessed. If two
Cowork windows (or a Cowork window and the visual app) edit the CRM at the
same moment, the store is locked for the instant it takes to save — you'll
see a "try again in a moment" message instead of one edit silently
overwriting the other.

The visual app's local server binds to 127.0.0.1 only (never reachable from
your network), requires a fresh random token every launch that only that
browser tab knows, and doesn't allow cross-origin requests — another tab or
site open in your browser cannot call it even though it's running on your
machine.


## Dev/prod protocol (2026-07-14)

- **Production data = Dillon's store** (`C:\UnrivaledCRM\store`, pointed to by
  `~\.unrivaled-crm-store`; daily robocopy backup into OneDrive `CRM-Backups`,
  `/XD .secrets` so the Outlook token never leaves his machine).
  Zeeshan's Mac store is a dev fixture. Data never moves between machines.
- **Code flows one way:** edit build -> rsync into zameer-marketplace clone
  (publish.sh exclusions) -> bump `plugin.json` version -> push `main` ->
  Dillon updates in Settings -> verify with "crm info" (`server_version`).
  The visual app's copy at `C:\UnrivaledCRM\app\` does NOT auto-update with
  the plugin (it's a stable copy, deliberately outside the plugin's
  ever-changing install path) — after any version bump that touches
  `skills/crm/mcp/local_server.py`, `server.py`, or `skills/crm/view/`,
  re-run the copy step from the README's setup section 5, or the desktop
  shortcut keeps launching old code indefinitely with no warning that it's
  stale.
- **Never ship store data.** Pipeline (`normalize.py`) output must never
  overwrite a live store. Schema changes ship as server migrations (e.g.
  v0.1.5 auto-creates missing entity files, v0.1.9 relocates secrets into
  `.secrets/` with an automatic one-time migration).
- **No env vars, ever.** Claude spawns plugin servers with a sanitized env.
  Store path: `~/.unrivaled-crm-store` pointer file. Graph/Outlook creds:
  `.secrets/.graph_config.json` inside the store — kept in a subfolder so a
  whole-store backup can exclude it with one flag. Launch diagnostics:
  `unrivaled-crm-launch.log` in the OS temp dir.

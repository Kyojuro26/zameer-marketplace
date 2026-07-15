# Unrivaled CRM — Setup on Dylan's Machine (Windows / HP)

_Run top to bottom on Dylan's Windows PC during the setup session. ~20–30 min.
Everything runs on his machine (his data stays his). Use **PowerShell**
(Start → type "PowerShell" → Enter). The Outlook half is Part 5._

---

## Part 0 — Before you start (have these ready)

- Dylan's **latest Sales Tracker workbook** (the .xlsx).
- Dylan **logged into GitHub** in his browser, with **read access** to
  `Kyojuro26/zameer-marketplace` → *you grant this first:* repo → Settings →
  Collaborators → add his GitHub user.
- For Outlook (Part 5): his **Microsoft 365 admin** available (~2 min).

## Part 1 — Install Python (the right way for Windows)

The plugin's engine launches as `python3`. On Windows that command only exists
if Python comes from the **Microsoft Store**, so use that:

1. Open **Microsoft Store** → search **Python 3.12** (or latest) → **Get**.
2. In PowerShell, confirm **both** of these print a version:
   ```powershell
   python --version
   python3 --version
   ```
   If `python3` errors, the Store install didn't register it — ping me and I'll
   give you a 2-line `python3` shim. Don't proceed until `python3` works.
3. Install the packages the CRM needs:
   ```powershell
   python -m pip install mcp msal requests openpyxl
   ```

## Part 2 — Install the plugin (in Cowork)

```
/plugin marketplace add Kyojuro26/zameer-marketplace
/plugin install unrivaled-solutions@zameer-marketplace
```
Uses his logged-in GitHub credentials for the private repo.

## Part 3 — Create his data folder + migrate his workbook

1. Get the pipeline scripts: on GitHub open `Kyojuro26/zameer-marketplace` →
   **Code → Download ZIP** → extract (e.g. to `Downloads\zameer-marketplace`).
   _(No Git needed. If you prefer Git: `git clone …` instead.)_
2. In PowerShell, create his store folder (plain local — NOT OneDrive; sync
   locks break saves, the daily robocopy task handles backup) and run the
   migration into it. **Only on first-ever setup: never re-run the migration
   over a live store — it would overwrite his edits.**
   ```powershell
   $store = "C:\UnrivaledCRM\store"
   New-Item -ItemType Directory -Force -Path $store | Out-Null
   cd "$env:USERPROFILE\Downloads\zameer-marketplace\plugins\unrivaled-solutions\skills\crm"
   python pipeline\normalize.py --workbook "C:\path\to\Sales Tracker.xlsx" --out "$store"
   ```
3. Confirm the data is clean (expect 0 bogus, all shipment legs reconciled):
   ```powershell
   python pipeline\audit_workbook_vs_store.py --workbook "C:\path\to\Sales Tracker.xlsx" --store "$store"
   ```
4. _(Optional, if he's confirmed them)_ apply his duplicate-company merges and
   the D/G rep-name legend now, so records read cleanly from day one.

## Part 4 — Point Cowork at his store + run

Env vars never reach the plugin (Claude spawns it with a sanitized
environment) — the store path lives in a **pointer file** in his home folder.
Keep the live store OUT of OneDrive (sync locks break saves); the daily
robocopy task backs it up INTO OneDrive instead.
```powershell
Set-Content -Path "$HOME\.unrivaled-crm-store" -Value "C:\UnrivaledCRM\store" -Encoding Ascii
```
Then **fully quit Cowork** (right-click its taskbar/system-tray icon → Quit;
make sure it's not still running in the tray) and **reopen it**.

**Verify the core CRM (no Outlook needed):** in Cowork say *"open the CRM"* or
*"pull up [a customer]"*, and confirm you can:
- search a customer and see contacts / projects / shipments / invoices,
- edit a project status → it persists,
- add a new customer and a new vendor,
- delete one (it archives; *"restore [name]"* brings it back),
- advance a shipment stage.

Dylan now has a fully working CRM.

## Part 5 — Outlook, both directions (optional but recommended)

Follow **`Unrivaled-CRM-Outlook-Runbook.md`** (Windows steps). In short:
1. Register the app in **Dylan's** M365 (his admin) → client + tenant IDs.
2. One-time `python -u graph_login.py` device sign-in with **Dylan's** mailbox.
3. Write `.graph_config.json` into the store (client + tenant IDs) + restart
   Cowork → click-to-draft writes real Outlook **drafts** (never sends).
4. Connect the read-only **Microsoft 365 connector** for inbound activity.
5. Create the **scheduled auto-refresh** so each customer's Outlook activity
   updates every morning on its own.

## Part 6 — Acceptance test

1. Open a company → drill into a project → edit → reload → edit persisted.
2. Advance a shipment stage → visible in the store.
3. Create a project, a contact, a customer, and a vendor from the CRM.
4. Delete a test record → confirm it's gone → restore it.
5. _(If Outlook on)_ click a contact → a real draft appears in his Outlook Drafts.
6. _(If Outlook on)_ run the refresh once → a customer shows recent Outlook
   activity with working links.
7. Walk the `needs_review` list together (duplicate-name candidates, D/G rep
   legend, flagged records).

---

## If something doesn't connect (Windows)

- **`python3` not recognized:** install Python from the **Microsoft Store**
  (not just python.org). That's what registers `python3`. Then reinstall the
  packages with `python -m pip install mcp msal requests openpyxl`.
- **CRM plugin won't start / tools don't appear:** check the pointer file
  (`type $HOME\.unrivaled-crm-store` must print the store path) and read the
  launch log: `type $env:TEMP\unrivaled-crm-launch.log`. Fully restart Cowork
  (check the system tray). Confirm the store folder has the `.json` files.
- **Outlook draft says "not configured":** `.graph_config.json` is missing
  from the store, unparseable, or the client/tenant IDs in it aren't
  written correctly, or `graph_login` hasn't been run for this store — see Part 5.
- **Paths with spaces:** always keep them in double quotes in PowerShell.

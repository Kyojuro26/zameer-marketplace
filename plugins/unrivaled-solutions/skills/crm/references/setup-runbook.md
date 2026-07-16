# Unrivaled CRM — production setup (v0.1.17, updated 7/16)

Run on Dillon's PC, logged in as his user, in **PowerShell** (Start → type `powershell` → Enter). No admin needed.

**What changed since the old runbook:** we proved on Zeeshan's Mac that Claude spawns plugin servers with a **sanitized environment — user env vars never reach the server.** Every `UNRIVALED_CRM_STORE` / `UNRIVALED_PYTHON` env-var step in the old runbook was a dead end and is gone. Plugin **v0.1.4** reads its store path from a pointer file instead, and writes a launch log so failures are readable. Two other confirmed bugs are also fixed in v0.1.4: the store must contain `invoices.json`, and the old plugin config passed an unexpandable `${UNRIVALED_CRM_STORE}` placeholder.

---

## STEP 1 — Install plugin v0.1.17

Update `unrivaled-solutions` from the zameer-marketplace (or install the `.plugin` file from Zeeshan). In Claude: **Settings → Capabilities**. Verify the version shows **0.1.17** — anything older than 0.1.4 can never connect, 0.1.9 moves the Outlook token cache + config into a `.secrets` subfolder (auto-migrated from the old location on first launch — no action needed), 0.1.10 adds a store-wide write lock so two writers can't silently overwrite each other's edits (if the store is briefly locked you'll see a clear "try again in a moment" message instead of a lost change), 0.1.11 adds the real visual app (Step 6 below) — **the "visual app talks live via Cowork" claim in older versions of this runbook was wrong and has been retracted**: tested directly and confirmed no Cowork artifact surface can reach the plugin's tools, so the visual app now runs as its own local server instead — 0.1.12 adds in-app editing for a company's own record (name, location) and for existing contacts (previously you could only add new ones, not fix a name/phone/email on one already there), 0.1.13 adds editing for a project's revenue, cost, gross profit, and margin (previously only status/collection/owner/notes were editable), 0.1.14 hardens the visual app's local server against DNS-rebinding (a Host-header allowlist) and fixes a rare partial-write on a failed vendor creation, 0.1.15 closes every remaining editing gap surfaced by "field is saved but the app never let you type it in" reports — a project's description (the deal name shown in every list — this is what "can't edit project names" meant), location, deal date, client PO #, invoice #, PO-on-file flag, and annotations are now editable, as are a shipment's vendor PO, order notes, start date, and ETA, and a contact's location, action notes, and last-action date — 0.1.16 ships this setup guide inside the plugin itself, so you can ask Claude for it directly instead of needing a separate file from Zeeshan (see the note at the very bottom), and 0.1.17 fixes Step 3b's backup-task command, which mis-parsed in real PowerShell (not cmd.exe) whenever the OneDrive path had a space in it — the old hand-quoted `schtasks /TR "..."` string is replaced with the `Register-ScheduledTask` cmdlet form. (To confirm what's actually running later, ask Claude "crm info" — the reply includes `server_version`.)

## STEP 2 — Real Python with the `mcp` package

The plugin launches `python3`. On Windows that must resolve to a real Python, not the Microsoft Store shim.

```powershell
where.exe python3
```

- If it shows `...\Microsoft\WindowsApps\python3.exe` → that's the broken shim. Remove it and install real Python:

```powershell
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe"  -Force -ErrorAction SilentlyContinue
Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"
Start-Process "$env:TEMP\python-installer.exe" -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
$py = (Get-Command python).Source
Copy-Item $py (Join-Path (Split-Path $py) "python3.exe") -Force
python3 --version
```

**Expect:** `Python 3.12.10`. Then install the server's dependency:

```powershell
python3 -m pip install mcp msal requests
```

(Only `mcp` is needed to connect; `msal`/`requests` are for Outlook features.)

## STEP 3 — Move the store to a plain local folder + pointer file

The store must NOT live inside OneDrive — sync locking and Files-On-Demand placeholders can corrupt or stall the server's atomic writes. Move it once, point at it forever:

```powershell
robocopy "C:\Users\DillonCarpenter\OneDrive - unrivaledsolutions.com\Desktop\store" "C:\UnrivaledCRM\store" /E
Set-Content -Path "$HOME\.unrivaled-crm-store" -Value "C:\UnrivaledCRM\store"
Get-ChildItem "C:\UnrivaledCRM\store" -Filter *.json | Select-Object Name
```

**Expect:** six or seven `.json` files (`companies`, `contacts`, `projects`, `shipments`, `vendors`, `needs_review`, maybe `invoices`). v0.1.5 auto-creates any missing entity file, so no manual `invoices.json` step. After confirming the CRM works (Step 4), delete the old OneDrive copy so there's only one store.

## STEP 3b — Automatic backup (local store → OneDrive, one-way)

This gives OneDrive's file versioning as the backup without OneDrive touching the live store. **Do not use a single hand-quoted `schtasks /TR "..."` string for this** — PowerShell does not treat `\"` as an escaped quote the way cmd.exe does (the backslash is just a literal character, so the string closes early at the next bare `"`), and a OneDrive path with a space in it (`OneDrive - <tenant>.com`) needs an embedded quote. That mis-parse showed up for real during Dillon's setup (2026-07-16) as `ERROR: Invalid argument/option - '/MIR'`. Use the scheduled-tasks cmdlets instead, which avoid the nested-quote problem entirely by building the argument as plain string concatenation:

```powershell
$dest = 'C:\Users\DillonCarpenter\OneDrive - unrivaledsolutions.com\CRM-Backups\store'
$argStr = 'C:\UnrivaledCRM\store "' + $dest + '" /MIR /XD .secrets /R:2 /W:5'
$action = New-ScheduledTaskAction -Execute "robocopy.exe" -Argument $argStr
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 18 -Minute 0 -Second 0)
Register-ScheduledTask -TaskName "UnrivaledCRM-Backup" -Action $action -Trigger $trigger -Force | Out-Null
Get-ScheduledTask -TaskName "UnrivaledCRM-Backup" | Select-Object TaskName, State
```

**Expect:** the last line prints `State: Ready` — that's the real confirmation it registered (a command returning without error is not enough proof; the mis-parsed version above also "succeeded" at the PowerShell level before failing inside schtasks). Daily at 6pm the store is mirrored into OneDrive; OneDrive keeps version history of every backup. Restore = copy the folder back and fix the pointer file.

**Note the `/XD .secrets` exclusion** — the Graph token cache and credential config live in a `.secrets` subfolder that's deliberately kept OUT of the cloud backup (they're an OAuth refresh token and app IDs; they don't belong in OneDrive). They regenerate on next sign-in if lost.

**If this task already exists from before v0.1.9** (created with `/XF .graph_token_cache.json .graph_config.json` instead), re-run `Register-ScheduledTask` above with `-Force` to replace it — the old by-filename exclusion still works today but won't cover any new secret file added later, where `/XD .secrets` will. To check what's currently registered without recreating it: `Get-ScheduledTask -TaskName "UnrivaledCRM-Backup" | Select-Object TaskName, State`.

## STEP 3c — Outlook credentials (optional, for draft_email / sync_outlook)

Env vars never reach the server, so Graph credentials live in a config file inside the store's `.secrets` subfolder (get the IDs from Zeeshan / the Azure app registration):

```powershell
New-Item -ItemType Directory -Force -Path "C:\UnrivaledCRM\store\.secrets" | Out-Null
Set-Content -Path "C:\UnrivaledCRM\store\.secrets\.graph_config.json" -Encoding Ascii -Value '{"client_id": "AZURE_APP_CLIENT_ID", "tenant_id": "AZURE_TENANT_ID"}'
```

First Outlook action will prompt a one-time device-code sign-in; the token caches into the store folder. Skip this step entirely if Outlook drafts aren't needed yet — the CRM works without it.

## STEP 4 — Full quit, relaunch, test

```powershell
Stop-Process -Name "Claude" -Force -ErrorAction SilentlyContinue
```

Relaunch Claude from the Start menu, open a **new chat**, type: **pull up a customer**.

**Expect:** real data (378 companies / 369 contacts / 210 projects...). Confirmed working on Zeeshan's Mac 7/14 with this exact setup — this exact sequence has not yet been run on an actual Windows machine, so treat Dillon's first run as the first real test of Steps 2–3b specifically.

## STEP 5 — Prove a write persists

Make any small edit through Claude (archive a throwaway customer, mark a test shipment delivered), then:

```powershell
$store = Get-Content "$HOME\.unrivaled-crm-store"
Get-Content "$store\changelog.jsonl" -Tail 5
```

**Expect:** a fresh timestamped entry. Reads + writes = done.

## STEP 6 — The visual app (recommended, ~2 minutes)

The interactive CRM view is a real local web app now, not something opened
through a Cowork chat — Cowork has no way for a rendered artifact to call
back into a plugin's tools, so this runs as its own token-authenticated
localhost server instead (127.0.0.1 only; fresh random token every launch;
not reachable from the network or from any other browser tab).

In the same Claude chat, ask: **"copy the CRM plugin's skills/crm/mcp and
skills/crm/view folders into C:\UnrivaledCRM\app\skills\crm\mcp and
...\view"** — the plugin's actual install folder moves around between
updates, so have Claude locate it live rather than typing a path by hand.

**Expect:** `C:\UnrivaledCRM\app\skills\crm\mcp\local_server.py` and
`C:\UnrivaledCRM\app\skills\crm\view\build_view.py` both exist afterward.

Then create the desktop shortcut:

```powershell
@"
@echo off
cd /d "C:\UnrivaledCRM\app\skills\crm\mcp"
python3 local_server.py
pause
"@ | Set-Content -Path "$env:USERPROFILE\Desktop\Open Unrivaled CRM.bat" -Encoding Ascii
```

Double-click **"Open Unrivaled CRM"** on the Desktop. It reads the same
`~\.unrivaled-crm-store` pointer as everything else and opens your default
browser automatically.

**Expect:** the header reads **"Live · edits persist (local app)"**, not
"Demo." Click into a real company and confirm the data matches what "pull
up a customer" showed in Step 4. Leave the console window open while using
the app — closing it stops the server. If the header ever says "Demo,"
close that window and reopen from the shortcut rather than using the
browser's back button.

**After any future plugin update:** this copy at `C:\UnrivaledCRM\app\`
does **not** auto-update — re-run the copy step above if the update
touched `skills/crm/mcp` or `skills/crm/view`, or the shortcut keeps
launching old code with no warning it's stale. You can ask Claude in chat
to do this refresh directly — see this file's "Setup & update instructions"
pointer in the CRM skill.

---

## If it still won't connect

v0.1.4 logs every launch attempt. This one command replaces all the old log spelunking:

```powershell
Get-Content "$env:TEMP\unrivaled-crm-launch.log" -Tail 10
```

- **File doesn't exist** → the server never started: plugin not on v0.1.4, or `python3` still unresolvable (re-run Step 2's `where.exe python3`).
- **`FATAL: mcp import failed`** → wrong Python answered; run `python3 -m pip install mcp` and retry.
- **`FATAL: no store configured`** → pointer file missing or empty (Step 3).
- **`FATAL: store at ... is missing [...]`** → store path wrong or files missing; the message names exactly which.
- **Ends with `store ok`** → server is healthy; the problem is on Claude's side — full quit, relaunch, new chat, and if it persists send Zeeshan the log lines.

*(This supersedes `Message-for-Dillon-python-fix.md` and the old runbook's env-var steps entirely.)*

---

## About this file

This is the canonical copy of the setup runbook — it now ships inside the
plugin itself (`skills/crm/references/setup-runbook.md`) specifically so it
survives on whatever machine the plugin is installed on and can be asked
for directly in chat ("how do I set up the CRM", "how do I update it",
"what's the runbook say"). A short pointer copy lives at the marketplace
repo's root (`docs/Dillon-PC-fix-runbook.md`) for anyone browsing the repo
on GitHub — edit **this** file when the setup process changes, not that one.

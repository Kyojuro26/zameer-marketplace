# Unrivaled CRM — MCP connect fix, exact commands
Run on Dillon's PC, logged in as his user. Open **PowerShell** (Start → type `powershell` → Enter). Regular user is fine, no admin needed. Run the blocks in order. Each block says what you should see.

---

## STEP 0 — Read Claude's MCP log (the real decisive test, 30 sec)

```powershell
Get-ChildItem "$env:APPDATA\Claude\logs" | Sort-Object LastWriteTime -Descending | Select-Object Name, LastWriteTime -First 15
```

Find the log for the CRM server (name contains `unrivaled`), then dump its tail — and the main mcp log:

```powershell
Get-ChildItem "$env:APPDATA\Claude\logs" -Filter "*unrivaled*" | ForEach-Object { Write-Host "=== $($_.Name) ==="; Get-Content $_.FullName -Tail 40 }
Get-Content "$env:APPDATA\Claude\logs\mcp.log" -Tail 40 -ErrorAction SilentlyContinue
```

**Interpretation — this decides everything:**
- `spawn python3 ENOENT` (or `EINVAL` / `UNKNOWN` on spawn) → **alias problem confirmed. Continue to Step 1.**
- `StoreError: store at ... is missing` or literal `${UNRIVALED_CRM_STORE}` in the error → env var isn't reaching Claude. Check it: `[Environment]::GetEnvironmentVariable("UNRIVALED_CRM_STORE","User")` — if that prints the store path correctly, reboot and re-check the log. Don't do the Python fix yet; send me the log line.
- Anything else you don't recognize → send me the log line before proceeding.

## STEP 1 — Confirm python3 is the Store alias

```powershell
where.exe python3
```

**Expect:** a path containing `\Microsoft\WindowsApps\python3.exe`. That's the broken shim.

## STEP 2 — Kill the Store aliases (pure CLI)

```powershell
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe"  -Force -ErrorAction SilentlyContinue
where.exe python3
```

**Expect:** the last line now errors with "could not find files" — good, the shim is gone.
*(If Remove-Item is denied: Start → "Manage app execution aliases" → toggle OFF both `python.exe` and `python3.exe` App Installer entries, then re-run the `where.exe` check.)*

## STEP 3 — Install real Python (silent, no clicking)

```powershell
Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"
Start-Process "$env:TEMP\python-installer.exe" -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
```

**Expect:** ~2–3 min, no output. `-Wait` returns when done.

## STEP 4 — Refresh PATH in this window, create python3.exe

```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
$py = (Get-Command python).Source
Write-Host "python is: $py"
Copy-Item $py (Join-Path (Split-Path $py) "python3.exe") -Force
where.exe python3
python3 --version
```

**Expect:** `python is:` shows `...\AppData\Local\Programs\Python\Python312\python.exe` (NOT WindowsApps). `where.exe python3` shows the same dir. Version prints `Python 3.12.10`.

## STEP 5 — Install the server's dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install mcp msal requests openpyxl
```

**Expect:** ends with `Successfully installed ...`. (Only `mcp` is needed for the server to connect; the rest are for Outlook later.)

## STEP 6 — Sanity-run the server by hand under the NEW python3

```powershell
$store = [Environment]::GetEnvironmentVariable("UNRIVALED_CRM_STORE","User")
Write-Host "store is: $store"
Invoke-WebRequest "https://raw.githubusercontent.com/Kyojuro26/zameer-marketplace/main/plugins/unrivaled-solutions/skills/crm/mcp/server.py" -OutFile "$env:TEMP\ucrm_server.py"
python3 "$env:TEMP\ucrm_server.py" --store "$store"
```

**Expect:** `store is:` prints `C:\Users\DillonCarpenter\OneDrive - unrivaledsolutions.com\Desktop\store`, then the last command **sits silently with a blinking cursor — that IS success** (server running, waiting on stdio). Press **Ctrl+C** to stop it.
If it instead prints `store at ... is missing [...]` → store files problem, stop and send me the output.
If `ModuleNotFoundError: mcp` → Step 5 installed into a different Python; run `python3 -m pip install mcp` and retry.

## STEP 7 — Fully quit Claude and relaunch

```powershell
Stop-Process -Name "Claude" -Force -ErrorAction SilentlyContinue
Start-Sleep 3
```

Relaunch Claude from the Start menu. In Claude, type: **pull up a customer** (or "crm info").

**Expect:** real data back (378 companies / 369 contacts / 210 projects...).

## STEP 8 — Prove a write persists

Make any small edit through Claude (e.g. "mark shipment X delivered" on a test record, or add/archive a throwaway customer), then:

```powershell
$store = [Environment]::GetEnvironmentVariable("UNRIVALED_CRM_STORE","User")
Get-Content "$store\changelog.jsonl" -Tail 5
```

**Expect:** a fresh timestamped entry for your edit. Reads + writes = done.

---

## If Step 7 still fails

1. **Reboot**, retry Step 7. (Claude inherits PATH from Explorer; a reboot forces the refresh.)
2. Re-run **Step 0** and read the new error — it will have changed. Send it to me.
3. Nuclear option (I do this, not on Dillon's PC): ship plugin v0.1.3 with `"command": "${UNRIVALED_PYTHON:-python3}"`, then on Dillon's PC:
   ```powershell
   setx UNRIVALED_PYTHON "$((Get-Command python).Source)"
   ```
   update the plugin in Claude, full quit, relaunch. Absolute-path spawn bypasses PATH/aliases entirely.

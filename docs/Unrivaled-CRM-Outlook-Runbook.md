# Unrivaled CRM — Outlook Two-Way Setup + Auto-Refresh (Windows / HP)

_For the setup session on Dylan's Windows PC. Gets email flowing both ways:
emails he writes from the CRM land in his Outlook as drafts, and recent
activity is pulled back onto each customer automatically. Use **PowerShell**._

## The two directions, in plain terms

- **CRM → Outlook (outbound):** clicking a contact in the CRM creates a **real
  draft** in Dylan's Outlook. He reviews and sends it from Outlook. The CRM
  never sends on its own — by design.
- **Outlook → CRM (inbound):** each customer's record shows its recent Outlook
  **activity** — last contact date, recent threads (subject · who · date · a
  link to open the real email), and meetings. Refreshed on a schedule (below)
  so it stays current on its own. It stores the thread *metadata + link*, not a
  copy of the email body.

---

## Part 1 — One-time Outlook enablement (Dylan's PC)

### 1. Register the app in Dylan's Microsoft 365 (his IT admin, ~2 min)
Azure/Entra portal → **Microsoft Entra ID → App registrations → New
registration**:
- **Name:** Unrivaled CRM · **Account type:** single tenant · no redirect URI.
- **Authentication → Advanced settings → Allow public client flows → Yes.**
- **API permissions → Microsoft Graph → Delegated:** `Contacts.ReadWrite`,
  `Mail.ReadWrite`, `MailboxSettings.ReadWrite` → **Grant admin consent**.
- Copy the **Application (client) ID** and **Directory (tenant) ID**.

### 2. Sign in once (PowerShell)
```powershell
cd "$env:USERPROFILE\Downloads\zameer-marketplace\plugins\unrivaled-solutions\skills\crm\mcp"
# Creds live in a config file INSIDE the store — env vars never reach the
# plugin (Claude spawns it with a sanitized environment). -Encoding Ascii
# matters: Out-File / default Set-Content write UTF-16, which older plugin
# versions couldn't read (0.1.8+ tolerates any encoding, but be kind).
Set-Content -Path "C:\UnrivaledCRM\store\.graph_config.json" -Encoding Ascii -Value '{"client_id": "<his client id>", "tenant_id": "<his tenant id>"}'
python -m pip install msal requests --quiet
python -u graph_login.py --store "C:\UnrivaledCRM\store"
```
Enter the code at **microsoft.com/devicelogin**, sign in with **Dylan's**
mailbox. Wait ~15 s for the code line to appear (the `-u` forces it to print).
Look for "Signed in as … — Outlook tools are now live."

### 3. Make it live inside Cowork
Nothing to set — the plugin reads `.graph_config.json` from the store (written
in Step 2) and the token cache saved by the sign-in. **Fully quit
Cowork** (system-tray icon → Quit) and **reopen it** so the plugin restarts. Click-to-draft in the CRM
now writes real Outlook drafts.

### 4. Connect the read-only Microsoft 365 connector
In Claude's connector settings, connect **Microsoft 365 / Outlook (read-only)**
for Dylan's account. This powers the inbound activity view. It's separate from
the app registration above (that one powers the *write* side).

---

## Part 2 — Make inbound automatic (the scheduled refresh)

In Dylan's Cowork, create one scheduled task — paste this as the request:

> **Every weekday at 7:00 AM, refresh Outlook activity in the Unrivaled CRM.**
> For each customer that has an open or pending project — plus any customer
> contacted in the last 14 days — search my Outlook email and calendar for that
> company's contacts, then compute and save (via the CRM's `set_enrichment`):
> the last contact date, up to 5 recent threads (subject, who it's with, date,
> and the Outlook link), and any recent or upcoming meetings. If a company has
> no activity, save an empty result — never invent activity. When done, tell me
> how many customers were refreshed and which had new contact since yesterday.

Optional: add a second run at **1:00 PM**. Scoping to active customers (open/
pending deals + recently contacted) keeps each run fast and relevant instead of
sweeping all 400+ records. Result: each morning, every active customer's Outlook
activity is already current when Dylan opens the CRM.

---

## Part 3 — Verify both directions

1. **Outbound:** open a customer → click a contact → confirm a **draft** appears
   in Outlook Drafts (nothing sent).
2. **Inbound:** trigger the schedule once (or ask "refresh Outlook activity for
   [customer]") → that customer's record shows last contact + recent threads,
   and the links open the real emails in Outlook.

## Guardrails (unchanged)
Drafts only — nothing is ever sent for Dylan. Inbound is **read-only** — Outlook
is never modified or deleted. The CRM stores thread metadata + links, not email
bodies. Anything uncertain is flagged for review, never guessed.

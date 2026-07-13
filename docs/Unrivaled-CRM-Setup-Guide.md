# Unrivaled CRM — Setup Guide

Your CRM turns the Sales Tracker workbook into something you can actually
work in: search any customer, see their projects, shipments, and receivables
in one place, add and remove customers and vendors, update a status and have
it stick, and start an Outlook email with one click. Nothing is ever sent on
your behalf.

You can be up and running in about ten minutes. The steps below are written so
you can follow along; the two technical bits are marked **"do this once with
Zeeshan"** — we'll knock those out together on a quick screen-share.

---

## What you need

- The plugin file: **`unrivaled-solutions.plugin`**
- Your current **Sales Tracker** Excel workbook
- Your computer with the **Claude** desktop app installed

---

## Step 1 — Install the plugin

1. Open the Claude desktop app.
2. Drag **`unrivaled-solutions.plugin`** into Claude (or open it and choose
   **Install**).
3. That's it — Claude now knows how to run your CRM.

## Step 2 — Turn it on with your data *(do this once with Zeeshan, ~10 min)*

This is the part we'll do together the first time. It does three small things:

1. Installs a few helper components the CRM needs to run.
2. Picks the folder where **your** records live — a folder you own (we'll put
   it in your OneDrive so it's automatically backed up). Your data never leaves
   your computer.
3. Loads your customers, projects, shipments, and receivables from your Sales
   Tracker workbook into that folder.

After this one-time step, your CRM is live and everything you change is saved.

## Step 3 — Start using it

Just talk to Claude in plain English. For example:

- *"Pull up Vibracoustic"* — see a customer's contacts, projects, shipments,
  and invoices.
- *"What's the status of project 1318?"*
- *"Mark shipment 1352-L1 delivered."*
- *"Add a new customer — Ace Manufacturing in Louisville."*
- *"Add a vendor — Bolt Supply, rep Jane, they sell fasteners."*
- *"Delete Dallas Group of America"* (see *Deleting* below — it's reversible).
- *"Draft an email to Jeff Haysley."*
- *"Open the CRM"* — opens the visual app: search on the left, click any
  company to see everything, and use the buttons to add a customer or vendor,
  add a project, or delete.

---

## Optional — Turn on Outlook

The CRM works fully without this. When you're ready to add real Outlook drafts
and see recent activity per customer, we turn on two things:

1. **A one-time approval in your Microsoft 365** (your IT admin, about two
   minutes) so the CRM is allowed to create drafts and sync contacts.
2. **A single sign-in** on your computer — after that it's automatic.

Once on, clicking a contact creates a real **draft** in your Outlook (you
review and send it — it is never sent for you), you can push a customer's
contacts into Outlook with status labels, and each customer shows its last
contact, recent email threads, and meetings.

---

## What works right away (no Outlook needed)

Everything except the Outlook pieces above: search, full customer view, adding
and deleting customers and vendors, editing statuses and notes, advancing
shipment stages, tracking receivables — all saved to your own records.

## Good to know

- **Nothing is ever sent or filed for you.** The CRM only ever prepares
  drafts; you send them.
- **"Delete" is reversible.** Deleting a customer or vendor hides it from the
  CRM but nothing is destroyed — its projects, contacts, and shipments are
  kept, and it can be restored. Just ask Claude to *"restore [name]."*
- **Your data is yours.** It lives in your own folder; nothing is hard-coded or
  shipped anywhere.
- **When it's unsure, it flags — it doesn't guess.** Anything ambiguous is set
  aside for you to confirm rather than filled in silently.

## A couple of things we'll confirm with you

To make the records perfect, we'll want your quick input on: which look-alike
names are the same company (e.g. *Dallas Group* vs *Dallas Group of America*),
and what the rep initials **D** and **G** stand for so owners show real names.

---

## Need a hand

Text or email Zeeshan anytime — zeeshan@zameer.io. Happy to hop on a quick
call and walk through anything.

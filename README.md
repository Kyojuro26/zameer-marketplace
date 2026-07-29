# Zameer Marketplace

Plugin marketplace for Zameer client deliveries. The client operator subscribes
once; every update pushed here flows to their install.

> **This repo is PUBLIC.** A private repo would not install, so it must stay
> public. Nothing client-identifying — names, mailboxes, tenant domains, user
> paths — may be committed anywhere in this tree, `docs/` and this file
> included. `publish.sh` sweeps for it, but the sweep is a backstop, not a
> substitute for checking before you commit.

## Repo layout

```
zameer-marketplace/            (public GitHub repo)
├── .claude-plugin/
│   └── marketplace.json       # catalog — lists available plugins
└── plugins/
    └── unrivaled-solutions/   # the plugin, copied from build/unrivaled-solutions
```

## One-time setup (Zeeshan)

1. Create a **public** GitHub repo, e.g. `zameer/zameer-marketplace`. It has to
   be public — the plugin installer fetches over unauthenticated HTTPS and a
   private repo simply fails to install. That constraint is why the banner
   above exists: nothing identifying can ever go in here.
2. Copy this `marketplace/` directory's contents to the repo root.
3. Copy `build/unrivaled-solutions/` → `plugins/unrivaled-solutions/`
   **excluding dev artifacts** (see "What not to publish" below).
4. Create `.pii-names` at the repo root (gitignored, never committed) with one
   `grep -E` pattern per line covering every client and contact name that must
   not appear here. `publish.sh` and the pre-commit hook both require it; see
   `.pii-names.example`.
5. Install the pre-commit hook: `./scripts/install-hooks.sh`.
6. Commit and push. No access grant is needed — the repo is public.

## The operator subscribes (once)

In Claude Code / Cowork:

```
/plugin marketplace add zameer/zameer-marketplace
/plugin install unrivaled-solutions@zameer-marketplace
```

No sign-in or access grant is involved — the repo is public and the installer
fetches it anonymously.

## Shipping an update

1. Make changes in the build workspace; run the test suites.
2. Bump `version` in `plugin.json` (semver).
3. Copy the plugin into `plugins/unrivaled-solutions/`, commit, push.
4. The operator's install picks up the update — verify with them once
   (Phase 7 done-when: an update propagates without touching their machine).

## What NOT to publish

- `skills/crm/store/` — that's DATA, not the product. The operator's store lives
  in their own folder, seeded at delivery by the migration.
- `skills/crm/store/.secrets/` — credentials (Graph token cache + config),
  never committed anywhere.
- `view/unrivaled-crm.html` — generated file with embedded data; the
  builder (`build_view.py`) is what ships.
- `node_modules/`, `__pycache__/`, changelogs from dev.

A `publish.sh` helper alongside this README does the copy with the right
exclusions.

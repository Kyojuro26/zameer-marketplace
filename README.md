# Zameer Private Marketplace

Private plugin marketplace for Zameer client deliveries. Dylan (Unrivaled
Solutions) subscribes once; every update pushed here flows to his install.

## Repo layout

```
zameer-marketplace/            (private GitHub repo)
├── .claude-plugin/
│   └── marketplace.json       # catalog — lists available plugins
└── plugins/
    └── unrivaled-solutions/   # the plugin, copied from build/unrivaled-solutions
```

## One-time setup (Zeeshan)

1. Create a **private** GitHub repo, e.g. `zameer/zameer-marketplace`.
2. Copy this `marketplace/` directory's contents to the repo root.
3. Copy `build/unrivaled-solutions/` → `plugins/unrivaled-solutions/`
   **excluding dev artifacts** (see "What not to publish" below).
4. Commit and push.
5. Give Dylan's GitHub account read access to the repo.

## Dylan subscribes (once)

In Claude Code / Cowork:

```
/plugin marketplace add zameer/zameer-marketplace
/plugin install unrivaled-solutions@zameer-marketplace
```

(Private repo access uses his logged-in GitHub credentials.)

## Shipping an update

1. Make changes in the build workspace; run the test suites.
2. Bump `version` in `plugin.json` (semver).
3. Copy the plugin into `plugins/unrivaled-solutions/`, commit, push.
4. Dylan's install picks up the update — verify with him once
   (Phase 7 done-when: an update propagates without touching his machine).

## What NOT to publish

- `skills/crm/store/` — that's DATA, not the product. Dylan's store lives
  in his own folder, seeded at delivery by the migration.
- `skills/crm/store/.secrets/` — credentials (Graph token cache + config),
  never committed anywhere.
- `view/unrivaled-crm.html` — generated file with embedded data; the
  builder (`build_view.py`) is what ships.
- `node_modules/`, `__pycache__/`, changelogs from dev.

A `publish.sh` helper alongside this README does the copy with the right
exclusions.

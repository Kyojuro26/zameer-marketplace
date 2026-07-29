# Unrivaled CRM — production setup

**Moved.** The canonical copy of this runbook now lives inside the plugin
itself, so it ships with every install and Claude can be asked for it
directly in chat (on whatever machine has the plugin installed: "how do I
set up the CRM", "how do I update it", "what's the runbook say"):

```
plugins/unrivaled-solutions/skills/crm/references/setup-runbook.md
```

Edit that file when the setup process changes.

This stub used to exist purely so older links into this `docs/` folder kept
resolving. It no longer does that job: the file was renamed to strip a client
name out of a public repo, so any link to the old filename now 404s regardless.
It is kept as a signpost for anyone who lands in `docs/` looking for the setup
steps and needs pointing at the in-plugin copy.

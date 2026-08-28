#!/usr/bin/env python3
"""COUNT ONLY -- this script CHANGES NOTHING.

It opens three files in your CRM store, READ-ONLY, counts a few things, and
prints the counts. It does not write, rename, move, or delete anything, it does
not connect to the network, and it needs nothing installed -- just Python.

It prints NUMBERS ONLY. No customer names, no project numbers, no tracker keys,
nothing from your records. The output is safe to paste into a chat.

WHAT IT IS FOR
    An upcoming change removes the guessing behind the Live Tracker's
    "Not in the CRM yet" list. After that change some rows that were being
    hidden by a stale guess will show up again, once, until you dismiss them.
    These counts tell us how many that could be, before we ship it.

HOW TO RUN
    python3 crm-tracker-key-count.py "C:\\path\\to\\your\\crm-store"

    If you leave the path off, it looks in the usual places.
"""
import json
import os
import sys
from pathlib import Path


def load(path):
    """Read one JSON file. Missing is fine and counts as empty."""
    try:
        # utf-8-sig strips a BOM; Windows editors add one.
        with open(path, encoding="utf-8-sig") as f:
            v = json.load(f)
        return v if isinstance(v, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"  ! {Path(path).name} could not be read ({e.__class__.__name__}).")
        print(f"    Counting it as empty. Nothing was changed.")
        return []


def find_store(argv):
    if len(argv) > 1:
        return Path(argv[1]).expanduser()
    pointer = Path.home() / ".unrivaled-crm-store"
    if pointer.exists():
        try:
            raw = pointer.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = pointer.read_text(encoding="utf-16")
        p = raw.strip().strip('"').strip("'").strip()
        if p:
            return Path(p).expanduser()
    env = os.environ.get("UNRIVALED_CRM_STORE")
    return Path(env).expanduser() if env else None


def main():
    store = find_store(sys.argv)
    if store is None or not store.is_dir():
        print("Could not find your CRM store folder.")
        print("Run it again with the folder path, for example:")
        print('    python3 crm-tracker-key-count.py "C:\\Users\\you\\OneDrive\\crm-store"')
        return 1

    projects = load(store / "projects.json")
    companies = load(store / "companies.json")
    unlinked = load(store / "tracker_unlinked.json")

    archived_companies = {c.get("company_id") for c in companies
                          if isinstance(c, dict) and c.get("archived")}

    def has_key(p):
        return isinstance(p, dict) and str(p.get("tracker_key") or "").strip() != ""

    with_key = [p for p in projects if has_key(p)]
    key_archived_company = [p for p in with_key
                            if p.get("company_id") in archived_companies]
    key_archived_project = [p for p in with_key if p.get("archived")]

    print("Unrivaled CRM -- tracker key counts")
    print(f"store: {store}")
    print("(read-only; nothing was changed)")
    print()
    print(f"  projects in the store ................................ {len(projects)}")
    print(f"  projects carrying a tracker key ...................... {len(with_key)}")
    print(f"    ... of those, on an ARCHIVED customer .............. {len(key_archived_company)}")
    print(f"    ... of those, the project itself archived .......... {len(key_archived_project)}")
    print(f"  rows currently on the 'Not in the CRM yet' list ...... {len(unlinked)}")
    print()
    print("Numbers only -- no names or record values are printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

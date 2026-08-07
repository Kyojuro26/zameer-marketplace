#!/usr/bin/env bash
# Build the installable .plugin file (a zip) from the tracked plugin tree.
#
# The runbook's STEP 1 offers "install the .plugin file from Zeeshan" but no
# script ever produced one, so it was built by hand -- and a naive zip of the
# working directory ships __pycache__/*.pyc, which this project's own rules
# class as forbidden, plus anything else lying around untracked.
#
# This builds from `git archive` (TRACKED FILES ONLY at the given ref), so
# nothing untracked can leak in by construction. It then re-runs the same
# forbidden-file sweep and PII sweep that guard a commit, over the staged
# content, and refuses rather than warns.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${1:-HEAD}"
SRC="plugins/unrivaled-solutions"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

git -C "$ROOT" archive "$REF" "$SRC" | tar -x -C "$STAGE"
PLUG="$STAGE/$SRC"

VER=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' \
      "$PLUG/.claude-plugin/plugin.json" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
[ -n "$VER" ] || { echo "FATAL: no version in plugin.json" >&2; exit 1; }

# the zip root must be exactly these four entries
EXPECTED=".claude-plugin .mcp.json README.md skills"
ACTUAL=$(cd "$PLUG" && ls -A | sort | tr '\n' ' ' | sed 's/ $//')
if [ "$ACTUAL" != "$(echo $EXPECTED | tr ' ' '\n' | sort | tr '\n' ' ' | sed 's/ $//')" ]; then
  echo "FATAL: unexpected contents at the plugin root:" >&2
  echo "  got:      $ACTUAL" >&2
  echo "  expected: $EXPECTED" >&2
  exit 1
fi

FORBIDDEN=$(find "$PLUG" \( -name 'dev_bridge*' -o -name 'test_*' -o -name '*smoke*' \
  -o -name 'audit-*' -o -name '*.pyc' -o -name '__pycache__' -o -name '*token_cache*' \
  -o -name '.graph_config.json' -o -name 'changelog.jsonl' -o -name '.secrets' \
  -o -name 'store' -o -name '*.html' -o -name '*.xlsx' -o -name '.env' \) -print)
if [ -n "$FORBIDDEN" ]; then
  echo "FATAL: forbidden files staged for packaging:" >&2
  echo "$FORBIDDEN" >&2
  exit 1
fi

cp "$ROOT/.pii-names" "$STAGE/.pii-names"
"$ROOT/scripts/pii-sweep.sh" "$STAGE" || {
  echo "FATAL: identifying content in the packaged tree -- NOT safe to ship." >&2
  exit 1; }
rm -f "$STAGE/.pii-names"

OUT="$ROOT/dist/unrivaled-solutions-$VER.plugin"
mkdir -p "$ROOT/dist"
rm -f "$OUT"
(cd "$PLUG" && zip -q -r "$OUT" . -x '.DS_Store')
echo "built $OUT  (v$VER, $(unzip -l "$OUT" | tail -1 | awk '{print $2}') files)"

#!/usr/bin/env bash
# Copy the plugin from the build workspace into this marketplace checkout,
# excluding dev artifacts (data, credentials, tests, dev bridge, audit output).
#   ./publish.sh /path/to/build/plugin-src
# NOTE: rsync --delete does NOT remove excluded files already in DEST —
# the find below sweeps them explicitly. Verify the forbidden-sweep is empty
# before committing. This repo is PUBLIC: no client data, ever. At the end this
# runs scripts/pii-sweep.sh over the whole tree (same check the pre-commit hook
# runs; needs a .pii-names — see .pii-names.example) plus a four-marker version
# check. Both fail the publish rather than warn.
set -euo pipefail

SRC="${1:?usage: ./publish.sh /path/to/build/plugin-src}"
DEST="$(cd "$(dirname "$0")" && pwd)/plugins/unrivaled-solutions"

mkdir -p "$DEST"
rsync -av --delete \
  --exclude 'skills/crm/store/' \
  --exclude '*.graph_token_cache.json' \
  --exclude '.graph_config.json' \
  --exclude 'skills/crm/view/unrivaled-crm.html' \
  --exclude 'skills/crm/mcp/dev_bridge.py' \
  --exclude 'skills/crm/mcp/test_*.py' \
  --exclude 'skills/crm/mcp/graph_layer_smoke.py' \
  --exclude 'skills/crm/view/test_*.js' \
  --exclude 'audit-findings.json' \
  --exclude 'audit-report.md' \
  --exclude 'DELIVERY.md' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'changelog.jsonl' \
  "$SRC/" "$DEST/"

# rsync protects excluded files from --delete; remove any that pre-exist.
find "$DEST" \( -name 'dev_bridge*' -o -name 'test_*' -o -name '*smoke*' \
  -o -name 'audit-*' -o -name 'DELIVERY.md' -o -name '*.pyc' \
  -o -name '*token_cache*' -o -name '.graph_config.json' \
  -o -name 'changelog.jsonl' -o -name '*.html' \) \
  -type f -delete
find "$DEST" \( -name '.secrets' -o -name 'store' \) -type d -prune -exec rm -rf {} +

# Verify, and FAIL the publish if anything forbidden survived — a printed
# warning nobody reads is not a tripwire. This repo is PUBLIC.
echo "FORBIDDEN-SWEEP (must print nothing):"
FORBIDDEN=$(find "$DEST" \( -name 'dev_bridge*' -o -name 'test_*' \
  -o -name '*smoke*' -o -name 'audit-*' -o -name '*.pyc' \
  -o -name '*token_cache*' -o -name '.graph_config.json' \
  -o -name 'changelog.jsonl' -o -name '.secrets' -o -name 'store' \) -print)
if [ -n "$FORBIDDEN" ]; then
  echo "$FORBIDDEN"
  echo "FATAL: forbidden files in $DEST — NOT safe to commit." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Identifying-content sweep — WHOLE REPO, not just the plugin.
#
# The forbidden sweep above only ever looked at $DEST and only ever matched
# file *kinds*. It passed green for months while docs/ carried the client's
# name, including in two filenames. The real sweep lives in scripts/pii-sweep.sh
# so the pre-commit hook (scripts/install-hooks.sh) runs the identical check —
# docs/ and README.md are hand-edited and never pass through this script.
# ---------------------------------------------------------------------------
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "IDENTIFYING-CONTENT SWEEP (must print nothing):"
"$ROOT/scripts/pii-sweep.sh" "$ROOT"

# ---------------------------------------------------------------------------
# Version-consistency gate. The version lives in FOUR unsynced places and the
# fourth (the shipped setup runbook, which tells the operator what number to
# expect) has already drifted a full release behind once.
# ---------------------------------------------------------------------------
echo "VERSION SWEEP:"

# Each marker is read through a helper that fails loudly. Under `set -e` a bare
# `VAR=$(grep ... | grep ...)` whose last stage matches nothing kills the script
# with no message at all, which reads as a crash rather than as drift.
read_marker() {
  local label="$1" file="$2" pattern="$3" out
  if [ ! -f "$file" ]; then
    echo "FATAL: version gate cannot find $label at $file." >&2
    exit 1
  fi
  out=$(grep -oE "$pattern" "$file" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)
  if [ -z "$out" ]; then
    echo "FATAL: no version marker found in $label ($file)." >&2
    echo "  Expected a line matching: $pattern" >&2
    exit 1
  fi
  printf '%s' "$out"
}

PJ=$(read_marker "plugin.json" "$DEST/.claude-plugin/plugin.json" \
     '"version"[[:space:]]*:[[:space:]]*"[^"]+"')
SV=$(read_marker "server.py" "$DEST/skills/crm/mcp/server.py" \
     '^SERVER_VERSION[[:space:]]*=[[:space:]]*"[^"]+"')
SK=$(read_marker "SKILL.md" "$DEST/skills/crm/SKILL.md" \
     '^[[:space:]]*version:[[:space:]]*"[^"]+"')
RB="$DEST/skills/crm/references/setup-runbook.md"
echo "  plugin.json=$PJ  server.py=$SV  SKILL.md=$SK"
if [ "$PJ" != "$SV" ] || [ "$PJ" != "$SK" ]; then
  echo "FATAL: version markers disagree — bump all four before publishing." >&2
  exit 1
fi

# The runbook's header, STEP 1 title, and "Verify the version shows" line must
# all name the current version. Its long changelog paragraph legitimately cites
# every past version, so match only those three instruction sites.
if [ ! -f "$RB" ]; then
  echo "FATAL: version gate cannot find setup-runbook.md at $RB." >&2
  exit 1
fi
# Each site is matched SEPARATELY and must contribute at least one version.
# Flattening them into one list and counting lines let a second occurrence of
# one phrase cover for another that had been reworded away -- the gate would
# report 3 while actually checking 2. STEP 1's body is a ~9000-character
# changelog that already cites every past version, so that was reachable.
RB_H=$(grep -oE '^# Unrivaled CRM — production setup \(v[0-9.]+' "$RB" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
RB_S=$(grep -oE '^## STEP 1 — Install plugin v[0-9.]+' "$RB" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
RB_V=$(grep -oE 'Verify the version shows \*\*[0-9.]+\*\*' "$RB" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
RB_COUNT=0
for _v in "$RB_H" "$RB_S" "$RB_V"; do [ -n "$_v" ] && RB_COUNT=$((RB_COUNT+1)); done
RB_RAW=$(printf '%s\n%s\n%s\n' "$RB_H" "$RB_S" "$RB_V" | grep -E '[0-9]' || true)
if [ "$RB_COUNT" -ne 3 ]; then
  echo "FATAL: expected 3 version markers in setup-runbook.md, found $RB_COUNT." >&2
  echo "  They are its '# Unrivaled CRM — production setup (vX.Y.Z' header, its" >&2
  echo "  '## STEP 1 — Install plugin vX.Y.Z' title, and its 'Verify the version" >&2
  echo "  shows **X.Y.Z**' line. If their wording changed, update this gate." >&2
  exit 1
fi
RB_SITES=$(printf '%s\n' "$RB_RAW" | sort -u)
for v in $RB_SITES; do
  if [ "$v" != "$PJ" ]; then
    echo "FATAL: setup-runbook.md still says $v (expected $PJ) in its header," >&2
    echo "  STEP 1 title, or 'verify the version shows' line." >&2
    exit 1
  fi
done
echo "  setup-runbook.md=$RB_SITES"

echo "Published to $DEST — commit and push."

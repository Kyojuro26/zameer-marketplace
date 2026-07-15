#!/usr/bin/env bash
# Copy the plugin from the build workspace into this marketplace checkout,
# excluding dev artifacts (data, credentials, tests, dev bridge, audit output).
#   ./publish.sh /path/to/build/plugin-src
# NOTE: rsync --delete does NOT remove excluded files already in DEST —
# the find below sweeps them explicitly. Verify the forbidden-sweep is empty
# before committing. This repo is PUBLIC: no client data, ever.
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
  -o -name '*token_cache*' -o -name 'changelog.jsonl' -o -name '*.html' \) \
  -type f -delete

echo "FORBIDDEN-SWEEP (must print nothing):"
find "$DEST" \( -name 'dev_bridge*' -o -name 'test_*' -o -name 'audit-*' -o -name '*.pyc' \) -type f
echo "Published to $DEST — bump plugin.json version, commit, push."

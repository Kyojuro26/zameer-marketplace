#!/usr/bin/env bash
# Copy the plugin from the build workspace into this marketplace checkout,
# excluding dev artifacts (data, credentials, generated files).
#   ./publish.sh /path/to/build/unrivaled-solutions
set -euo pipefail

SRC="${1:?usage: ./publish.sh /path/to/build/unrivaled-solutions}"
DEST="$(cd "$(dirname "$0")" && pwd)/plugins/unrivaled-solutions"

mkdir -p "$DEST"
rsync -av --delete \
  --exclude 'skills/crm/store/' \
  --exclude '*.graph_token_cache.json' \
  --exclude 'skills/crm/view/unrivaled-crm.html' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '.DS_Store' \
  --exclude 'changelog.jsonl' \
  "$SRC/" "$DEST/"

echo
echo "Published to $DEST"
echo "Now: bump version in plugin.json if not done, commit, push."

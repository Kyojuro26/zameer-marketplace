#!/usr/bin/env bash
# Install the repo's git hooks. Run once per clone.
#
#   ./scripts/install-hooks.sh
#
# Hooks are not cloned with a repo, so this is deliberate and manual. Without
# it the identifying-content sweep only runs at publish time, which is exactly
# how the client name reached docs/ — those files never go through publish.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# rev-parse, not "$ROOT/.git/hooks": in a linked worktree or a submodule .git is
# a regular file, and the literal path would just fail with "Not a directory".
HOOKS="$(git -C "$ROOT" rev-parse --git-path hooks)"
case "$HOOKS" in /*) ;; *) HOOKS="$ROOT/$HOOKS" ;; esac
mkdir -p "$HOOKS"

TARGET="$HOOKS/pre-commit"
if [ -e "$TARGET" ] && ! grep -q 'pii-sweep.sh' "$TARGET" 2>/dev/null; then
  cp "$TARGET" "$TARGET.bak"
  echo "NOTE: existing pre-commit hook backed up to $TARGET.bak" >&2
fi

cat > "$TARGET" <<'EOF'
#!/usr/bin/env bash
# Sweep the STAGED content, not the working tree.
#
# This distinction is the whole point. The normal way this hook gets used is:
# it blocks, you delete the offending line, you re-run `git commit` — and if it
# swept the worktree it would pass while the index still holds the leak. Same
# hole with `git add -p`.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git checkout-index -a -f --prefix="$TMP/"
# .pii-names is gitignored, so it is not in the index — hand it over explicitly.
if [ -r "$ROOT/.pii-names" ]; then
  cp "$ROOT/.pii-names" "$TMP/.pii-names"
fi
exec "$ROOT/scripts/pii-sweep.sh" "$TMP"
EOF
chmod +x "$TARGET"
echo "pre-commit hook installed -> $TARGET (sweeps the git index)"

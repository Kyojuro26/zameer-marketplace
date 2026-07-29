#!/usr/bin/env bash
# Identifying-content sweep for this PUBLIC repo.
#
# Shared by publish.sh and the pre-commit hook so both paths enforce the same
# rule. This matters: the leak this exists to prevent came in through docs/ and
# README.md, which are hand-edited and never go through publish.sh.
#
#   ./scripts/pii-sweep.sh [root]     exit 0 = clean, exit 1 = found / broken
#
# FAILS CLOSED. A missing .pii-names, an unreadable one, or a pattern that is
# not a valid ERE all abort. A sweep that cannot run must never look like a
# sweep that found nothing.
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || { echo "FATAL: cannot cd to $ROOT" >&2; exit 1; }

FAIL=0
HITS=""

add_hit() { HITS="$HITS$1"$'\n'; FAIL=1; }

# --- 1. Shape-based checks -------------------------------------------------
# No names live in this file — it is itself public. ALLOWED_EMAIL is the one
# address deliberately published as a contact line.
ALLOWED_EMAIL="zeeshan@zameer.io"
SHAPES=$(grep -rInoE \
  -e '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' \
  -e 'C:\\Users\\[^\\<> ]+' \
  -e '/Users/[a-z0-9._-]+/' \
  -e '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' \
  -e '[A-Za-z0-9-]+\.onmicrosoft\.com' \
  --exclude-dir=.git --exclude-dir=__pycache__ \
  --exclude=pii-sweep.sh --exclude=.pii-names --exclude=.pii-names.example .)
rc=$?
if [ "$rc" -ge 2 ]; then
  echo "FATAL: shape sweep failed (grep exit $rc)." >&2
  exit 1
fi
SHAPES=$(printf '%s\n' "$SHAPES" | grep -v "$ALLOWED_EMAIL" || true)
[ -n "$(printf '%s' "$SHAPES" | tr -d '[:space:]')" ] && add_hit "$SHAPES"

# --- 2. Name-based check ---------------------------------------------------
# The names cannot be committed here, so they live in an untracked, gitignored
# .pii-names (one grep -E pattern per line). See .pii-names.example.
if [ ! -r "$ROOT/.pii-names" ]; then
  echo "FATAL: .pii-names is missing or unreadable at $ROOT/.pii-names." >&2
  echo "  Copy .pii-names.example to .pii-names and fill it in. It is" >&2
  echo "  gitignored and must never be committed to this public repo." >&2
  exit 1
fi

NPAT=0
while IFS= read -r pat || [ -n "$pat" ]; do
  # Strip a trailing CR. .pii-names is hand-written, and the setup runbooks all
  # have the operator working in PowerShell/Notepad, which write CRLF. Left on,
  # "Smith\r" is a VALID regex that matches nothing — the sweep would pass green
  # while checking a name that can never hit. (Every example name in this file
  # is deliberately fictional: this script is itself public, and the name grep
  # below does not exclude it.)
  pat=${pat%$'\r'}
  [ -z "$pat" ] && continue
  case "$pat" in \#*) continue ;; esac
  NPAT=$((NPAT + 1))

  # Validate the ERE before trusting a no-match result. A typo like "Sm(ith"
  # makes grep exit 2 with zero output, which reads identically to "clean"
  # unless we check. This is the fail-open bug this block exists to close.
  printf '' | grep -qE "$pat" 2>/dev/null
  rc=$?
  if [ "$rc" -ge 2 ]; then
    echo "FATAL: .pii-names pattern is not a valid regex: $pat" >&2
    exit 1
  fi

  HIT=$(grep -rInoiE "$pat" --exclude-dir=.git --exclude-dir=__pycache__ \
        --exclude=.pii-names --exclude=.pii-names.example .)
  rc=$?
  if [ "$rc" -ge 2 ]; then
    echo "FATAL: name sweep failed on pattern '$pat' (grep exit $rc)." >&2
    exit 1
  fi
  [ -n "$HIT" ] && add_hit "$HIT"

  # Paths, not just contents — the name was in two FILENAMES and one directory
  # name. find|grep rather than find -iregex: -regextype is GNU-only and this
  # runs on macOS too, where it would abort the whole sweep.
  PATHS=$(find . -path ./.git -prune -o -print)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "FATAL: path listing failed (find exit $rc)." >&2
    exit 1
  fi
  FNAME=$(printf '%s\n' "$PATHS" | grep -v '^\./\.pii-names' | grep -iE "$pat")
  rc=$?
  if [ "$rc" -ge 2 ]; then
    echo "FATAL: filename sweep failed on pattern '$pat' (grep exit $rc)." >&2
    exit 1
  fi
  [ -n "$FNAME" ] && add_hit "FILENAME: $FNAME"
done < "$ROOT/.pii-names"

# A file of nothing but comments is the likeliest way this goes wrong: the
# README says to copy .pii-names.example, and that example is all comments.
# Copy-and-forget must not read as "swept clean".
if [ "$NPAT" -eq 0 ]; then
  echo "FATAL: .pii-names contains no patterns (only blanks/comments)." >&2
  echo "  It was probably copied from .pii-names.example and not filled in." >&2
  echo "  Add one grep -E pattern per line for every name that must not" >&2
  echo "  appear in this public repo." >&2
  exit 1
fi

if [ "$FAIL" -ne 0 ]; then
  printf '%s\n' "$HITS"
  echo "FATAL: identifying content in the tree — NOT safe to commit." >&2
  exit 1
fi
exit 0

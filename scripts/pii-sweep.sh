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

# Resolved to an ABSOLUTE path before anything else. The cd below changes what
# a relative path means, and `$ROOT/.pii-names` is read AFTER it -- so
# `pii-sweep.sh sometree` looked for `sometree/sometree/.pii-names`, found
# nothing, and aborted with "FATAL: .pii-names is missing". Failing closed, so
# never unsafe, but it aborts on the config branch rather than sweeping: a
# positive control run that way proves the sweep can exit 1, not that it can
# find a name. The pre-commit hook passes an absolute mktemp path, which is why
# this survived.
ROOT="$(cd "${1:-$(dirname "$0")/..}" 2>/dev/null && pwd)" \
  || { echo "FATAL: cannot cd to ${1:-.}" >&2; exit 1; }
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
ALLNAMES=""
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
  # combined alternation, used by the binary/UTF-16 pass below
  if [ -z "$ALLNAMES" ]; then ALLNAMES="$pat"; else ALLNAMES="$ALLNAMES|$pat"; fi

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


# --- 3. Binary and non-UTF-8 files -----------------------------------------
# grep -I skips binary files ENTIRELY, so the formats a leak is most likely to
# arrive in walked straight through: an .xlsx (the client's sales tracker is a
# zip of XML), a UTF-16 text file (what PowerShell and Notepad write by
# default, and the runbooks have the operator in both), and any PDF or doc.
#
# NUL-stripping rather than iconv: without a BOM, `iconv -f UTF-16` guesses the
# wrong endianness and yields mojibake that matches nothing -- it reported
# those files clean. Deleting NUL bytes recovers ASCII from UTF-16LE, UTF-16BE
# and NUL-containing binaries alike, with no guessing.
#
# Fail CLOSED: a binary the sweep cannot read is a binary it cannot clear. The
# tree currently contains none, so the allowlist starts empty on purpose --
# add to it deliberately, per format, with a reason.
BINARY_ALLOW='\.(png|jpg|jpeg|gif|ico|woff2?|ttf|otf)$'
BINARIES=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  grep -Iq . "$f" 2>/dev/null && continue          # ordinary text: swept above
  if tr -d '\000' < "$f" 2>/dev/null | grep -qiE "$ALLNAMES" 2>/dev/null; then
    BINARIES="$BINARIES$f: contains an identifying name (binary/UTF-16)"$'\n'
  elif ! printf '%s\n' "$f" | grep -qE "$BINARY_ALLOW"; then
    BINARIES="$BINARIES$f: binary, and not an allowlisted format -- the sweep cannot read it, so it cannot clear it"$'\n'
  fi
done <<EOF
$(find "$ROOT" -type f -not -path '*/.git/*' -not -path '*/__pycache__/*' 2>/dev/null)
EOF
if [ -n "$(printf '%s' "$BINARIES" | tr -d '[:space:]')" ]; then
  add_hit "$BINARIES"
fi


if [ "$FAIL" -ne 0 ]; then
  printf '%s\n' "$HITS"
  echo "FATAL: identifying content in the tree — NOT safe to commit." >&2
  exit 1
fi
exit 0

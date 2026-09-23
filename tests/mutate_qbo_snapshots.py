#!/usr/bin/env python3
"""Mutation-test tests/regression/test_qbo_snapshots.py against
pipeline/qbo_exports.py and the snapshot writer in mcp/server.py.

Every mutant is the tempting shortcut: read columns by position, accept a
header that half matches, multiply a float by 100 and truncate, round a
sub-cent amount, drop the window's first year, ignore the footer, count a
TOTAL row as an invoice, guess a split account, file a transaction under no
vendor, put the snapshot inside the store, append instead of replace, or
os.replace without the store's Windows-lock retry.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_qbo_snapshots.py"

PARSER = [
 ("columns are read by position, not header name",
  "    col = {n: i for i, n in enumerate(names)}",
  "    col = {n: i for i, n in enumerate(expected)}"),
 ("a header that half matches is loaded",
  "    if sorted(names, key=str) != sorted(expected, key=str):",
  "    if not set(names) & set(expected):"),
 ("a float amount is multiplied by 100 and truncated",
  "    if isinstance(v, int):\n        return v * 100\n",
  "    if isinstance(v, (int, float)):\n        return int(v * 100)\n"),
 ("a sub-cent amount is truncated, not refused",
  "    if not c.is_finite() or c != c.to_integral_value():",
  "    if not c.is_finite():"),
 ("a missing amount reads as 0",
  "    if v is None:\n        return None\n    if isinstance(v, bool):",
  "    if v is None:\n        return 0\n    if isinstance(v, bool):"),
 ("a window across a year takes the end year for both ends",
  '    y1 = int(m.group("y1")) if m.group("y1") else y2',
  "    y1 = y2"),
 ("as_of ignores the footer and uses the window end",
  '            "as_of": as_of or window[1],',
  '            "as_of": window[1],'),
 ("the grand TOTAL row is data",
  '    if isinstance(first, str) and first.strip().upper() == "TOTAL":\n        return True\n',
  ""),
 ("a 'Total for' row is not recognised as a total",
  '            if _empty(g("Date")) and (t.startswith("Total for")\n',
  '            if _empty(g("Date")) and (False\n'),
 ("a vendor named 'Total' is skipped as the grand total",
  '            if _empty(g("Date")) and _empty(g("Amount")):\n                vendor = str(first).strip()\n',
  '            if _empty(g("Date")) and _empty(g("Amount")) and str(first).strip().upper() != "TOTAL":\n'
  '                vendor = str(first).strip()\n'),
 ("a summary row with an amount is read as a vendor",
  '            if _empty(g("Date")) and _empty(g("Amount")):\n',
  '            if _empty(g("Date")):\n'),
 ("a date-typed cell passes as text",
  '    raise QboExportError(f"{where}: {v!r} is not text")',
  "    return v"),
 ("a blank split account is guessed from the account column",
  '                    "split_account": None if _empty(g("Item split account"))\n'
  '                    else _text(g("Item split account"),\n'
  '                               f"{where} Item split account"),',
  '                    "split_account": g("Item split account") or g("Account full name"),'),
 ("a transaction above any vendor row is filed under no vendor",
  '        if vendor is None:\n            raise QboExportError(f"{where}: a transaction above any vendor row")\n',
  ""),
 ("the parser opens the export writable and saves it",
  "        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)",
  "        wb = openpyxl.load_workbook(path, data_only=True); wb.save(path)"),
 ("Posting (Y/N) is kept as text",
  '                    "posting": _yes_no(g("Posting (Y/N)"),\n'
  '                                       f"{where} Posting (Y/N)"),',
  '                    "posting": g("Posting (Y/N)"),'),
]

SERVER = [
 ("the snapshot dir is inside the store",
  '    return STORE.root.parent / "qbo-snapshots"',
  '    return STORE.root / "qbo-snapshots"'),
 ("a second load appends to the rows already on disk",
  '           "rows": rows}\n    d = _qbo_snapshot_dir()',
  '           "rows": (json.loads((_qbo_snapshot_dir() / f"{kind}.json").read_text())["rows"]\n'
  '                    if (_qbo_snapshot_dir() / f"{kind}.json").exists() else []) + rows}\n'
  '    d = _qbo_snapshot_dir()'),
 ("a bare os.replace, without the Windows-lock retry",
  "    Store._commit(tmp, d / fn, fn)",
  "    os.replace(tmp, d / fn)"),
 ("a boolean passes as integer cents",
  "                    (type(v) is not int):",
  "                    (not isinstance(v, int)):"),
 ("cents are not checked at all",
  '            if k.endswith("_cents") and v is not None and \\',
  '            if False and \\'),
 ("an unknown kind is written",
  "    if kind not in QBO_SNAPSHOT_KINDS:",
  "    if False:"),
 ("an unknown source is written",
  "    if source not in QBO_SNAPSHOT_SOURCES:",
  "    if False:"),
 ("a snapshot folder that cannot be created raises a raw OSError",
  '        fd, tmp = tempfile.mkstemp(dir=d, prefix=".~", suffix=".tmp")\n    except OSError as e:',
  '        fd, tmp = tempfile.mkstemp(dir=d, prefix=".~", suffix=".tmp")\n    except ZeroDivisionError as e:'),
 ("a row JSON cannot hold raises a raw TypeError",
  "    except (OSError, TypeError, ValueError) as e:",
  "    except OSError as e:"),
 ("loaded_at is not recorded",
  '           "loaded_at": datetime.now(timezone.utc).isoformat(),\n', ""),
 ("Store startup creates the snapshot dir",
  "    def __init__(self, root: Path):\n        self.root = root\n",
  "    def __init__(self, root: Path):\n        self.root = root\n"
  "        (root.parent / 'qbo-snapshots').mkdir(exist_ok=True)\n"),
]


def main():
    worst = 0
    for title, target, mutants in (("PARSER -- pipeline/qbo_exports.py",
                                    "pipeline/qbo_exports.py", PARSER),
                                   ("SERVER -- mcp/server.py", "mcp/server.py", SERVER)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, TEST, target, mutants))
    return worst


sys.exit(main())

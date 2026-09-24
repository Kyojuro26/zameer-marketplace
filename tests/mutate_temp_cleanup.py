#!/usr/bin/env python3
"""Mutation-test the harness's scratch-store cleanup, graded by
tests/regression/test_temp_cleanup.py.

The code under test is in tests/ (lib/harness.py, run_all.py), not in the
plugin, so mutate_lib.mutate -- which copies the plugin -- cannot reach it.
This copies tests/ per mutant instead and runs the COPY's test module, which
imports the copy's harness (the module puts its own parent first on
sys.path). Scoring is mutate_lib's: run_against, a baseline that must pass,
and a crash is not a kill.
"""
import os, re, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import run_against

TESTS = os.path.dirname(os.path.abspath(__file__))
CRM = os.path.join(os.path.dirname(TESTS), "plugins/unrivaled-solutions/skills/crm")
TEST_IN_COPY = "regression/test_temp_cleanup.py"

MUTANTS = [
 ("lib/harness.py", "cleanup_temp removes nothing",
  "        shutil.rmtree(_OWNED.pop(), ignore_errors=True)\n", "        _OWNED.pop()\n"),
 ("lib/harness.py", "Store() does not record the directory it made",
  "            _OWNED.append(path)\n", ""),
 ("lib/harness.py", "a store given a path is removed too",
  "        if path is None:\n            path = tempfile.mkdtemp(prefix=\"crmtest-\")\n            _OWNED.append(path)\n",
  "        if path is None:\n            path = tempfile.mkdtemp(prefix=\"crmtest-\")\n        _OWNED.append(str(path))\n"),
 ("lib/harness.py", "nothing cleans up at exit",
  "atexit.register(cleanup_temp)\n", ""),
 ("run_all.py", "run_all does not clean up after each module",
  "        finally:\n            cleanup_temp()          # the module's scratch stores, not the next one's\n", ""),
]


def _copy():
    tmp = tempfile.mkdtemp(prefix="mutt-")
    dst = os.path.join(tmp, "tests")
    shutil.copytree(TESTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return tmp, dst


def main():
    tmp, dst = _copy()
    rc, out = run_against(os.path.join(dst, TEST_IN_COPY), CRM)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n=== HARNESS -- tests/lib/harness.py, tests/run_all.py  ({len(MUTANTS)} mutants) ===")
    if rc != 0:
        print("  BASELINE FAILS on the unmutated copy -- every result below would be a false positive.")
        print(out[-600:])
        return 2
    print("  baseline passes on the unmutated copy\n")
    res = []
    for target, label, old, new in MUTANTS:
        tmp, dst = _copy()
        p = os.path.join(dst, target)
        s = open(p, encoding="utf-8").read()
        n = s.count(old)
        if n != 1:
            res.append((label, "ANCHOR-MISSING" if n == 0 else "ANCHOR-AMBIGUOUS", f"{n} matches"))
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        rc, out = run_against(os.path.join(dst, TEST_IN_COPY), CRM)
        first = next((l.strip()[:86] for l in out.splitlines() if l.strip().startswith("x ")), "")
        reported = bool(re.search(r"^\[(PASS|FAIL)\] ", out, re.M))
        res.append((label, "CRASH-NOT-A-KILL" if (rc and not reported) else ("CAUGHT" if rc else "SURVIVED"), first))
        shutil.rmtree(tmp, ignore_errors=True)
    w = max(len(l) for l, _, _ in res); bad = 0
    for label, v, d in res:
        if v != "CAUGHT":
            bad += 1
        print(f"  {label.ljust(w)}  {v}{'' if v == 'CAUGHT' else '   <<<<'}")
        if d:
            print(f"  {' ' * w}  {d}")
    print(f"\n  {len(res) - bad}/{len(res)} mutants caught")
    return 1 if bad else 0


sys.exit(main())

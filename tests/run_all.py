#!/usr/bin/env python3
"""Unrivaled CRM test suite.

    python3 tests/run_all.py                    run everything
    python3 tests/run_all.py --positive-control prove the suite can FAIL
    python3 tests/run_all.py -k identifiers     run one module

Why --positive-control exists
-----------------------------
The suite that preceded this one scored 59/59 on a tree with ~40 known defects
and 59/59 after they were fixed. It could not tell the two apart, so its green
run carried no information. --positive-control checks out the last published
release into a temp dir and runs this suite against it; the run is a SUCCESS
only if the suite fails there. A suite that passes on known-broken code is
broken itself, and this is the only way to know.

Exit code is 0 only when every check passes.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
from lib.harness import load_server  # noqa: E402

PLUGIN = "plugins/unrivaled-solutions/skills/crm"

# The last PUBLISHED release. --positive-control runs against this and requires
# failures. Bump only when a new version actually ships.
BASELINE_REF = "5669d2f"

PY_MODULES = [
    ("regression.test_identifiers", "regression/test_identifiers.py"),
    ("regression.test_visibility", "regression/test_visibility.py"),
    ("regression.test_integrity", "regression/test_integrity.py"),
    ("regression.test_merge", "regression/test_merge.py"),
    ("regression.test_importer", "regression/test_importer.py"),
    ("shapes.test_shape_parity", "shapes/test_shape_parity.py"),
    ("shapes.test_shape_verifiers", "shapes/test_shape_verifiers.py"),
    ("shapes.test_shape_guarantees", "shapes/test_shape_guarantees.py"),
]
JS_MODULES = [("regression/test_view.js", "view")]


def _load(modname, relpath):
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_python(crm_dir, pattern):
    results = []
    server = load_server(crm_dir)
    for modname, relpath in PY_MODULES:
        if pattern and pattern not in modname:
            continue
        mod = _load(modname, relpath)
        try:
            # shape modules need the crm dir for source-level assertions
            import inspect
            if len(inspect.signature(mod.run).parameters) > 1:
                res = mod.run(server, crm_dir)
            else:
                res = mod.run(server)
        except Exception as e:                        # noqa: BLE001
            from lib.harness import Result
            res = Result(modname)
            res.check("module ran to completion", False, f"{type(e).__name__}: {e}")
        results.append(res)
    return results


def run_js(crm_dir, pattern):
    """Run the node-side modules; return (name, ok, checks, detail) tuples."""
    out = []
    for relpath, name in JS_MODULES:
        if pattern and pattern not in name:
            continue
        script = f"""
        const m = require({str(ROOT / relpath)!r});
        const r = m.run({str(crm_dir)!r});
        process.exit(r.report() ? 0 : 1);
        """
        p = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        sys.stdout.write(p.stdout)
        if p.returncode != 0 and not p.stdout.strip():
            print(f"[FAIL] {name}  (harness error)")
            print("        " + (p.stderr.strip().split("\n")[-1] if p.stderr else "?"))
        out.append((name, p.returncode == 0))
    return out


def checkout_baseline(ref):
    """Extract the plugin at `ref` into a temp dir so the suite can be run
    against known-broken code."""
    tmp = Path(tempfile.mkdtemp(prefix="crm-baseline-"))
    p = subprocess.run(["git", "archive", ref, PLUGIN], cwd=REPO,
                       capture_output=True)
    if p.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit(f"cannot read baseline {ref}: {p.stderr.decode()[:200]}")
    tar = tmp / "b.tar"
    tar.write_bytes(p.stdout)
    subprocess.run(["tar", "-xf", str(tar)], cwd=tmp, check=True)
    tar.unlink()
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positive-control", action="store_true",
                    help="run against the last published release; REQUIRE failures")
    ap.add_argument("-k", dest="pattern", default=None, help="substring filter")
    args = ap.parse_args()

    if args.positive_control:
        base = checkout_baseline(BASELINE_REF)
        crm = base / PLUGIN
        print(f"POSITIVE CONTROL -- running the suite against {BASELINE_REF} "
              f"(the last published release).")
        print("A suite that cannot fail on known-broken code proves nothing.\n")
        try:
            results = run_python(str(crm), args.pattern)
            for r in results:
                r.report()
            js = run_js(str(crm), args.pattern)
            failed_modules = [r.name for r in results if r.failed] + \
                             [n for n, ok in js if not ok]
            print()
            if failed_modules:
                print(f"POSITIVE CONTROL PASSED -- the suite detects the baseline's "
                      f"defects in: {', '.join(failed_modules)}")
                (ROOT / ".positive-control-ran").write_text(
                    f"{BASELINE_REF}\n{', '.join(failed_modules)}\n")
                return 0
            print("POSITIVE CONTROL FAILED -- the suite passed on the last "
                  "published release, which is known to be defective.")
            print("The tests are not testing what they claim to test.")
            return 1
        finally:
            shutil.rmtree(base, ignore_errors=True)

    crm = REPO / PLUGIN
    print(f"Unrivaled CRM suite -- {crm.relative_to(REPO)}\n")
    results = run_python(str(crm), args.pattern)
    ok_py = all([r.report() for r in results])   # list: report ALL modules
    js = run_js(str(crm), args.pattern)
    ok_js = all(o for _, o in js)

    total = sum(len(r.passed) + len(r.failed) for r in results)
    failed = sum(len(r.failed) for r in results)
    print()
    print(f"python: {total - failed}/{total} checks passed"
          + (f"   ({failed} failing)" if failed else ""))
    if not (ROOT / ".positive-control-ran").exists():
        print("\nNOTE: --positive-control has never been run. Until it has, a "
              "green result here is not evidence.")
    return 0 if (ok_py and ok_js) else 1


if __name__ == "__main__":
    sys.exit(main())

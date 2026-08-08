#!/usr/bin/env python3
"""Shared mutation runner.

Extracted so the drawer and receivables mutant lists cannot drift apart in how
they are SCORED. This runner has produced a wrong answer twice, both times by
being generous:

  * it read any non-zero exit as a kill, so a mutant that crashed node with an
    empty stdout counted as caught while no assertion had run;
  * it applied anchors as substrings, so a 6-space "      return true;" matched
    inside a 12-space line elsewhere in the file and mutated the wrong function.

Both are guarded below, and the baseline is required to pass before any verdict
is printed. Keep new guards here rather than in a caller.
"""
import os, re, shutil, subprocess, sys, tempfile


def run_against(test_rel, crm_dir):
    """Drive one test module against a (possibly mutated) plugin copy.

    Dispatches on extension: the suite has both node and python modules, and a
    second copy of this runner for python would be one more thing to drift.
    Both paths must print a [PASS]/[FAIL] line -- the caller reads its absence
    as "crashed, not a kill"."""
    if test_rel.endswith(".js"):
        cmd = ["node", "-e",
               f"const m=require({test_rel!r});"
               f"Promise.resolve(m.run({crm_dir!r})).then(r=>process.exit(r.report()?0:1))"
               f".catch(e=>{{console.error(String(e).slice(0,300));process.exit(1)}});"]
    else:
        cmd = ["python3", "-c",
               "import importlib.util,sys\n"
               "sys.path.insert(0,'tests')\n"
               f"spec=importlib.util.spec_from_file_location('m',{test_rel!r})\n"
               "m=importlib.util.module_from_spec(spec)\n"
               "spec.loader.exec_module(m)\n"
               "import inspect\n"
               f"n=len(inspect.signature(m.run).parameters)\n"
               f"res=m.run(None,{crm_dir!r}) if n>1 else m.run(None)\n"
               "sys.exit(0 if res.report() else 1)"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutate(label_src, test_rel, target_file, mutants):
    """label_src: plugin dir to copy. Returns exit status (0 = all caught)."""
    tmp = tempfile.mkdtemp(prefix="base-"); dst = os.path.join(tmp, "crm")
    shutil.copytree(label_src, dst)
    rc, out = run_against(test_rel, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    if rc != 0:
        print("  BASELINE FAILS on the unmutated tree -- every result below would"
              " be a false positive.\n")
        for line in out.splitlines():
            if line.strip().startswith("x ") or line.startswith("["):
                print("   ", line.strip())
        return 2
    print("  baseline passes on the unmutated tree\n")

    res = []
    for label, old, new in mutants:
        tmp = tempfile.mkdtemp(prefix="mut-"); dst = os.path.join(tmp, "crm")
        shutil.copytree(label_src, dst)
        p = os.path.join(dst, target_file)
        s = open(p, encoding="utf-8").read()
        n = s.count(old)
        if n == 0:
            res.append((label, "ANCHOR-MISSING", "mutation never applied -- proves nothing"))
            shutil.rmtree(tmp, ignore_errors=True); continue
        if n > 1:
            res.append((label, "ANCHOR-AMBIGUOUS", f"{n} matches -- would mutate the wrong one"))
            shutil.rmtree(tmp, ignore_errors=True); continue
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        rc, out = run_against(test_rel, dst)
        first = next((l.strip()[:86] for l in out.splitlines() if l.strip().startswith("x ")), "")
        reported = bool(re.search(r"^\[(PASS|FAIL)\] ", out, re.M))
        verdict = "CRASH-NOT-A-KILL" if (rc and not reported) else ("CAUGHT" if rc else "SURVIVED")
        res.append((label, verdict, first))
        shutil.rmtree(tmp, ignore_errors=True)

    w = max(len(l) for l, _, _ in res); bad = 0
    for label, v, d in res:
        if v != "CAUGHT": bad += 1
        print(f"  {label.ljust(w)}  {v}{'' if v=='CAUGHT' else '   <<<<'}")
        if d:
            print(f"  {' '*w}  {d}")
    print(f"\n  {len(res)-bad}/{len(res)} mutants caught")
    return 1 if bad else 0

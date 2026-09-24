"""The suite removes the scratch stores it creates.

lib.harness.Store() made a crmtest-* directory under the system temp dir for
every store it was not given a path for, and nothing removed any of them: one
full run left 22 behind, every mutant run more, and a machine that had run the
suite for a few weeks held thousands. Asserted:

  * cleanup_temp() removes every directory Store() created, and only those --
    a store given an explicit path belongs to its caller and is left alone;
  * run_all removes a module's stores when that module finishes;
  * a module run on its own (as the mutation runner runs it) removes its
    stores when the process exits.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib.harness as H  # noqa: E402
from lib.harness import Result, Store  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]


def run(server, crm_dir=None):
    r = Result("temp-cleanup", since="0.1.43")
    crm = Path(crm_dir) if crm_dir else TESTS.parent / "plugins/unrivaled-solutions/skills/crm"
    srv = server
    if srv is None:
        srv = H.load_server(str(crm))
    if not r.check("the harness exposes cleanup_temp()", callable(getattr(H, "cleanup_temp", None))):
        return r

    r.section("cleanup_temp removes what Store() created, and only that")
    a, b = Store(srv), Store(srv)
    mine = Path(tempfile.mkdtemp(prefix="crm-own-"))
    c = Store(srv, mine / "store")
    r.check("the stores exist while in use", a.path.exists() and b.path.exists() and c.path.exists())
    H.cleanup_temp()
    r.check("cleanup_temp removes both scratch stores", not a.path.exists() and not b.path.exists(),
            f"{a.path.exists()} {b.path.exists()}")
    r.check("... and leaves a store whose path the caller gave", c.path.exists())
    import shutil
    shutil.rmtree(mine, ignore_errors=True)

    r.section("run_all removes a module's stores when it finishes")
    sys.path.insert(0, str(TESTS))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_run_all_under_test", TESTS / "run_all.py")
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    made = []
    real = H.tempfile.mkdtemp

    def spy(*a_, **k):
        p = real(*a_, **k)
        made.append(p)
        return p
    H.tempfile.mkdtemp = spy
    try:
        ra.run_python(str(crm), "test_next_action")
    finally:
        H.tempfile.mkdtemp = real
    r.check("the module made scratch stores (precondition)", len(made) > 0, str(len(made)))
    left = [p for p in made if Path(p).exists()]
    r.check("none is left once run_all moves on", not left, f"{len(left)} of {len(made)} left")

    r.section("a module run on its own cleans up at exit")
    probe = ("import sys\n"
             f"sys.path.insert(0, {str(TESTS)!r})\n"
             "from lib.harness import load_server, Store\n"
             f"s = Store(load_server({str(crm)!r}))\n"
             "print(s.path)\n")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    path = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    r.check("the process made a scratch store (precondition)", "crmtest-" in path, out.stderr[-200:])
    r.check("... and it is gone after the process exits", bool(path) and not Path(path).exists(), path)
    return r

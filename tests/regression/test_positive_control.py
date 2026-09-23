"""The positive control's own scoring (0.1.38).

A module that CRASHES against the baseline has evaluated nothing, so it is
not evidence the suite can detect anything. The node side has said so since
0.1.36 ("NOT COUNTED"). The python side did not: run_python turned a thrown
exception into a synthetic failed check, "module ran to completion", and the
positive control credited that as a detection.

Asserted by running the real scoring on a module that throws and one that
fails a real assertion -- not by reading run_all.py's source.
"""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]


def run(server, crm_dir=None):
    r = Result("positive-control", since="0.1.38")
    crm = Path(crm_dir) if crm_dir else \
        TESTS.parent / "plugins/unrivaled-solutions/skills/crm"
    spec = importlib.util.spec_from_file_location("_run_all_under_test",
                                                  TESTS / "run_all.py")
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    verdict = getattr(ra, "positive_control_verdict", None)
    if not r.check("run_all exposes positive_control_verdict", callable(verdict),
                   "the scoring is inline in main() and cannot be run"):
        return r
    tmp = Path(tempfile.mkdtemp(prefix="pctest-"))
    try:
        (tmp / "crasher.py").write_text(
            "def run(server):\n    raise RuntimeError('died before any check')\n")
        (tmp / "failer.py").write_text(
            "import sys\nsys.path.insert(0, %r)\n"
            "from lib.harness import Result\n"
            "def run(server):\n"
            "    r = Result('failer')\n"
            "    r.check('a real assertion', False, 'wrong value')\n"
            "    return r\n" % str(TESTS))
        res = ra.run_python(str(crm), None,
                            modules=[("pc.crasher", str(tmp / "crasher.py")),
                                     ("pc.failer", str(tmp / "failer.py"))])
        by = {x.name: x for x in res}
        r.check("a python module that throws is marked crashed",
                getattr(by.get("pc.crasher"), "crashed", False) is True,
                sorted(by))
        r.check("a module that fails a real assertion is not marked crashed",
                getattr(by.get("failer"), "crashed", False) is False)
        js = [("js.died", False, False, 0, 0), ("js.failed", False, True, 3, 1)]
        detected, not_counted = verdict(res, js)
        r.check("the crashed python module is NOT COUNTED, not a detection",
                "pc.crasher" in not_counted and "pc.crasher" not in detected,
                (detected, not_counted))
        r.check("the python module that failed an assertion IS a detection",
                "failer" in detected and "failer" not in not_counted,
                (detected, not_counted))
        r.check("node keeps its rule: died -> NOT COUNTED, failed -> detected",
                "js.died" in not_counted and "js.failed" in detected
                and "js.died" not in detected, (detected, not_counted))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r

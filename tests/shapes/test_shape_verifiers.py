"""SHAPE 2 -- a verifier that shares the bug it is meant to catch.

The importer reads "NOT PAID" as paid. The audit script built to check the
importer against the workbook uses the SAME regex, applies the SAME row caps,
and never opens invoices.json at all -- so it certified the mistake as correct
for five releases. The PII sweep cannot read the file format a leak would
actually arrive in. And the regression suite that shipped before this one
scored 59/59 both before and after ~40 defects were fixed.

A verifier that has never been shown a known-bad input is not evidence of
anything. Every checking tool in this repo gets fed something it MUST reject.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _sweep(root):
    """Run the PII sweep against a tree; return its exit code."""
    return subprocess.run([str(REPO / "scripts" / "pii-sweep.sh"), str(root)],
                          capture_output=True, text=True).returncode


def run(server, crm_dir=None):
    r = Result("SHAPE/verifiers", since="all")
    crm = Path(crm_dir) if crm_dir else REPO / "plugins/unrivaled-solutions/skills/crm"

    # ---- the PII sweep must fail on every format a leak can arrive in -------
    r.section("PII sweep: known-bad inputs it must reject")
    tmp = Path(tempfile.mkdtemp(prefix="sweepctl-"))
    try:
        shutil.copy(REPO / ".pii-names", tmp / ".pii-names")
        shutil.copytree(REPO / "scripts", tmp / "scripts")
        (tmp / "docs").mkdir()
        # read the needle from .pii-names -- never hardcode it here;
        # a test file carrying the literal name is itself a leak, and
        # the sweep correctly rejects this file if it does
        names = [n for n in (REPO / ".pii-names").read_text().strip().split("|") if n]
        if not names:
            r.check("the PII sweep has patterns to match", False,
                    ".pii-names is empty -- the sweep protects nothing")
            return r
        needle = names[0]

        cases = {
            "plain UTF-8 text": lambda p: p.write_text(f"contact {needle}\n"),
            "a filename": lambda p: None,          # handled below
            "UTF-16 text (PowerShell/Notepad default)":
                lambda p: p.write_bytes(f"contact {needle}".encode("utf-16-le")),
            "an .xlsx workbook (the client's tracker)":
                lambda p: _xlsx(p, needle),
            "a file containing a NUL byte (PDF, doc)":
                lambda p: p.write_bytes(b"%PDF-1.4\x00 " + needle.encode()),
        }
        for label, make in cases.items():
            for f in (tmp / "docs").iterdir():
                f.unlink()
            if label == "a filename":
                (tmp / "docs" / f"{needle}-notes.md").write_text("nothing inside\n")
            else:
                make(tmp / "docs" / "leak.bin")
            r.check(f"the sweep REJECTS {label}", _sweep(tmp) != 0,
                    "passed clean -- this format can carry a leak into a PUBLIC repo")

        for f in (tmp / "docs").iterdir():
            f.unlink()
        r.check("and it passes a genuinely clean tree", _sweep(tmp) == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- the store/workbook audit must not certify a sabotaged store -------
    r.section("workbook audit: it must not report a destroyed store as clean")
    audit = crm / "pipeline" / "audit_workbook_vs_store.py"
    src = audit.read_text() if audit.exists() else ""
    r.check("the workbook audit reads invoices.json at all",
            bool(re.search(r'["\']invoices["\']', src.split("def main")[0])
                 or "invoices.json" in src),
            "it loads companies/contacts/projects/shipments/vendors only -- "
            "the receivables are never compared to the workbook")

    # ---- no verifier may reproduce the importer's own paid-parsing ---------
    r.section("no checker may repeat the importer's payment parsing")
    negatives = ["NOT PAID", "not paid yet", "never paid", "will be paid net 60",
                 "partially paid", "50% paid, balance due"]
    for name in ("normalize.py", "audit_workbook_vs_store.py",
                 "audit_commission_pct.py"):
        f = crm / "pipeline" / name
        if not f.exists():
            continue
        m = re.search(r'PAID_RE\s*=\s*re\.compile\(\s*r?"([^"]+)"', f.read_text())
        if not m:
            continue
        pat = re.compile(m.group(1))
        wrong = [n for n in negatives if pat.search(n)]
        r.check(f"{name} does not read a negated note as paid",
                not wrong,
                f"reads these as PAID: {wrong}")

    # ---- a verifier must distinguish a good tree from a bad one ------------
    r.section("meta: this suite itself must be able to fail")
    marker = REPO / "tests" / ".positive-control-ran"
    r.check("run_all.py --positive-control has been exercised at least once",
            marker.exists(),
            "run `python3 tests/run_all.py --positive-control` -- a suite that "
            "has never been shown failing code proves nothing")

    return r


def _xlsx(path, needle):
    p = path.with_suffix(".xlsx")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/sharedStrings.xml",
                   f"<sst><si><t>{needle}</t></si></sst>")
    if p != path and path.exists():
        path.unlink()

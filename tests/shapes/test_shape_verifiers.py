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

        # ---- the sweep must actually SWEEP when handed a relative path ------
        # It resolved $1 into a cd and then read "$ROOT/.pii-names" relative to
        # the new cwd, so a relative root looked for tree/tree/.pii-names,
        # missed, and aborted "FATAL: .pii-names is missing". That fails closed
        # -- never unsafe -- but it exits 1 on the CONFIG branch, so anyone
        # positive-controlling the sweep that way proves only that it can
        # return 1, not that it can find a name. Shape 2: the check passes for
        # a reason unrelated to what it claims to check. Both directions, from
        # a different cwd, because one direction cannot tell the two apart.
        rel_leak = tmp / "docs" / f"{needle}-rel.md"
        rel_leak.write_text("nothing inside\n")
        rel = subprocess.run(
            [str(REPO / "scripts" / "pii-sweep.sh"), tmp.name],
            cwd=str(tmp.parent), capture_output=True, text=True)
        r.check("a RELATIVE root still finds a planted name",
                rel.returncode != 0 and "missing or unreadable" not in rel.stderr,
                f"rc={rel.returncode} stderr={rel.stderr.strip()[:120]!r} -- "
                f"aborting on the config branch is not a sweep")
        rel_leak.unlink()
        rel = subprocess.run(
            [str(REPO / "scripts" / "pii-sweep.sh"), tmp.name],
            cwd=str(tmp.parent), capture_output=True, text=True)
        r.check("and passes a clean tree given the same relative root",
                rel.returncode == 0,
                f"rc={rel.returncode} stderr={rel.stderr.strip()[:120]!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- the money reconciler must reject a store that does not add up -----
    #
    # Shape 2 again: a checker is only worth its green run if it can go red.
    # This one exists because audit_workbook_vs_store.py compares counts and
    # fields but never sums anything, so a store could agree field-by-field and
    # still print a wrong total in the top bar -- which is what happened.
    r.section("the money reconciler: known-bad inputs it must reject")
    rec = crm / "pipeline" / "reconcile_workbook.py"
    if not rec.exists():
        r.check("pipeline/reconcile_workbook.py exists", False,
                "nothing reconciles the KPI figures against the workbook")
    else:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("_recon", rec)
        _rc = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_rc)

        bad_inv = [{"invoice_no": "1", "payment_status": "partial:25%",
                    "payment_notes": "Invoice sent on 4/20/26 (D @ 25%)"},
                   {"invoice_no": "2", "payment_status": "partial:25%",
                    "payment_notes": "(D@25%)"},
                   {"invoice_no": "3", "payment_status": "partial:10%",
                    "payment_notes": "10% comm to D"}]
        r.check("it flags a rep's cut stored as a part payment",
                len(_rc.suspicious_percentages(bad_inv)) == 3,
                f"flagged {len(_rc.suspicious_percentages(bad_inv))} of 3 -- "
                f"these are the spellings that reached the real ledger")
        ok_inv = [{"invoice_no": "4", "payment_status": "partial:30%",
                   "payment_notes": "30% deposit received 5/2"},
                  {"invoice_no": "5", "payment_status": "paid",
                   "payment_notes": "(D @ 25%)"}]
        r.check("and does NOT flag a real deposit, or an already-paid invoice",
                _rc.suspicious_percentages(ok_inv) == [],
                "a checker that flags everything is not a checker")

        projects = [{"project_no": "1", "company_id": "a", "revenue": 100,
                     "year": 2026, "status": "won"}]
        h = _rc.invoice_health([{"invoice_no": "9", "company_id": "a",
                                 "payment_status": "open"}], projects)
        r.check("it reports an invoice with no project link as unpriceable",
                h["unpriced"] == 1 and h["screen_total"] == 0,
                f"got {h} -- counting it as zero is how a receivable vanishes")
        h2 = _rc.invoice_health([{"invoice_no": "9", "company_id": "b",
                                  "project_no": "1", "payment_status": "open"}],
                                projects)
        r.check("and does not price it off ANOTHER company's project",
                h2["unpriced"] == 1,
                f"got {h2} -- two customers can hold one project number")

        k = _rc.kpi_totals([
            {"year": 2026, "status": "won", "revenue": 100},
            {"year": "2026", "status": "won", "revenue": "50"},
            {"year": 2025, "status": "won", "revenue": 999},
            {"year": 2026, "status": "pending", "revenue": 7},
        ], 2026)
        r.check("its KPI maths matches build_view's, strings and all",
                k["won"] == 150 and k["pending"] == 7,
                f"got {k} -- a reconciler that computes the total differently "
                f"from the screen reconciles nothing")

    # ---- the store/workbook audit must not certify a sabotaged store -------
    r.section("workbook audit: it must not report a destroyed store as clean")
    audit = crm / "pipeline" / "audit_workbook_vs_store.py"
    src = audit.read_text() if audit.exists() else ""
    # look at the entity list it actually loads, wherever that lives
    loads = re.search(r'for\s+n\s+in\s+\[([^\]]*)\]', src)
    loaded = loads.group(1) if loads else ""
    r.check("the workbook audit loads invoices.json",
            '"invoices"' in loaded or "'invoices'" in loaded,
            f"entity files it loads: {loaded.strip() or '(none found)'} -- the "
            f"receivables are never compared to the workbook")

    # ---- no verifier may reproduce the importer's own paid-parsing ---------
    r.section("no checker may repeat the importer's payment parsing")
    negatives = ["NOT PAID", "not paid yet", "never paid", "will be paid net 60",
                 "partially paid", "50% paid, balance due"]
    # Test the FUNCTION each module decides with, not a raw regex. One module
    # (audit_commission_pct.py) deliberately keeps the bare historical regex to
    # REPLAY the old importer -- that is its purpose -- while judging current
    # truth through says_paid(). Grepping the regex alone would flag that
    # legitimate use and miss a module that had no guard at all.
    import importlib.util
    for name in ("normalize.py", "audit_workbook_vs_store.py",
                 "audit_commission_pct.py", "audit_qualified_paid.py"):
        f = crm / "pipeline" / name
        if not f.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"_v_{name}", f)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:                        # noqa: BLE001
            r.check(f"{name} imports for inspection", False, str(e)[:70])
            continue
        decide = getattr(mod, "says_paid", None) or getattr(mod, "qualified", None)
        if decide is None:
            r.check(f"{name} decides 'paid' through a guarded helper", False,
                    "no says_paid()/qualified() -- a bare regex reads "
                    "'NOT PAID' as paid")
            continue
        if decide.__name__ == "qualified":
            wrong = [n for n in negatives if not decide(n)]
            r.check(f"{name} recognises negated wording as qualified", not wrong,
                    f"treats these as unqualified: {wrong}")
        else:
            wrong = [n for n in negatives if decide(n) is True]
            r.check(f"{name} does not read a negated note as paid", not wrong,
                    f"reads these as PAID: {wrong}")
        r.check(f"{name} still recognises a genuine payment",
                decide("paid 6/1 check 8812") in (True, False),
                "an unqualified 'paid' must still be readable")

    # ---- every module deciding "paid" must give the SAME answer ------------
    r.section("the importer and its checkers cannot drift apart")
    # They carried three separate copies of a bare r"\bpaid\b" and so agreed,
    # wrongly, for five releases. They now share payment_words.py -- this
    # asserts they still do, on wording where a disagreement costs money.
    corpus = [
        ("Paid in full, balance $0", True),      # chasing a paid customer
        ("paid - no balance due", True),
        ("Paid 6/1 check 8812", True),
        ("paid 50%", None),                      # writing off live money
        ("was paid but check bounced", None),
        ("paid - REVERSED", None),
        ("paid to VENDOR, client still owes", None),
        ("disputed - they say paid", None),
        ("NOT PAID as of 7/1", None),
        ("will be paid net 60", None),
        ("Open", False),
        ("unpaid", False),
    ]
    deciders = {}
    for name in ("payment_words.py", "normalize.py", "audit_workbook_vs_store.py",
                 "audit_qualified_paid.py"):
        f = crm / "pipeline" / name
        if not f.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"_pw_{name}", f)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:                      # noqa: BLE001
            r.check(f"{name} imports", False, str(e)[:70])
            continue
        if hasattr(mod, "says_paid"):
            deciders[name] = mod.says_paid
    r.check("every module that decides 'paid' was found",
            len(deciders) >= 3, f"found {sorted(deciders)}")
    for text, want in corpus:
        got = {n: fn(text) for n, fn in deciders.items()}
        r.check(f"all modules agree on {text!r}",
                len(set(got.values())) == 1, str(got))
        r.check(f"and the answer is right for {text!r}",
                all(v == want for v in got.values()),
                f"want {want}, got {got}")

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

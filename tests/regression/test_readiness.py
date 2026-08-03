"""The readiness checker: it runs on the operator's LIVE store.

Two properties matter more than its findings:
  1. it must be strictly READ-ONLY -- it is pointed at the only copy of the
     business's receivables, while the CRM may be open
  2. it must not report CLEAN on a store that has problems, which is the
     failure every other checker in this project has had at least once
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402


def _seed(d, **files):
    d.mkdir(parents=True, exist_ok=True)
    base = {e: [] for e in ("companies", "contacts", "projects", "shipments",
                            "invoices", "vendors", "needs_review")}
    base.update(files)
    for k, v in base.items():
        (d / f"{k}.json").write_text(json.dumps(v, indent=1))
    return d


def _run(script, store):
    p = subprocess.run([sys.executable, str(script), "--store", str(store)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def run(server, crm_dir=None):
    r = Result("readiness", since="0.1.28")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    script = crm / "pipeline" / "readiness_check.py"
    if not script.exists():
        r.check("a read-only readiness checker exists", False,
                "pipeline/readiness_check.py missing -- there is no way to find "
                "out what the operator's real store contains before trusting it")
        return r

    CO = [{"company_id": "acme", "display_name": "Ace", "role": "customer",
           "archived": False}]

    r.section("a clean store reports nothing")
    clean = _seed(Path(tempfile.mkdtemp(prefix="rc-clean-")), companies=CO,
                  projects=[{"project_no": "4521", "company_id": "acme",
                             "revenue": 100, "archived": False}],
                  invoices=[{"invoice_no": "7001", "company_id": "acme",
                             "payment_status": "paid",
                             "payment_status_raw": "PAID",
                             "payment_notes": "ck 8812",
                             "invoice_date": "2026-03-01"}])
    (clean / "changelog.jsonl").write_text("")
    rc, out = _run(script, clean)
    r.check("exit 0 and CLEAN on a healthy store", rc == 0 and "CLEAN" in out,
            f"rc={rc} {out[-120:]}")

    r.section("every defect class is detected")
    bad = _seed(
        Path(tempfile.mkdtemp(prefix="rc-bad-")),
        companies=CO + [{"company_id": "constructor", "display_name": "C",
                         "role": "customer", "archived": False},
                        {"company_id": "gone", "display_name": "G",
                         "role": "customer", "archived": True}],
        projects=[{"project_no": None, "company_id": "acme", "revenue": 1},
                  {"project_no": None, "company_id": "acme", "revenue": 2},
                  {"project_no": "4530", "company_id": "acme"},
                  {"project_no": "4530", "company_id": "acme", "archived": True},
                  {"project_no": "9000.0", "company_id": "acme"}],
        shipments=[{"shipment_id": "noid-L1", "company_id": "acme"},
                   {"shipment_id": "noid-L1", "company_id": "acme"}],
        contacts=[{"company_id": "acme", "name": "A", "email": "?"},
                  {"company_id": "acme", "name": "B", "email": "?"}],
        invoices=[{"invoice_no": "7001", "company_id": "acme",
                   "payment_status": "paid", "payment_status_raw": "Open",
                   "payment_notes": "NOT PAID as of 7/1"},
                  {"invoice_no": "7003", "company_id": None},
                  {"invoice_no": "7004", "company_id": "gone"},
                  {"invoice_no": "7005", "company_id": "acme",
                   "invoice_date": 45731}])
    rc, out = _run(script, bad)
    r.check("exit 1 when there are findings", rc == 1, f"rc={rc}")
    for phrase, why in (
            ("have no project number", "un-numbered projects are frozen"),
            ("used more than once", "duplicate project numbers are frozen"),
            ("nobody can type", "a '.0' identifier is unreachable"),
            ("shipment id(s) used by more than one", "duplicate legs"),
            ("marked PAID whose own notes say otherwise",
             "the falsely-paid receivables -- the whole point"),
            ("attached to no customer", "invoices invisible in the app"),
            ("belong to a DELETED customer", "hidden receivables"),
            ("break the desktop app", "a prototype-name company id"),
            ("cannot read", "unparseable dates"),
            ("no email address", "'?' placeholder contacts")):
        r.check(f"detects: {why}", phrase in out, f"missing {phrase!r}")

    r.section("it refuses rather than reporting clean on an unreadable store")
    broken = _seed(Path(tempfile.mkdtemp(prefix="rc-broken-")), companies=CO)
    (broken / "invoices.json").write_text("{not json")
    rc, out = _run(script, broken)
    r.check("a corrupt store is refused, not reported clean",
            rc == 2 and "CLEAN" not in out, f"rc={rc}")
    (broken / "invoices.json").unlink()
    rc, out = _run(script, broken)
    r.check("a MISSING entity file is refused too",
            rc == 2 and "CLEAN" not in out, f"rc={rc}")

    r.section("it is strictly read-only")
    before = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
              for p in bad.iterdir() if p.is_file()}
    _run(script, bad)
    after = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
             for p in bad.iterdir() if p.is_file()}
    r.check("no store file is modified", before == after,
            f"changed: {[k for k in before if before.get(k) != after.get(k)]}")
    r.check("no file is added to the store",
            set(after) == set(before), f"added: {sorted(set(after) - set(before))}")

    r.section("it will not write its report into the store")
    p = subprocess.run([sys.executable, str(script), "--store", str(bad),
                        "--out", str(bad / "report.md")],
                       capture_output=True, text=True)
    r.check("--out inside the store is refused",
            p.returncode == 2 and not (bad / "report.md").exists(),
            f"rc={p.returncode}")

    import shutil
    for d in (clean, bad, broken):
        shutil.rmtree(d, ignore_errors=True)
    return r

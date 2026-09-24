"""Fields the importer never produces survive a re-import, changelog or not.

merge.py's refresh path starts from the WORKBOOK's record (merged_rec =
dict(rec)) and copies back from the store only the fields the changelog says
the operator touched, plus archived/archived_at. A field the workbook never
produces -- next_action_on, the quote dates, a due-date override -- was
therefore kept ONLY while its changelog line existed. Store.log swallows
OSError (a locked changelog on OneDrive), so an edit can land on disk with no
line, and the next import deleted the field outright. Measured at 8afcf2c:
next_action_on and quote_sent_on both vanished.

The fix is by class: merge.OPERATOR_ONLY names, per file, the fields the
importer never produces, and the refresh path carries each one from the stored
record whenever the workbook's record does not supply it. For EVERY field in
the class, three refreshes are asserted:

  * its changelog line missing, other lines present (the ordinary merge path);
  * the changelog absent entirely (the add-only path);
  * the changelog intact.

Plus three things that keep the fix honest:

  * a TRIPWIRE, per entity file: every key in its *_FIELDS set is emitted by
    the importer (on a synthetic workbook that produces every entity), or is in
    OPERATOR_ONLY, or is in EXCLUDED with its reason. A new operator field
    cannot be added to the server and forgotten here.
  * a DIFFERENTIAL against 8afcf2c's merge.py (read with git show): with an
    intact changelog the two merges write identical stores except for
    OPERATOR_ONLY fields; with lines removed they differ, and only there.
  * pipeline/audit_operator_fields.py, read-only: on a store where the old
    merge wiped fields it lists exactly those, and on a clean store nothing.

Fixture names are invented.
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness import Result, company, invoice, project, shipment  # noqa: E402

# (file, the fresh workbook record, the stored record's extra fields, the key
# Store.log writes). Each stored value differs from anything the workbook says.
CASES = {
    "projects.json": {
        "next_action": "Chase the revised PO",
        "next_action_on": "2026-08-08",
        "quote_requested_on": "2026-07-01",
        "quote_sent_on": "2026-07-03",
        "quote_revisions": [{"requested_on": "2026-07-05", "sent_on": None, "note": "two more options"}],
        "completed_on": "2026-08-01",
        "tracker_key": "5001",
    },
    "shipments.json": {"eta": "2026-09-01"},
    "invoices.json": {"due_on": "2026-09-15", "source": "manual"},
    "companies.json": {"notes": "Prefers calls", "linked_vendor_id": "gamma", "qbo_name": "Ace Mfg"},
    "vendors.json": {"notes": "Net 45", "qbo_name": "Gamma Tooling LLC"},
}
ENTITY = {"projects.json": "project", "shipments.json": "shipment", "invoices.json": "invoice",
          "companies.json": "company", "vendors.json": "vendor"}
LOG_KEY = {"projects.json": "4521", "shipments.json": "4521-L1", "invoices.json": "acme:9001",
           "companies.json": "acme", "vendors.json": "gamma"}


def _base(fname):
    return {"projects.json": project("4521", "acme", revenue=50000),
            "shipments.json": shipment("4521-L1", "4521", "acme"),
            "invoices.json": invoice("9001", "acme", project_no="4521"),
            "companies.json": company("acme", "Ace Manufacturing"),
            "vendors.json": {"company_id": "gamma", "display_name": "Gamma Tooling"}}[fname]


def _fresh(fname, rec):
    out = {"companies.json": [company("acme", "Ace Manufacturing")], "contacts.json": [],
           "vendors.json": [], "shipments.json": [], "invoices.json": [],
           "needs_review.json": [], "projects.json": []}
    out[fname] = [rec]
    return out


def _load_merge(crm):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_oo_merge", Path(crm) / "pipeline" / "merge.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _line(ent, key, fields):
    return json.dumps({"ts": "2026-08-01T00:00:00+00:00", "op": "update", "entity": ent,
                       "key": key, "fields": fields, "interface_version": "0.1"}) + "\n"


def run(server, crm_dir=None):
    r = Result("operator-only", since="0.1.43")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    # a checkout from before merge.py existed has no non-destructive re-import
    # at all: that is the defect, named, not a crash (as test_merge.py does)
    if not r.check("a re-import has a non-destructive path (pipeline/merge.py)",
                   (crm / "pipeline" / "merge.py").exists()):
        return r
    merge = _load_merge(crm)
    oo = getattr(merge, "OPERATOR_ONLY", None)
    r.check("merge.py names the fields the importer never produces (OPERATOR_ONLY)",
            isinstance(oo, dict), repr(oo)[:120])
    oo = oo if isinstance(oo, dict) else {}
    tmp = Path(tempfile.mkdtemp(prefix="crm-oo-"))
    try:
        # behaviour first: a mutant that drops a field should be named by what
        # the operator loses, not by the membership check below
        for fname, fields in CASES.items():
            ent = ENTITY[fname]
            for field, value in fields.items():
                _three_refreshes(r, merge, tmp, fname, ent, field, value)
        for fname, fields in CASES.items():
            missing = sorted(set(fields) - set(oo.get(fname, ())))
            r.check(f"OPERATOR_ONLY[{fname!r}] holds {sorted(fields)}", not missing,
                    f"missing {missing}")
        r.check("no importer-owned field is operator-only",
                not (set(oo.get("projects.json", ())) & set(getattr(merge, "IMPORTER_OWNED", set()))))
        _fresh_supplies(r, merge, tmp)
        _tripwire(r, crm, tmp, oo)
        _differential(r, crm, tmp, oo)
        _audit_checks(r, crm, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _store(tmp, fname, stored, changelog):
    d = Path(tempfile.mkdtemp(dir=tmp))
    for f in ("companies.json", "contacts.json", "vendors.json", "shipments.json",
              "invoices.json", "needs_review.json", "projects.json"):
        d.joinpath(f).write_text("[]")
    d.joinpath(fname).write_text(json.dumps([stored]))
    if changelog is not None:
        d.joinpath("changelog.jsonl").write_text(changelog)
    return d


def _three_refreshes(r, merge, tmp, fname, ent, field, value):
    stored = dict(_base(fname), **{field: value})
    fresh = _base(fname)                          # the workbook: no such field
    other = _line("contact", "contact-1", {"phone": "1"})
    for how, log in (("its changelog line missing", other),
                     ("the changelog absent", None),
                     ("the changelog intact", other + _line(ent, LOG_KEY[fname], {field: value}))):
        d = _store(tmp, fname, stored, log)
        try:
            merged, _ = merge.merge_all(_fresh(fname, dict(fresh)), str(d))
            got = (merged.get(fname) or [{}])[0].get(field, "<absent>")
        except Exception as exc:                                  # noqa: BLE001
            got = f"<raised {type(exc).__name__}: {exc}>"
        r.check(f"{fname} {field}: kept on a re-import with {how}", got == value,
                f"got {json.dumps(got)[:100]}")
    # the workbook carrying the key as null is "not supplied", not "clear it"
    d = _store(tmp, fname, stored, other)
    merged, _ = merge.merge_all(_fresh(fname, dict(fresh, **{field: None})), str(d))
    r.check(f"{fname} {field}: a workbook null does not clear it",
            (merged.get(fname) or [{}])[0].get(field) == value)


def _fresh_supplies(r, merge, tmp):
    """Carry-over fills a gap; it never overrides a value the workbook supplies
    for a field the operator did not touch."""
    d = _store(tmp, "invoices.json", dict(_base("invoices.json"), due_on="2026-09-15"),
               _line("contact", "contact-1", {"phone": "1"}))
    merged, _ = merge.merge_all(
        _fresh("invoices.json", dict(_base("invoices.json"), due_on="2026-10-01")), str(d))
    r.check("a value the workbook supplies wins over the stored one when untouched",
            merged["invoices.json"][0].get("due_on") == "2026-10-01",
            json.dumps(merged["invoices.json"][0])[:160])
    d = _store(tmp, "projects.json", dict(_base("projects.json"), revenue=1),
               _line("contact", "contact-1", {"phone": "1"}))
    merged, _ = merge.merge_all(_fresh("projects.json", _base("projects.json")), str(d))
    r.check("a field the workbook owns still refreshes",
            merged["projects.json"][0].get("revenue") == 50000)



# Keys in a *_FIELDS set the importer never emits and that are NOT operator-only
# carry-over, each with its reason. contacts.json has none: the importer emits
# every CONTACT_FIELDS key, and no contact field is operator-only.
_SOFT_DELETE = "soft-delete: merge carries archived/archived_at by its own rule"
EXCLUDED = {
    "projects.json": {"archived": _SOFT_DELETE, "archived_at": _SOFT_DELETE},
    "companies.json": {"archived": _SOFT_DELETE, "archived_at": _SOFT_DELETE},
    "vendors.json": {"archived": _SOFT_DELETE, "archived_at": _SOFT_DELETE},
    "shipments.json": {}, "invoices.json": {}, "contacts.json": {},
}
BASE_REF = "8afcf2c"


def _workbook(path):
    """The Live Tracker fixture plus one client contact, one vendor contact and
    one invoice row, so the importer emits every entity file."""
    import openpyxl
    import test_livetracker as lt
    lt._build_workbook(path)
    wb = openpyxl.load_workbook(path)
    at = "@"            # built, not written: the PII sweep refuses email literals
    wb["Client Contacts"].append(["Brightwater Fabrication", "Pat Doe", f"pat{at}brightwater.test",
                                  "555-0100", "Buyer", "Dayton OH", "Called re quote", "2026-07-01"])
    wb["Vendor Contacts"].append(["Gamma Tooling", "Columbus OH", "Sam Roe", f"sam{at}gamma.test",
                                  "555-0101", "Frames", f"po{at}gamma.test", f"ap{at}gamma.test"])
    wb["Project Tracker"].append(["5001-INV 7001", "PO-5001", "2026-07-15", "2026-08-14",
                                  "Brightwater Fabrication", "paid 7/30 (50%)"])
    wb.save(path)


def _import(crm, xl, store, merge_mod=None):
    """normalize.run(mode="merge") -- the operator's import path. merge_mod, when
    given, is the module normalize's `import merge` resolves to."""
    import test_livetracker as lt
    added = str(Path(crm) / "pipeline")
    sys.path.insert(0, added)
    prior = sys.modules.pop("merge", None)
    if merge_mod is not None:
        sys.modules["merge"] = merge_mod
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            lt._load(crm, "normalize.py").run(str(xl), str(store), force=False, mode="merge")
    finally:
        sys.modules.pop("merge", None)
        if prior is not None:
            sys.modules["merge"] = prior
        try:
            sys.path.remove(added)
        except ValueError:
            pass


def _tripwire(r, crm, tmp, oo):
    from lib.harness import load_server
    srv = load_server(str(crm))
    xl = tmp / "trip.xlsx"
    _workbook(xl)
    out = tmp / "trip-store"
    out.mkdir()
    _import(crm, xl, out)
    sets = {"projects.json": "PROJECT_FIELDS", "shipments.json": "SHIPMENT_FIELDS",
            "invoices.json": "INVOICE_FIELDS", "companies.json": "COMPANY_FIELDS",
            "contacts.json": "CONTACT_FIELDS", "vendors.json": "VENDOR_FIELDS"}
    for fname, attr in sets.items():
        recs = json.loads((out / fname).read_text())
        emitted = {k for rec in recs for k in rec}
        known = set(getattr(srv, attr))
        mine, excl = set(oo.get(fname, ())), set(EXCLUDED[fname])
        gap = sorted(known - emitted - mine - excl)
        r.check(f"tripwire {fname}: every {attr} key is emitted, operator-only or excluded",
                bool(recs) and not gap, f"{len(recs)} records; unaccounted: {gap}")
        r.check(f"tripwire {fname}: nothing emitted is operator-only or excluded",
                not (emitted & (mine | excl)), sorted(emitted & (mine | excl)))


def _old_merge(tmp):
    """merge.py as it stood at BASE_REF, from git, as a module."""
    import importlib.util
    root = Path(__file__).resolve().parents[2]
    rel = "plugins/unrivaled-solutions/skills/crm/pipeline/merge.py"
    res = subprocess.run(["git", "-C", str(root), "show", f"{BASE_REF}:{rel}"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        return None
    p = tmp / "merge_at_base.py"
    p.write_text(res.stdout)
    spec = importlib.util.spec_from_file_location("merge", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _new_merge(crm):
    import importlib.util
    spec = importlib.util.spec_from_file_location("merge", Path(crm) / "pipeline" / "merge.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _seed(crm, tmp, name):
    """A store imported from the fixture workbook, then edited through the
    server so every edit has its changelog line. Returns (store, xl, edits):
    edits maps (entity, key, field) to the changelog line index that set it."""
    from lib.harness import Store, load_server
    xl = tmp / f"{name}.xlsx"
    _workbook(xl)
    store = tmp / name
    store.mkdir()
    _import(crm, xl, store)
    srv = load_server(str(crm))
    s = Store.__new__(Store)
    s.server, s.path = srv, store
    s.rebind()
    rd = lambda f: json.loads((store / f).read_text())
    proj = {str(p["project_no"]): p["company_id"] for p in rd("projects.json")}
    leg = rd("shipments.json")[0]["shipment_id"]
    inv = rd("invoices.json")[0]
    ven = rd("vendors.json")[0]["company_id"]
    calls = [
        ("update_project", dict(project_no="5001", company_id=proj["5001"], fields={"next_action_on": "2026-08-20"})),
        ("update_project", dict(project_no="5002", company_id=proj["5002"], fields={"quote_requested_on": "2026-07-01"})),
        ("update_project", dict(project_no="5002", company_id=proj["5002"], fields={"quote_sent_on": "2026-07-03"})),
        ("update_project", dict(project_no="5003", company_id=proj["5003"], fields={"next_action": "Chase frames"})),
        ("update_project", dict(project_no="5003", company_id=proj["5003"], fields={"next_action": "Chase the balance"})),
        ("update_shipment", dict(shipment_id=leg, fields={"eta": "2026-09-10"})),
        ("update_invoice", dict(company_id=inv["company_id"], invoice_no=inv["invoice_no"], fields={"due_on": "2026-09-30"})),
        ("update_company", dict(company_id=proj["5001"], fields={"notes": "Prefers calls"})),
        ("update_vendor", dict(company_id=ven, fields={"qbo_name": "Gamma Tooling LLC"})),
    ]
    for tool, args in calls:
        res = s.call(tool, **args)
        if not res.get("ok"):
            raise AssertionError(f"seed edit {tool} {args} refused: {res}")
    keys = {"project": lambda a: a["project_no"], "shipment": lambda a: a["shipment_id"],
            "invoice": lambda a: f"{a['company_id']}:{a['invoice_no']}",
            "company": lambda a: a["company_id"], "vendor": lambda a: a["company_id"]}
    return store, xl, {"proj": proj, "leg": leg, "inv": f"{inv['company_id']}:{inv['invoice_no']}",
                       "ven": ven, "keys": keys}


def _files(store):
    return {p.name: p.read_text() for p in sorted(store.iterdir()) if p.suffix == ".json"}


def _diff(a, b):
    """{file: set of fields that differ} over two stores' json files, or a
    string naming a structural difference no field set can express."""
    out = {}
    fa, fb = _files(a), _files(b)
    if set(fa) != set(fb):
        return f"file sets differ: {sorted(set(fa) ^ set(fb))}"
    for name in fa:
        ja, jb = json.loads(fa[name]), json.loads(fb[name])
        if not (isinstance(ja, list) and isinstance(jb, list)) or len(ja) != len(jb):
            if ja != jb:
                return f"{name}: shape or length differs"
            continue
        for ra, rb in zip(ja, jb):
            if ra == rb:
                continue
            if not (isinstance(ra, dict) and isinstance(rb, dict)):
                return f"{name}: a non-record differs"
            out.setdefault(name, set()).update(
                k for k in set(ra) | set(rb) if ra.get(k, "<absent>") != rb.get(k, "<absent>"))
    return out


def _outside(diff, oo):
    return {f: sorted(ks - set(oo.get(f, ()))) for f, ks in diff.items() if ks - set(oo.get(f, ()))}


def _differential(r, crm, tmp, oo):
    old = _old_merge(tmp)
    if not r.check(f"differential: merge.py at {BASE_REF} loads from git", old is not None):
        return
    new = _new_merge(crm)
    store, xl, _ = _seed(crm, tmp, "diff-seed")
    a, b = tmp / "diff-old", tmp / "diff-new"
    shutil.copytree(store, a)
    shutil.copytree(store, b)
    _import(crm, xl, a, old)
    _import(crm, xl, b, new)
    d = _diff(a, b)
    r.check(f"differential, changelog intact: {BASE_REF} and the new merge differ only in "
            f"OPERATOR_ONLY fields", isinstance(d, dict) and not _outside(d, oo), repr(d)[:200])
    # not vacuous: hide two edits' lines and the merges must differ -- there only
    log = (store / "changelog.jsonl").read_text().splitlines(keepends=True)
    keep = [l for l in log if not any(f in json.loads(l).get("fields", {})
                                      for f in ("next_action_on", "due_on"))]
    a, b = tmp / "diff-old-2", tmp / "diff-new-2"
    for d_ in (a, b):
        shutil.copytree(store, d_)
        (d_ / "changelog.jsonl").write_text("".join(keep))
    _import(crm, xl, a, old)
    _import(crm, xl, b, new)
    d = _diff(a, b)
    r.check("differential, two lines hidden: the merges differ in exactly those two fields",
            isinstance(d, dict) and d == {"projects.json": {"next_action_on"},
                                          "invoices.json": {"due_on"}}, repr(d)[:200])


def _load_audit(crm):
    import importlib.util
    p = Path(crm) / "pipeline" / "audit_operator_fields.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location("_audit_operator_fields", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _digest(store):
    return {p.name: p.read_bytes() for p in sorted(store.iterdir()) if p.is_file()}


def _audit_checks(r, crm, tmp):
    aud = _load_audit(crm)
    if not r.check("pipeline/audit_operator_fields.py exists and loads", aud is not None):
        return
    old = _old_merge(tmp)
    store, xl, ids = _seed(crm, tmp, "audit-seed")
    proj = ids["proj"]
    WIPE = {("project", "5001", "next_action_on"), ("project", "5002", "quote_sent_on"),
            ("invoice", ids["inv"], "due_on"), ("shipment", ids["leg"], "eta"),
            ("company", proj["5001"], "notes"), ("vendor", ids["ven"], "qbo_name")}

    # the wipe, reproduced: the edits' lines were invisible to an import by the
    # 8afcf2c merge (a locked or not-yet-synced changelog), then reappeared
    w = tmp / "audit-wiped"
    shutil.copytree(store, w)
    full = (w / "changelog.jsonl").read_text()
    lines = full.splitlines(keepends=True)
    hide = lambda e: any((e.get("entity"), e.get("key"), f) in WIPE for f in e.get("fields") or {})
    (w / "changelog.jsonl").write_text("".join(l for l in lines if not hide(json.loads(l))))
    if not r.check("audit: the 8afcf2c merge loads from git to reproduce the wipe", old is not None):
        return
    _import(crm, xl, w, old)
    (w / "changelog.jsonl").write_text(full)
    before = _digest(w)
    res = aud.audit(str(w))
    got = {(f["entity"], f["key"], f["field"]) for f in res["findings"]}
    r.check("audit on the wiped store lists exactly the wiped fields", got == WIPE,
            f"extra {sorted(got - WIPE)} missing {sorted(WIPE - got)}")
    r.check("... each with the changelog value, '<missing>' and the changelog timestamp",
            all(f["stored_value"] == "<missing>" and f["changelog_value"] is not None
                and f["changelog_ts"] for f in res["findings"]), json.dumps(res["findings"])[:200])
    r.check("... and nothing unmatched or ambiguous", not res["unmatched"] and not res["ambiguous"],
            json.dumps(res)[:200])
    cli = subprocess.run([sys.executable, str(Path(crm) / "pipeline" / "audit_operator_fields.py"),
                          "--store", str(w), "--json"], capture_output=True, text=True, timeout=60)
    try:
        cli_n = len(json.loads(cli.stdout)["findings"])
    except (ValueError, KeyError):
        cli_n = None
    r.check("the command line reports the same findings", cli_n == len(WIPE), (cli.stdout + cli.stderr)[-200:])
    inside = subprocess.run([sys.executable, str(Path(crm) / "pipeline" / "audit_operator_fields.py"),
                             "--store", str(w), "--out", str(w / "report.txt")],
                            capture_output=True, text=True, timeout=60)
    r.check("--out inside the store is refused", inside.returncode != 0
            and not (w / "report.txt").exists(), inside.stderr[-160:])
    r.check("the audit wrote nothing into the store", _digest(w) == before)

    # clean: the same edits, re-imported by the new merge
    c = tmp / "audit-clean"
    shutil.copytree(store, c)
    _import(crm, xl, c)
    res = aud.audit(str(c))
    r.check("audit on a clean store lists nothing",
            not res["findings"] and not res["unmatched"] and not res["ambiguous"]
            and res["fields_checked"] > 0, json.dumps(res)[:200])
    r.check("... including a field edited twice, whose store holds the second value",
            not any(f["field"] == "next_action" for f in res["findings"]))

    # simulated disagreements the merge cannot produce, one per rule
    _audit_simulated(r, aud, crm, tmp)
    _audit_review1(r, aud, crm, tmp)


def _audit_simulated(r, aud, crm, tmp):
    from lib.harness import Store, load_server
    srv = load_server(str(crm))
    s = Store(srv, tmp / "audit-sim")
    s.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
            projects=[project("4521", "acme"), project("4521", "beta"),
                      project("4522", "acme"), project("4522", "beta"),
                      project("4600", "acme"), project("4700", "acme"),
                      project("4900", "acme")],
            invoices=[invoice("9001", "acme", project_no="4600")])
    s.call("update_project", project_no="4521", company_id="acme", fields={"next_action_on": "2026-08-20"})
    s.call("update_project", project_no="4600", company_id="acme", fields={"next_action": "Old"})
    s.call("rename_project", old_project_no="4600", new_project_no="4610", company_id="acme")
    s.call("update_project", project_no="4700", company_id="acme", fields={"next_action": "Call"})
    s.call("update_project", project_no="4700", company_id="acme", fields={"next_action": None})
    s.call("update_project", project_no="4900", company_id="acme", fields={"next_action": "Call"})
    s.call("update_project", project_no="4900", company_id="acme", fields={"next_action": None})
    s.call("update_invoice", company_id="acme", invoice_no="9001", fields={"due_on": "2026-09-30"})
    s.call("create_project", fields={"project_no": "4800", "company_id": "acme", "next_action": "New"})
    with open(s.path / "changelog.jsonl", "a") as f:       # a pre-0.1.41 line: no company
        f.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "op": "update", "entity": "project",
                            "key": "4522", "fields": {"next_action": "Either"}}) + "\n")
    ps = s.read("projects")
    for p in ps:
        k = (str(p["project_no"]), p["company_id"])
        if k in (("4521", "acme"), ("4610", "acme"), ("4800", "acme")):
            p.pop("next_action_on" if k[0] == "4521" else "next_action", None)
        if k == ("4700", "acme"):
            p["next_action"] = "Call"          # a cleared field resurrected
        if k == ("4900", "acme"):
            p.pop("next_action", None)         # cleared, then the key dropped: both read empty
    s.write("projects", ps)
    inv = s.read("invoices")
    inv[0]["due_on"] = "2026-10-15"            # different, not missing
    s.write("invoices", inv)
    res = aud.audit(str(s.path))
    got = {(f["entity"], f["key"], f["field"]): f for f in res["findings"]}
    r.check("audit scopes a project by its customer: acme's 4521, not beta's",
            ("project", "4521", "next_action_on") in got
            and got[("project", "4521", "next_action_on")]["company_id"] == "acme", json.dumps(res)[:200])
    r.check("audit follows a rename: the edit made under 4600 is checked on 4610",
            ("project", "4610", "next_action") in got, json.dumps(res)[:200])
    r.check("audit reads a create: 4800's next_action set at creation",
            ("project", "4800", "next_action") in got, json.dumps(res)[:200])
    r.check("audit counts a recorded null: 4700 cleared, then resurrected on disk",
            ("project", "4700", "next_action") in got
            and got[("project", "4700", "next_action")]["changelog_value"] is None, json.dumps(res)[:200])
    r.check("audit lists a different value, not only a missing one",
            got.get(("invoice", "acme:9001", "due_on"), {}).get("stored_value") == "2026-10-15",
            json.dumps(res)[:200])
    r.check("a line with no customer on a shared number is ambiguous, never a finding",
            any(a["key"] == "4522" for a in res["ambiguous"])
            and ("project", "4522", "next_action") not in got, json.dumps(res)[:200])
    r.check("a recorded null against a missing field is not a finding",
            ("project", "4900", "next_action") not in got, json.dumps(res)[:200])
    r.check("and exactly those five findings", len(got) == 5, sorted(got))


def _audit_review1(r, aud, crm, tmp):
    """Review round 1 found five ways to get a wrong answer out of the audit."""
    import os
    from lib.harness import Store, load_server
    srv = load_server(str(crm))
    script = str(Path(crm) / "pipeline" / "audit_operator_fields.py")

    # 1. a changelog with malformed lines: no crash, and the skips are counted
    s = Store(srv, tmp / "audit-malformed")
    s.reset(companies=[company("acme", "Ace Manufacturing")], projects=[project("4521", "acme")])
    s.call("update_project", project_no="4521", company_id="acme", fields={"next_action": "Call"})
    ps = s.read("projects"); ps[0].pop("next_action"); s.write("projects", ps)
    bad = ['{"torn": ', '[]', '"text"',
           json.dumps({"op": "update", "entity": ["project"], "key": "4521", "fields": {"next_action": "x"}}),
           json.dumps({"op": "update", "entity": {"a": 1}, "key": "4521", "fields": {"next_action": "x"}}),
           json.dumps({"op": "update", "entity": "project", "key": "4521", "company_id": ["acme"],
                       "fields": {"next_action": "x"}}),
           json.dumps({"op": "update", "entity": "project", "key": "4521", "fields": "next_action"}),
           json.dumps({"op": "update", "entity": "project", "key": ["4521"], "fields": {"next_action": "x"}})]
    with open(s.path / "changelog.jsonl", "a") as f:
        f.write("\n".join(bad) + "\n")
    try:
        res = aud.audit(str(s.path))
        crashed = None
    except Exception as exc:                                       # noqa: BLE001
        res, crashed = {}, f"{type(exc).__name__}: {exc}"
    r.check("audit: malformed changelog lines do not crash it", crashed is None, str(crashed))
    r.check("... every unreadable line is counted, not silently dropped",
            res.get("skipped_lines") == len(bad), json.dumps(res.get("skipped_lines")))
    r.check("... and the readable lines are still audited",
            [(f["key"], f["field"]) for f in res.get("findings", [])] == [("4521", "next_action")],
            json.dumps(res.get("findings"))[:200])

    # 2. no changelog: never a clean result
    s = Store(srv, tmp / "audit-nolog")
    s.reset(companies=[company("acme", "Ace Manufacturing")], projects=[project("4521", "acme")])
    res = aud.audit(str(s.path))
    r.check("audit: a store with no changelog says so, not 'nothing differs'",
            res.get("changelog") == "missing", json.dumps(res)[:200])
    out = subprocess.run([sys.executable, script, "--store", str(s.path)], capture_output=True, text=True, timeout=60)
    r.check("... the command line says it is not a clean result, and exits non-zero",
            out.returncode != 0 and "not a clean result" in out.stdout, (out.stdout + out.stderr)[-200:])

    # 3. a superseded entry with no customer is not compared
    s = Store(srv, tmp / "audit-superseded")
    s.reset(companies=[company("acme", "Ace Manufacturing")],
            projects=[project("4521", "acme", next_action_on="2026-09-01")])
    with open(s.path / "changelog.jsonl", "w") as f:
        f.write(json.dumps({"ts": "1", "op": "update", "entity": "project", "key": "4521",
                            "fields": {"next_action_on": "2026-08-01"}}) + "\n")
        f.write(json.dumps({"ts": "2", "op": "update", "entity": "project", "key": "4521", "company_id": "acme",
                            "fields": {"next_action_on": "2026-09-01"}}) + "\n")
    res = aud.audit(str(s.path))
    r.check("audit: a newer entry for the customer supersedes an older one without a customer",
            not res["findings"] and not res["ambiguous"], json.dumps(res)[:200])
    s.reset(companies=[company("acme", "Ace Manufacturing")],
            projects=[project("4521", "acme", next_action="Second")])
    with open(s.path / "changelog.jsonl", "w") as f:
        for ts, v in (("1", "First"), ("2", "Second")):
            f.write(json.dumps({"ts": ts, "op": "update", "entity": "project", "key": "4521",
                                "fields": {"next_action": v}}) + "\n")
    res = aud.audit(str(s.path))
    r.check("audit: of two entries without a customer on a one-holder number, the later wins",
            not res["findings"] and res["fields_checked"] == 1, json.dumps(res)[:200])

    # 4. a rename moves only the renamed customer's entries
    s = Store(srv, tmp / "audit-rename-shared")
    s.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
            projects=[project("4600", "acme"), project("4600", "beta")])
    s.call("update_project", project_no="4600", company_id="beta", fields={"quote_sent_on": "2026-07-03"})
    s.call("rename_project", old_project_no="4600", new_project_no="4999", company_id="acme")
    log = [json.loads(l) for l in (s.path / "changelog.jsonl").read_text().splitlines() if l.strip()]
    r.check("rename_project logs which customer's project it renamed",
            any(e.get("op") == "rename" and e.get("company_id") == "acme" for e in log), json.dumps(log)[-200:])
    ps = s.read("projects")
    for p in ps:
        if p["company_id"] == "beta":
            p.pop("quote_sent_on", None)
    s.write("projects", ps)
    res = aud.audit(str(s.path))
    r.check("audit: another customer's rename does not carry this customer's entries away",
            any(f["key"] == "4600" and f["company_id"] == "beta" and f["field"] == "quote_sent_on"
                for f in res["findings"]), json.dumps(res)[:240])

    # 5. --out resolving into the store, by any spelling, is refused
    s = Store(srv, tmp / "audit-outstore")
    s.reset(companies=[company("acme", "Ace Manufacturing")], projects=[project("4521", "acme")])
    before = _digest(s.path)
    outside = tmp / "audit-outside"
    outside.mkdir()
    os.link(s.path / "projects.json", outside / "hard.json")
    (outside / "lnk").symlink_to(s.path, target_is_directory=True)
    tries = [("a hard link to a store file", outside / "hard.json"),
             ("a path through a symlinked directory", outside / "lnk" / "report.txt")]
    other_case = s.path.parent / s.path.name.swapcase()
    if other_case.exists():                       # a case-insensitive filesystem
        tries.append(("the store's path spelled in another case", other_case / "projects.json"))
    r.check("the case-variant probe applies here (a case-insensitive filesystem)", other_case.exists()
            or sys.platform != "darwin", str(other_case))
    for what, dest in tries:
        out = subprocess.run([sys.executable, script, "--store", str(s.path), "--out", str(dest)],
                             capture_output=True, text=True, timeout=60)
        r.check(f"--out as {what} is refused", out.returncode != 0, (out.stdout + out.stderr)[-160:])
    r.check("... and the store is byte-identical after every attempt", _digest(s.path) == before)

    # round 2: a directory, the store itself, a missing parent -- a message, not a traceback
    for what, dest in (("the store directory itself", s.path), ("a directory", outside),
                       ("a path whose parent does not exist", outside / "nope" / "r.txt")):
        out = subprocess.run([sys.executable, script, "--store", str(s.path), "--out", str(dest)],
                             capture_output=True, text=True, timeout=60)
        r.check(f"--out as {what} fails with a message, not a traceback",
                out.returncode != 0 and "Traceback" not in out.stderr and "FATAL" in out.stderr,
                out.stderr[-200:])
    r.check("... and the store is still byte-identical", _digest(s.path) == before)

    # round 2: an entry without a customer, on a number two customers held, is
    # not pinned to whichever of them renames first
    s = Store(srv, tmp / "audit-rename-legacy")
    s.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
            projects=[project("4600", "acme"), project("4600", "beta", next_action_on="2026-09-01")])
    with open(s.path / "changelog.jsonl", "w") as f:
        f.write(json.dumps({"ts": "1", "op": "update", "entity": "project", "key": "4600",
                            "fields": {"next_action_on": "2026-09-01"}}) + "\n")
    s.call("rename_project", old_project_no="4600", new_project_no="4999", company_id="acme")
    res = aud.audit(str(s.path))
    r.check("audit: a customer's rename does not pin an unscoped entry on a shared number to it",
            not res["findings"], json.dumps(res)[:240])
    r.check("... the entry is listed as ambiguous instead", any(a_["field"] == "next_action_on" for a_ in res["ambiguous"]),
            json.dumps(res)[:240])

    # round 2: an entry the audit cannot place names its customer and says why
    s = Store(srv, tmp / "audit-moved")
    s.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
            projects=[project("4700", "acme")])
    s.call("update_project", project_no="4700", company_id="acme", fields={"next_action_on": "2026-09-01"})
    s.call("update_project", project_no="4700", company_id="acme", fields={"company_id": "beta"})
    res = aud.audit(str(s.path))
    text = aud.render(res, str(s.path))
    r.check("audit: an entry for a customer that no longer holds the number is unmatched, naming the customer",
            any(u["key"] == "4700" and u["company_id"] == "acme" for u in res["unmatched"])
            and "4700 (acme)" in text, text[-300:])
    r.check("... and the report says the record may have moved or been renamed, to check by hand",
            "check by hand" in text, text[-300:])

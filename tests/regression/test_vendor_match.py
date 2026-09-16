"""Vendors on shipment legs, from the PO text: one parse rule, exact or
aliased matching, never a guess.

Three decisions are asserted, each with an obvious wrong version:

 1. THE TOKEN IS THE LAST NON-PAYMENT PARENTHETICAL. "(70% Paid)", "(PAID)"
    and "(Paid)" are payment notes, not vendors; of two vendor-looking
    parentheticals the last wins; no parenthetical, or no text at all, is no
    token. Taking the first, or taking a payment note, files a leg under a
    vendor called "Paid".
 2. A MATCH IS EXACT ON THE NORMALISED NAME, OR AN ALIAS THE OPERATOR WROTE.
    "Save-ty Yellow" and "SaveTy Yellow" are one key; "FS" is not "FS Racking"
    until vendor_aliases.json says so; "JnL" matches nothing. A name two vendor
    records collapse onto is ambiguous, and an alias naming no vendor record is
    reported, not used.
 3. REPORT MODE WRITES NOTHING, lists every leg without a vendor, never lists
    a leg that already has one, and tables the unmatched tokens by count.

The rule is one function shared by the backfill script and the importer, so
it is tested directly (pipeline/vendor_match.py) and through the script.
Fixture names are invented.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, shipment  # noqa: E402


def _load(crm, name):
    import importlib.util
    p = Path(crm) / "pipeline" / f"{name}.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_{name}_under_test", p)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(p.parent))
    try:
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(str(p.parent))
    return m


def run(server, crm_dir=None):
    r = Result("vendor-match", since="0.1.37")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    vm = _load(crm, "vendor_match")
    if not r.check("pipeline/vendor_match.py exists", vm is not None,
                   "no shared rule -- the script and the importer would each guess"):
        return r

    # ---- 1. the token --------------------------------------------------------------
    r.section("the token is the last non-payment parenthetical")
    for po, want in (("PO # 1252 (FS)", "FS"),
                     ("PO # 1220 (Baihu Designs) (PAID)", "Baihu Designs"),
                     ("PO # 1253 (Dickgistics) (Paid)", "Dickgistics"),
                     ("PO # 1235 (BHD) (70% Paid)", "BHD"),
                     ("PO # 1139 Baihu Designs (PAID)", None),
                     ("PO # 1300 (Interlake) (FS)", "FS"),
                     ("PO # 1301 (Paid) (FS)", "FS"),
                     ("PO # 1302 ( ) (FS)", "FS"),
                     ("PO # 1303 (  J&L Wire  )", "J&L Wire"),
                     ("(50% paid)", None),
                     # a percentage alone is a payment note too: the survivor
                     # that found this had every "%" case also saying "paid"
                     ("PO # 1305 (Interlake) (30%)", "Interlake"),
                     ("PO # 1306 (100%)", None),
                     ("PO # 1304", None),
                     ("", None), (None, None), (12345, None), (True, None)):
        got = vm.vendor_token(po)
        r.check(f"vendor_token({po!r}) == {want!r}", got == want, f"got {got!r}")

    # ---- 2. the match --------------------------------------------------------------
    r.section("exact on the normalised name, or an alias; never a guess")
    vendors = [{"company_id": "fs-racking", "display_name": "FS Racking"},
               {"company_id": "j-and-l-wire", "display_name": "J and L Wire"},
               {"company_id": "savety-yellow", "display_name": "SaveTy Yellow"},
               {"company_id": "hallowell", "display_name": "Hallowell"}]
    for a, b, same in (("J&L Wire", "J and L Wire", False), ("Save-ty Yellow", "SaveTy Yellow", True),
                       ("FS", "fs", True), ("FS Racking", "FSRacking", True)):
        r.check(f"norm_token: {a!r} {'==' if same else '!='} {b!r}",
                (vm.norm_token(a) == vm.norm_token(b)) is same,
                f"{vm.norm_token(a)!r} vs {vm.norm_token(b)!r}")
    m = lambda tok, al=None: vm.match_vendor(tok, vendors, al or {})  # noqa: E731
    r.check("the normalised display name matches exactly", m("FS Racking") == ("fs-racking", "exact"), str(m("FS Racking")))
    r.check("case and punctuation do not matter", m("Save-ty Yellow") == ("savety-yellow", "exact"), str(m("Save-ty Yellow")))
    r.check("a prefix is NOT a match", m("FS") == (None, "unmatched"), str(m("FS")))
    r.check("nor is a longer name that contains a vendor's", m("FS Racking Inc") == (None, "unmatched"), str(m("FS Racking Inc")))
    r.check("a misspelling matches nothing", m("JnL") == (None, "unmatched"), str(m("JnL")))
    r.check("an alias the operator wrote matches", m("FS", {"fs": "fs-racking"}) == ("fs-racking", "alias"), str(m("FS", {"fs": "fs-racking"})))
    r.check("an alias naming no vendor record is reported, not used",
            m("FS", {"fs": "nobody"}) == (None, "alias_unknown"), str(m("FS", {"fs": "nobody"})))
    r.check("an exact name wins over an alias that disagrees",
            m("Hallowell", {"hallowell": "fs-racking"}) == ("hallowell", "exact"))
    r.check("no token is no match", m(None) == (None, "no_token") and m("") == (None, "no_token"))
    twins = vendors + [{"company_id": "hallowell-2", "display_name": "Hallowell"}]
    r.check("a name two vendor records collapse onto is ambiguous, and picks neither",
            vm.match_vendor("Hallowell", twins, {}) == (None, "ambiguous"),
            str(vm.match_vendor("Hallowell", twins, {})))
    tmp = Path(tempfile.mkdtemp(prefix="crmvend-"))
    (tmp / "vendor_aliases.json").write_text(json.dumps({"FS": "fs-racking", " J n L ": "j-and-l-wire", "": "x", "bad": 5}))
    al = vm.load_aliases(str(tmp))
    r.check("aliases are normalised on load, and junk entries are dropped",
            al == {"fs": "fs-racking", "jnl": "j-and-l-wire"}, str(al))
    r.check("no aliases file means no aliases", vm.load_aliases(str(tmp / "nope")) == {})
    (tmp / "vendor_aliases.json").write_text("[1,2]")
    r.check("an aliases file that is not an object means no aliases", vm.load_aliases(str(tmp)) == {})

    # ---- 3. the report ---------------------------------------------------------------
    r.section("report mode lists every leg without a vendor, and writes nothing")
    store = tmp / "store"
    store.mkdir()
    w = lambda n, v: (store / n).write_text(json.dumps(v, indent=2))  # noqa: E731
    w("vendors.json", vendors)
    w("vendor_aliases.json", {"fs": "fs-racking"})
    w("shipments.json", [
        {"shipment_id": "4521-L1", "vendor_po_raw": "PO # 1 (FS)", "vendor_id": None},
        {"shipment_id": "4521-L2", "vendor_po_raw": "PO # 2 (FS Racking) (PAID)", "vendor_id": None},
        {"shipment_id": "4521-L3", "vendor_po_raw": "PO # 3 (JnL)"},
        {"shipment_id": "4521-L4", "vendor_po_raw": "PO # 4 (JnL) (70% Paid)"},
        {"shipment_id": "4521-L5", "vendor_po_raw": "PO # 5 (Welter)"},
        {"shipment_id": "4521-L6", "vendor_po_raw": "PO # 6", "vendor_id": None},
        {"shipment_id": "4521-L7", "vendor_po_raw": "PO # 7 (FS)", "vendor_id": "penco"},
        {"shipment_id": "4521-L8", "vendor_po_raw": "PO # 8 (Hallowell)"}])
    # hallowell's company is archived: its name matches, and it must not be written
    w("companies.json", [{"company_id": "hallowell", "display_name": "Hallowell", "role": "vendor", "archived": True}])
    w("projects.json", []); w("invoices.json", [])
    before = {p.name: p.read_bytes() for p in store.iterdir()}
    script = crm / "pipeline" / "backfill_leg_vendors.py"
    if not r.check("pipeline/backfill_leg_vendors.py exists", script.exists()):
        return r
    proc = subprocess.run([sys.executable, str(script), "--store", str(store)],
                          capture_output=True, text=True)
    out = proc.stdout
    r.check("the script runs in report mode by default", proc.returncode == 0, proc.stderr[-300:])
    r.check("an aliased leg is reported with its vendor", "4521-L1" in out and "fs-racking  [alias]" in out, out[:400])
    r.check("an exact leg is reported with its vendor", "4521-L2" in out and "fs-racking  [exact]" in out, out[:400])
    r.check("an unmatched leg is reported UNMATCHED, and a payment note beside it does not change that",
            "4521-L3" in out and "4521-L4" in out and out.count("UNMATCHED") >= 3, out[:600])
    r.check("a leg with no parenthetical is reported as having no token", "4521-L6" in out and "NO TOKEN" in out)
    r.check("a leg that already carries a vendor_id is not listed", "4521-L7" not in out and "penco" not in out)
    r.check("a name that matches an ARCHIVED vendor is reported, not planned",
            "4521-L8" in out and "VENDOR IS ARCHIVED" in out, out[:800])
    r.check("the unmatched tokens are tabled by count, most first",
            out.find("   2  JnL") > 0 and out.find("   1  Welter") > out.find("   2  JnL"), out[out.find("UNMATCHED TOKENS"):][:300])
    r.check("the before/after counts say what a write would do",
            "Would set vendor_id on 2 leg(s) (1 exact, 1 by alias)" in out and "1 of 8 now -> 3 of 8" in out,
            out[-400:])
    after = {p.name: p.read_bytes() for p in store.iterdir()}
    r.check("nothing was written", after == before and "nothing was written" in out.lower())

    # ---- 4. --apply ------------------------------------------------------------------
    r.section("--apply writes exactly the exact and aliased matches, once, with a changelog")
    proc = subprocess.run([sys.executable, str(script), "--store", str(store), "--apply"],
                          capture_output=True, text=True)
    r.check("--apply runs", proc.returncode == 0, proc.stderr[-300:])
    # tolerant reads throughout: a script that wrote the wrong thing, or no
    # changelog at all, must read as red checks, not a crash the runner
    # cannot score
    def read_legs():
        try:
            data = json.loads((store / "shipments.json").read_text())
        except (OSError, ValueError):
            return {}
        return {str((s or {}).get("shipment_id")): s for s in data if isinstance(s, dict)}
    def read_log():
        p = store / "changelog.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    legs = read_legs()
    L = lambda k: legs.get(k) or {}  # noqa: E731
    r.check("the aliased and the exact leg now carry the vendor",
            L("4521-L1").get("vendor_id") == "fs-racking" and L("4521-L2").get("vendor_id") == "fs-racking",
            json.dumps({k: (v or {}).get("vendor_id") for k, v in legs.items()}))
    r.check("the unmatched legs, the no-token leg and the archived-vendor leg are untouched",
            all(L(k).get("vendor_id") is None for k in ("4521-L3", "4521-L4", "4521-L5", "4521-L6", "4521-L8"))
            and all(k in legs for k in ("4521-L3", "4521-L4", "4521-L5", "4521-L6", "4521-L8")),
            json.dumps({k: (v or {}).get("vendor_id") for k, v in legs.items()}))
    r.check("a vendor already on a leg is never overwritten", L("4521-L7").get("vendor_id") == "penco")
    log = read_log()
    r.check("one changelog entry per leg written, in Store.log's shape, so a re-import preserves it",
            len(log) == 2 and all(e["op"] == "update" and e["entity"] == "shipment"
                                  and e["fields"] == {"vendor_id": "fs-racking"} for e in log)
            and sorted(e["key"] for e in log) == ["4521-L1", "4521-L2"], json.dumps(log)[:300])
    r.check("and it says what it did", "APPLIED: vendor_id set on 2 leg(s); 1 of 8 -> 3 of 8" in proc.stdout, proc.stdout[-300:])
    snap = (store / "shipments.json").read_bytes()
    proc = subprocess.run([sys.executable, str(script), "--store", str(store), "--apply"],
                          capture_output=True, text=True)
    log2 = read_log()
    r.check("run twice, the second run writes nothing and logs nothing",
            proc.returncode == 0 and "APPLIED: vendor_id set on 0 leg(s)" in proc.stdout
            and (store / "shipments.json").read_bytes() == snap and len(log2) == 2, proc.stdout[-200:])

    # ---- 5. the importer, by the same rule ----------------------------------------------
    r.section("the importer files a new leg under the vendor its PO names, and reviews the rest")
    lt = _load_test("test_livetracker")
    nrm = lt._load(crm, "normalize.py") if lt else None
    if r.check("the Live fixture builder and normalize are loadable", bool(lt and nrm)):
        import openpyxl
        xl = tmp / "vendors.xlsx"
        lt._build_workbook(xl)
        wb = openpyxl.load_workbook(xl)
        vc = wb["Vendor Contacts"]
        vc.append(["FS Racking", "Dayton OH", "A Rep", None, None, "Racking", None, None])
        pt = wb["Project Tracker"]
        # row 4 of the fixture (key 5003) carries five legs in G/H, I/J, K/L ...;
        # three of its POs are rewritten to the three cases
        target = next(row for row in pt.iter_rows(min_row=2) if str(row[0].value) == "5003")
        target[6].value = "PO 1 (FS Racking)"       # exact
        target[8].value = "PO 2 (FS)"               # alias
        target[10].value = "PO 3 (Nobody) (PAID)"   # unmatched, payment note skipped
        wb.save(xl)
        out = tmp / "store-vendors"
        out.mkdir()
        (out / "vendor_aliases.json").write_text(json.dumps({"FS": "fs-racking"}))
        added = str(crm / "pipeline")
        sys.path.insert(0, added)
        err = None
        try:
            nrm.run(str(xl), str(out), force=False, mode="merge")
        except Exception as exc:                                   # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        finally:
            sys.path.remove(added)
        r.check("the import runs", err is None, err or "")
        legs = json.loads((out / "shipments.json").read_text()) if (out / "shipments.json").exists() else []
        by_po = {str(s.get("vendor_po_raw")): s for s in legs}
        r.check("a PO naming a vendor exactly files the leg under it",
                by_po.get("PO 1 (FS Racking)", {}).get("vendor_id") == "fs-racking", json.dumps(by_po.get("PO 1 (FS Racking)"))[:200])
        r.check("a PO naming an alias files the leg under the aliased vendor",
                by_po.get("PO 2 (FS)", {}).get("vendor_id") == "fs-racking", json.dumps(by_po.get("PO 2 (FS)"))[:200])
        r.check("a PO naming nobody leaves the leg with no vendor",
                "PO 3 (Nobody) (PAID)" in by_po and by_po["PO 3 (Nobody) (PAID)"].get("vendor_id") is None,
                json.dumps(by_po.get("PO 3 (Nobody) (PAID)"))[:200])
        review = json.loads((out / "needs_review.json").read_text()) if (out / "needs_review.json").exists() else []
        ent = [x for x in review if x.get("type") == "vendor_token_unmatched"]
        r.check("and goes to needs_review as vendor_token_unmatched with the token and the leg",
                len(ent) == 1 and ent[0].get("token") == "Nobody"
                and ent[0].get("shipment_id") == by_po["PO 3 (Nobody) (PAID)"].get("shipment_id"),
                json.dumps(ent)[:300])
        r.check("a matched token raises no review entry", not any(x.get("token") in ("FS", "FS Racking") for x in ent))

    # ---- 6. the server ----------------------------------------------------------------
    r.section("the server: legs by vendor, a vendor's open POs, and no vendor that is not one")
    srv = server
    if srv is None:
        from lib.harness import load_server
        srv = load_server(str(crm))
    s = Store(srv)
    s.reset(companies=[company("acme", "Ace Manufacturing"),
                       company("fs-racking", "FS Racking", role="vendor"),
                       company("penco", "Penco", role="vendor", archived=True)],
            vendors=[{"company_id": "fs-racking", "display_name": "FS Racking"},
                     {"company_id": "penco", "display_name": "Penco"}],
            projects=[{"project_no": "4521", "company_id": "acme", "status": "won", "archived": False}],
            shipments=[shipment("4521-L1", "4521", "acme", vendor_id="fs-racking", stage="Ordered"),
                       shipment("4521-L2", "4521", "acme", vendor_id="fs-racking", stage="Delivered"),
                       shipment("4521-L3", "4521", "acme", vendor_id=None, stage="Ordered")])
    res = s.call("list_shipments", vendor_id="fs-racking")
    r.check("list_shipments(vendor_id=) keeps the legs filed under that vendor",
            res.get("ok") and sorted(x["shipment_id"] for x in res["shipments"]) == ["4521-L1", "4521-L2"], json.dumps(res)[:200])
    res = s.call("get_vendor", ref="fs-racking")
    r.check("get_vendor returns the vendor's OPEN legs -- not the delivered one",
            res.get("ok") and [x["shipment_id"] for x in res.get("open_legs", [])] == ["4521-L1"], json.dumps(res.get("open_legs"))[:200])
    res = s.call("get_vendor", ref="FS Racking")
    r.check("by name too", res.get("ok") and [x["shipment_id"] for x in res.get("open_legs", [])] == ["4521-L1"])
    before = json.dumps(s.read("shipments"), sort_keys=True)
    res = s.call("update_shipment", shipment_id="4521-L3", fields={"vendor_id": "nobody"})
    r.check("update_shipment refuses a vendor_id that names no vendor record",
            res.get("ok") is False and "no vendor record" in str(res.get("error")), json.dumps(res)[:200])
    res = s.call("update_shipment", shipment_id="4521-L3", fields={"vendor_id": "penco"})
    r.check("and one whose company is archived",
            res.get("ok") is False and "archived" in str(res.get("error")), json.dumps(res)[:200])
    r.check("nothing changed on either refusal", json.dumps(s.read("shipments"), sort_keys=True) == before)
    res = s.call("update_shipment", shipment_id="4521-L3", fields={"vendor_id": "fs-racking"})
    r.check("a real vendor is accepted", res.get("ok") and res["shipment"]["vendor_id"] == "fs-racking", json.dumps(res)[:200])
    res = s.call("update_shipment", shipment_id="4521-L3", fields={"vendor_id": None})
    r.check("and null clears it", res.get("ok") and res["shipment"]["vendor_id"] is None, json.dumps(res)[:200])
    res = s.call("create_shipment", project_no="4521", fields={"vendor_po_raw": "X", "vendor_id": "nobody"}, company_id="acme")
    r.check("create_shipment refuses an unknown vendor too",
            res.get("ok") is False and "no vendor record" in str(res.get("error")) and len(s.read("shipments")) == 3,
            json.dumps(res)[:200])
    # vendor_on_time: legs without a vendor are excluded as no_vendor_on_leg;
    # once they carry one, that exclusion goes and the population is unchanged
    s.write("shipments", [shipment("4521-L1", "4521", "acme", stage="Delivered", eta="2026-02-01", ship_date="2026-02-01"),
                          shipment("4521-L2", "4521", "acme", stage="Delivered", eta="2026-02-01", ship_date="2026-02-03")])
    def vot():
        res = s.call("crm_metrics", report="vendor_on_time")
        rep = (res.get("reports") or {}).get("vendor_on_time") or res.get("vendor_on_time") or {}
        return res, rep
    res, rep = vot()
    r.check("vendor_on_time excludes vendor-less legs as no_vendor_on_leg",
            res.get("ok") and rep.get("population") == 2 and (rep.get("excluded") or {}).get("no_vendor_on_leg") == 2
            and rep.get("counted") == 0, json.dumps(rep)[:300])
    for sid in ("4521-L1", "4521-L2"):
        s.call("update_shipment", shipment_id=sid, fields={"vendor_id": "fs-racking"})
    res, rep = vot()
    r.check("once the legs carry a vendor, counted moves and the population does not",
            res.get("ok") and rep.get("population") == 2 and rep.get("counted") == 2
            and not (rep.get("excluded") or {}).get("no_vendor_on_leg"), json.dumps(rep)[:300])
    return r


def _load_test(name):
    """Another regression module, for its fixture builders."""
    import importlib.util
    p = Path(__file__).resolve().parent / f"{name}.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_{name}_fixtures", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

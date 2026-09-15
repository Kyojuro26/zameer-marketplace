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
from lib.harness import Result  # noqa: E402


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
        {"shipment_id": "4521-L7", "vendor_po_raw": "PO # 7 (Hallowell)", "vendor_id": "penco"}])
    w("companies.json", []); w("projects.json", []); w("invoices.json", [])
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
    r.check("the unmatched tokens are tabled by count, most first",
            out.find("   2  JnL") > 0 and out.find("   1  Welter") > out.find("   2  JnL"), out[out.find("UNMATCHED TOKENS"):][:300])
    r.check("the before/after counts say what a write would do",
            "Would set vendor_id on 2 leg(s) (1 exact, 1 by alias)" in out and "1 of 7 now -> 3 of 7" in out,
            out[-400:])
    after = {p.name: p.read_bytes() for p in store.iterdir()}
    r.check("nothing was written", after == before and "nothing was written" in out.lower())
    return r

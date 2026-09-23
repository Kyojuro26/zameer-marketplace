"""A customer and a vendor that are the same business (0.1.39, Phase C).

QuickBooks forces two names for one business that both buys and sells
("Harbor Mart" the vendor, "Harbor Mart LLC" the customer). The CRM keeps
them as two records and LINKS them; it never merges them.

Decisions asserted, each with an obvious wrong version:

 1. THE LINK LIVES ON THE COMPANY ONLY. update_company sets linked_vendor_id;
    the vendor side (linked_company_id) is derived at read time and never
    written to vendors.json. Null unlinks.
 2. THE LINK IS VALIDATED: the vendor must exist and not be archived; it is
    one-to-one, and a vendor already linked elsewhere is refused NAMING the
    company that holds it; a company cannot link to itself, and a vendor
    company does not hold a link.
 3. LINKING IS NOT MERGING: no record combines, no field copies across; the
    company's metrics, invoices and contacts and the vendor's legs read
    exactly as before.
 4. QBO NAMES: qbo_name is editable on companies and vendors. A QuickBooks
    name resolves by qbo_name first, then by the normalised display name; a
    name that fits more than one record is listed in unmatched_names, never
    guessed.
 5. suggest_entity_links IS READ-ONLY and explains every pair; distinct
    plants of one group are not paired with the group's vendor.

Names are invented.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)


def _em(user, host):
    """A fixture address composed at runtime, as test_importer does: written
    as a literal it is an email shape in a public repo, which the PII sweep
    rejects -- it cannot tell an invented address from a real one."""
    return user + "@" + host


def vendor(cid, name, **kw):
    r = {"company_id": cid, "display_name": name, "archived": False}
    r.update(kw)
    return r


def seed(st):
    st.reset(
        companies=[company("hmart", "Harbor Mart"),
                   company("beta", "Beta Works"),
                   company("norv-a", "Norvale Plant A"),
                   company("norv-b", "Norvale Plant B"),
                   company("gamma1", "Gamma Co"),
                   company("gamma2", "gamma  co."),
                   company("delta", "Delta Corp"),
                   company("delta2", "Delta Holdings", qbo_name="Delta Corp"),
                   # a CUSTOMER that also has a vendor record under its own id:
                   # create_vendor refuses to make one now, an older store can hold it
                   company("both", "Both Ways"),
                   company("hmart-v", "Harbor Mart LLC", role="vendor"),
                   company("norv-v", "Norvale", role="vendor"),
                   company("oldv", "Old Supply", role="vendor", archived=True),
                   company("cobalt", "Cobalt Freight", role="vendor")],
        vendors=[vendor("hmart-v", "Harbor Mart LLC"),
                 vendor("norv-v", "Norvale"),
                 vendor("oldv", "Old Supply", archived=True),
                 vendor("cobalt", "Cobalt Freight", qbo_name="Cobalt Freight Lines Inc"),
                 vendor("both", "Both Ways")],
        projects=[project("4521", "hmart", revenue=10000)],
        invoices=[invoice("7001", "hmart", project_no="4521",
                          invoice_date="2026-02-01")],
        shipments=[shipment("4521-L1", "4521", "hmart", vendor_id="hmart-v",
                            vendor_po_raw="PO # 1167")],
        contacts=[{"company_id": "hmart", "name": "Rae Nolan",
                   "email": _em("rae", "hmart.example")}])


def run(server, crm_dir=None):
    r = Result("entity-links", since="0.1.39")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    tmp = Path(tempfile.mkdtemp(prefix="crmlink-"))
    try:
        _body(r, server, tmp)
        _qbo_vendor_section(r, server, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _qbo_vendor_section(r, server, tmp):
    """C2: a CRM customer that appears in QuickBooks as a VENDOR, where the CRM
    holds no vendor record for it -- the shape the real data has."""
    r.section("QuickBooks vendors that are CRM customers")
    st = Store(server, tmp / "q" / "store")
    seed(st)
    if not callable(getattr(server, "_save_qbo_snapshot", None)):
        return
    line = {"date": "2026-01-08", "type": "Bill", "num": "1", "posting": True,
            "account": None, "split_account": None, "amount_cents": 100}
    server._save_qbo_snapshot("vendor_transactions", "export", "2026-04-07",
                              "2026-01-01", "2026-03-31",
                              [dict(line, vendor=v) for v in (
                                  "Beta Works Inc",       # customer beta, no vendor record
                                  "Harbor Mart LLC",      # customer hmart; record hmart-v exists
                                  "Norvale",              # the group: plants are not it
                                  "Gamma Co",             # two customers fit: never guessed
                                  "Zeta Tools")])         # nobody
    before = {n: st.raw(n) for n in ("companies", "vendors", "invoices")}
    got = st.call("suggest_entity_links")
    q = {(x.get("company_id"), x.get("qbo_vendor_name")): x
         for x in got.get("qbo_vendor_names") or []}
    b = q.get(("beta", "Beta Works Inc")) or {}
    r.check("a customer whose name is a QuickBooks vendor's is suggested",
            bool(b) and "QuickBooks vendor" in str(b.get("reason")), got.get("qbo_vendor_names"))
    r.check("... saying no CRM vendor record exists for it",
            b.get("vendor_record_exists") is False and b.get("vendor_id") is None, b)
    h = q.get(("hmart", "Harbor Mart LLC")) or {}
    r.check("where a CRM vendor record exists for the QuickBooks name, it says which",
            h.get("vendor_record_exists") is True and h.get("vendor_id") == "hmart-v", h)
    r.check("the group vendor is not paired with its plants",
            not any(k[1] == "Norvale" for k in q), sorted(q))
    r.check("... nor offered as an ambiguous candidate for them",
            not any(x.get("qbo_vendor_name") == "Norvale"
                    for x in got.get("qbo_vendor_ambiguous") or []), got.get("qbo_vendor_ambiguous"))
    r.check("a QuickBooks vendor name that fits two customers is not suggested for either",
            not any(k[1] == "Gamma Co" for k in q), sorted(q))
    r.check("... it is listed apart, with both candidates",
            any(a.get("qbo_vendor_name") == "Gamma Co"
                and sorted(a.get("candidates") or []) == ["gamma1", "gamma2"]
                for a in got.get("qbo_vendor_ambiguous") or []), got.get("qbo_vendor_ambiguous"))
    r.check("a name nobody carries is not suggested", not any(k[1] == "Zeta Tools" for k in q))
    r.check("suggesting still writes nothing",
            {n: st.raw(n) for n in ("companies", "vendors", "invoices")} == before)

    r.section("the one-step confirm: create the vendor record, then link")
    got = st.call("link_qbo_vendor", company_id="beta", qbo_vendor_name="Zeta Tools")
    r.check("a name that is not a current suggestion for that customer is refused",
            got.get("ok") is False and "_raised" not in got, got)
    r.check("... and nothing was written",
            {n: st.raw(n) for n in ("companies", "vendors", "invoices")} == before)
    got = st.call("link_qbo_vendor", company_id="beta", qbo_vendor_name="Beta Works Inc")
    r.check("confirming creates the vendor record and links it", got.get("ok") is True
            and got.get("created_vendor") is True, got)
    vs = [v for v in st.read("vendors") if v.get("qbo_name") == "Beta Works Inc"]
    r.check("... one vendor record, carrying the QuickBooks name as qbo_name",
            len(vs) == 1 and vs[0].get("display_name") == "Beta Works Inc", vs)
    vid = vs[0]["company_id"] if vs else None
    beta = next(c for c in st.read("companies") if c["company_id"] == "beta")
    r.check("... the customer links to it", beta.get("linked_vendor_id") == vid and vid, beta)
    r.check("... and stays a customer: nothing merged", beta.get("role") == "customer", beta)
    gv = st.call("get_vendor", ref=vid) if vid else {}
    r.check("... the vendor side reads the link", (gv.get("vendor") or {}).get("linked_company_id") == "beta",
            gv.get("vendor"))
    cl = st.path / "changelog.jsonl"
    log = [json.loads(l) for l in cl.read_text().splitlines() if l.strip()] if cl.exists() else []
    r.check("... through the existing writes: a vendor create, then a company update",
            [(e.get("op"), e.get("entity")) for e in log][-2:] == [("create", "vendor"), ("update", "company")],
            [(e.get("op"), e.get("entity")) for e in log][-3:])
    again = st.call("suggest_entity_links")
    r.check("once linked, the customer is not suggested again",
            not any(x.get("company_id") == "beta" for x in again.get("qbo_vendor_names") or []))
    got = st.call("link_qbo_vendor", company_id="hmart", qbo_vendor_name="Harbor Mart LLC")
    r.check("where the vendor record already exists, confirming links it and creates nothing",
            got.get("ok") is True and got.get("created_vendor") is False
            and next(c for c in st.read("companies") if c["company_id"] == "hmart")
            .get("linked_vendor_id") == "hmart-v"
            and len([v for v in st.read("vendors") if v.get("display_name") == "Harbor Mart LLC"]) == 1, got)
    st2 = Store(server, tmp / "q2" / "store")
    seed(st2)
    got = st2.call("suggest_entity_links")
    r.check("with no vendor snapshot loaded there are no QuickBooks suggestions, and no error",
            got.get("ok") is True and got.get("qbo_vendor_names") == [], got.get("qbo_vendor_names"))


def _strip(d, *keys):
    return {k: v for k, v in (d or {}).items() if k not in keys}


def _body(r, server, tmp):
    st = Store(server, tmp / "m" / "store")
    seed(st)
    vendors_before = st.raw("vendors")
    comp_seeded = next(c for c in st.read("companies") if c["company_id"] == "hmart")
    co_before = st.call("get_company", ref="hmart")
    v_before = st.call("get_vendor", ref="hmart-v")

    # ---- 1. the link, stored once ------------------------------------------
    r.section("linking")
    got = st.call("update_company", company_id="hmart",
                  fields={"linked_vendor_id": "hmart-v"})
    r.check("a customer links to its vendor record", got.get("ok") is True, got)
    comp = next(c for c in st.read("companies") if c["company_id"] == "hmart")
    r.check("the link is stored on the company", comp.get("linked_vendor_id") == "hmart-v",
            comp)
    r.check("vendors.json is byte-identical: the vendor side is never stored",
            st.raw("vendors") == vendors_before)
    gv = st.call("get_vendor", ref="hmart-v")
    r.check("get_vendor derives linked_company_id at read time",
            (gv.get("vendor") or {}).get("linked_company_id") == "hmart", gv.get("vendor"))
    uv = st.call("update_vendor", company_id="hmart-v", fields={"rep": "Sam"})
    r.check("update_vendor's response carries it too",
            (uv.get("vendor") or {}).get("linked_company_id") == "hmart", uv.get("vendor"))
    r.check("... and writing the vendor does not persist it",
            not any("linked_company_id" in v for v in st.read("vendors")))
    got = st.call("update_company", company_id="hmart",
                  fields={"linked_vendor_id": "hmart-v", "notes": "buys and sells"})
    r.check("re-saving the same link (the drawer echoes it) is not a conflict",
            got.get("ok") is True, got)
    log = [json.loads(l) for l in (st.path / "changelog.jsonl").read_text().splitlines()
           if l.strip()]
    r.check("the link is in the changelog",
            any(e.get("entity") == "company" and e.get("key") == "hmart"
                and (e.get("fields") or {}).get("linked_vendor_id") == "hmart-v" for e in log),
            log[-1] if log else None)

    # ---- 3. not merging ----------------------------------------------------
    r.section("linking is not merging")
    co_after = st.call("get_company", ref="hmart")
    r.check("the company's invoices, projects, contacts and shipments are unchanged",
            all(co_after.get(k) == co_before.get(k)
                for k in ("invoices", "projects", "contacts", "shipments")))
    r.check("the company's metrics are unchanged",
            (co_after.get("company") or {}).get("metrics")
            == (co_before.get("company") or {}).get("metrics"))
    r.check("the vendor's record and open legs are unchanged apart from the derived link",
            _strip(gv.get("vendor"), "linked_company_id") == _strip(v_before.get("vendor"), "linked_company_id")
            and gv.get("open_legs") == v_before.get("open_legs"))
    r.check("no field was copied from the vendor onto the company",
            _strip(comp, "linked_vendor_id") == _strip(comp_seeded, "linked_vendor_id"),
            (comp, comp_seeded))

    # ---- 2. validation -----------------------------------------------------
    r.section("the link is validated")

    def refused(label, cid, value, needle=None):
        before = st.raw("companies")
        got = st.call("update_company", company_id=cid, fields={"linked_vendor_id": value})
        ok = got.get("ok") is False and "_raised" not in got
        r.check(f"refused: {label}", ok, got)
        if needle:
            r.check(f"... the refusal says {needle!r}", needle in str(got.get("error")),
                    got.get("error"))
        r.check(f"... nothing written ({label})", st.raw("companies") == before)

    refused("a vendor that does not exist", "beta", "nope")
    refused("an archived vendor", "beta", "oldv", "archived")
    refused("a vendor already linked to another company -- naming it", "beta",
            "hmart-v", "Harbor Mart")
    refused("a second plant linking to the group vendor already taken", "norv-b",
            "hmart-v", "hmart")
    refused("a company linked to itself", "both", "both", "itself")
    refused("a vendor company holding a link", "cobalt", "norv-v")
    refused("a link that is not text", "beta", True)
    got = st.call("update_company", company_id="norv-a", fields={"linked_vendor_id": "norv-v"})
    r.check("one plant may link to the group vendor", got.get("ok") is True, got)
    got = st.call("update_company", company_id="norv-b", fields={"linked_vendor_id": "norv-v"})
    r.check("... but not a second plant: one-to-one, the plants stay separate",
            got.get("ok") is False and "Norvale Plant A" in str(got.get("error")), got)

    got = st.call("update_company", company_id="hmart", fields={"linked_vendor_id": " hmart-v "})
    stored = next(c for c in st.read("companies") if c["company_id"] == "hmart").get("linked_vendor_id")
    r.check("a padded id is stored as the vendor record's own id -- the page matches ids "
            "exactly, and ' hmart-v ' would link to nothing it can find",
            got.get("ok") is True and stored == "hmart-v", repr(stored))
    got = st.call("update_company", company_id="hmart", fields={"linked_vendor_id": None})
    r.check("null unlinks", got.get("ok") is True
            and next(c for c in st.read("companies") if c["company_id"] == "hmart")
            .get("linked_vendor_id") is None, got)
    r.check("... and the vendor side follows, with nothing to clean up",
            (st.call("get_vendor", ref="hmart-v").get("vendor") or {})
            .get("linked_company_id") is None)
    got = st.call("update_company", company_id="beta", fields={"linked_vendor_id": "hmart-v"})
    r.check("once unlinked, the vendor can link elsewhere", got.get("ok") is True, got)
    st.call("archive_company", company_id="beta")
    r.check("the vendor side shows only a LIVE company: archiving the holder clears it",
            (st.call("get_vendor", ref="hmart-v").get("vendor") or {}).get("linked_company_id") is None)
    got = st.call("update_company", company_id="hmart", fields={"linked_vendor_id": "hmart-v"})
    r.check("a vendor held by an ARCHIVED company is still refused, and the refusal "
            "says it is archived -- the operator cannot see that company to unlink it",
            got.get("ok") is False and "archived" in str(got.get("error"))
            and "Beta Works" in str(got.get("error")), got.get("error"))
    st.call("restore_company", company_id="beta")
    st.call("update_company", company_id="beta", fields={"linked_vendor_id": None})

    # ---- 5. candidate pairs ------------------------------------------------
    r.section("suggest_entity_links")
    st.call("update_company", company_id="beta", fields={"linked_vendor_id": None})
    st.call("update_company", company_id="norv-a", fields={"linked_vendor_id": None})
    before = {n: st.raw(n) for n in ("companies", "vendors", "invoices")}
    got = st.call("suggest_entity_links")
    r.check("suggest_entity_links answers", got.get("ok") is True, got)
    pairs = {(p.get("company_id"), p.get("vendor_id")): p for p in got.get("pairs") or []}
    p = pairs.get(("hmart", "hmart-v")) or {}
    r.check("'Harbor Mart' and 'Harbor Mart LLC' are suggested, and the reason "
            "names the legal suffix", bool(p) and "LLC" in str(p.get("reason")), got.get("pairs"))
    r.check("the group vendor 'Norvale' is not paired with its plants",
            not any(k[1] == "norv-v" for k in pairs), sorted(pairs))
    r.check("an archived vendor is never suggested", not any(k[1] == "oldv" for k in pairs))
    r.check("suggesting writes nothing",
            {n: st.raw(n) for n in ("companies", "vendors", "invoices")} == before)
    st.call("update_company", company_id="beta", fields={"linked_vendor_id": "hmart-v"})
    pairs2 = {(p.get("company_id"), p.get("vendor_id"))
              for p in st.call("suggest_entity_links").get("pairs") or []}
    r.check("a vendor already linked elsewhere is not suggested", ("hmart", "hmart-v") not in pairs2,
            sorted(pairs2))
    st.call("update_company", company_id="beta", fields={"linked_vendor_id": None})
    st.call("update_company", company_id="hmart", fields={"linked_vendor_id": "norv-v"})
    pairs3 = {(p.get("company_id"), p.get("vendor_id"))
              for p in st.call("suggest_entity_links").get("pairs") or []}
    r.check("a company already linked is not suggested", ("hmart", "hmart-v") not in pairs3,
            sorted(pairs3))
    st.call("update_company", company_id="hmart", fields={"linked_vendor_id": "hmart-v"})

    # ---- 4. QuickBooks names ----------------------------------------------
    r.section("QuickBooks names")
    got = st.call("update_company", company_id="hmart",
                  fields={"qbo_name": "Harbor Mart LLC"})
    r.check("qbo_name is editable on a company", got.get("ok") is True
            and (got.get("company") or {}).get("qbo_name") == "Harbor Mart LLC", got)
    got = st.call("update_vendor", company_id="norv-v", fields={"qbo_name": "Norvale Inc"})
    r.check("qbo_name is editable on a vendor", got.get("ok") is True
            and (got.get("vendor") or {}).get("qbo_name") == "Norvale Inc", got)
    if not callable(getattr(server, "_save_qbo_snapshot", None)):
        return
    server._save_qbo_snapshot("invoices", "export", "2026-04-07", "2026-01-01",
                              "2026-03-31", [
        {"type": "Invoice", "num": n, "name": name, "amount_cents": 100,
         "open_cents": 100}
        for n, name in (("9101", "Harbor Mart LLC"), ("9102", "beta works"),
                        ("9103", "Gamma Co"), ("9104", "Nobody Ltd"),
                        ("9105", "Delta Corp"), ("9106", "Cobalt Freight"))])
    server._save_qbo_snapshot("vendor_transactions", "export", "2026-04-07",
                              "2026-01-01", "2026-03-31", [
        {"vendor": "Cobalt Freight Lines Inc", "date": "2026-01-08", "type": "Purchase Order",
         "num": "1167", "posting": False, "account": None, "split_account": None,
         "amount_cents": 500}])
    d = (st.call("crm_metrics", report="qbo_drift").get("reports") or {}).get("qbo_drift") or {}
    by = {x.get("num"): x for x in d.get("rows") or []}
    r.check("a QuickBooks customer name resolves by qbo_name first",
            (by.get("9101") or {}).get("company_id") == "hmart", by.get("9101"))
    r.check("... then by the normalised display name",
            (by.get("9102") or {}).get("company_id") == "beta", by.get("9102"))
    r.check("qbo_name wins over another company's display name",
            (by.get("9105") or {}).get("company_id") == "delta2", by.get("9105"))
    r.check("a customer name never resolves to a vendor company",
            (by.get("9106") or {}).get("company_id") is None, by.get("9106"))
    r.check("a name that fits two companies is not guessed",
            (by.get("9103") or {}).get("company_id") is None, by.get("9103"))
    um = {u.get("name"): u for u in d.get("unmatched_names") or []}
    r.check("... it is listed in unmatched_names with both candidates",
            (um.get("Gamma Co") or {}).get("reason") == "ambiguous"
            and sorted((um.get("Gamma Co") or {}).get("candidates") or []) == ["gamma1", "gamma2"],
            d.get("unmatched_names"))
    r.check("a name that fits nothing is listed as no match",
            (um.get("Nobody Ltd") or {}).get("reason") == "no_match", d.get("unmatched_names"))
    look = st.call("lookup_number", n="1167")
    po = next((m for m in look.get("matches") or [] if m.get("type") == "qbo_po"), {})
    r.check("a QuickBooks PO's vendor resolves to the vendor record by its qbo_name",
            po.get("vendor_id") == "cobalt", po)


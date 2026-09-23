"""The QuickBooks snapshot tools (0.1.38, B2), through the real MCP dispatch.

    load_qbo_export(path)                          an exported .xlsx -> snapshot
    load_qbo_rows(kind, rows, as_of, window_start, window_end)
                                                   the connector path
    qbo_snapshot_info()                            what is loaded, and how old

Decisions asserted, each with an obvious wrong version:

 1. LOADING IS NOT A STORE WRITE. Every store file, the changelog included, is
    byte-identical after a load; the snapshot lands beside the store.
 2. THE EXPORT IS DETECTED BY ITS HEADER, not its file name, and a file that
    is neither export is refused with the header it carries.
 3. CONNECTOR ROWS ARE VALIDATED STRICTLY: unknown fields refused, cents must
    be ints (never a float, never a bool), (type, number) unique for invoices
    through _key, dates ISO, the connector-only fields only where they mean
    something. A refusal leaves the snapshot on disk untouched.
 4. NOTHING HERE TOUCHES THE NETWORK. socket.socket is made to raise, and
    every snapshot load and every metric read must still succeed. This
    executes the rule instead of grepping for it.
"""
import datetime
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness import (Result, Store, company, invoice, load_server,  # noqa: E402
                         project, shipment)
import test_qbo_snapshots as T  # noqa: E402  -- the layout fixtures


def _files(root):
    return {p.name: p.read_bytes() for p in Path(root).iterdir() if p.is_file()}


def run(server, crm_dir=None):
    r = Result("qbo-tools", since="0.1.38")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    if server is None:
        server = load_server(crm)
    for tool in ("load_qbo_export", "load_qbo_rows", "qbo_snapshot_info"):
        if not r.check(f"tool {tool} exists", callable(getattr(server, tool, None)),
                       "not defined in server.py"):
            return r
    tmp = Path(tempfile.mkdtemp(prefix="qbotools-"))
    real_today = server._today
    server._today = lambda: datetime.date(2026, 4, 20)
    try:
        _body(r, server, tmp)
    finally:
        server._today = real_today
        shutil.rmtree(tmp, ignore_errors=True)
    return r


def _body(r, server, tmp):
    st = Store(server, tmp / "m" / "store")
    st.reset(companies=[company("acme", "Ace Manufacturing")],
             projects=[project("4521", "acme", revenue=10000)],
             invoices=[invoice("7001", "acme", project_no="4521",
                               invoice_date="2026-01-05")])
    snap = st.path.parent / "qbo-snapshots"

    inv = T._xlsx(tmp / "inv.xlsx", T._titled(
        "Invoice List by Date", "January 1-March 31, 2026", T.INV_HEADER,
        T.INV_BODY + [T.INV_TOTAL]))
    txn = T._xlsx(tmp / "txn.xlsx", T._titled(
        "Transaction List by Vendor", "January 1-March 31, 2026", T.TXN_HEADER,
        T.TXN_BODY))

    # ---- 1-2. load_qbo_export ------------------------------------------------
    r.section("load_qbo_export")
    before = _files(st.path)
    got = st.call("load_qbo_export", path=str(inv))
    r.check("an invoice list loads", got.get("ok") is True, got)
    r.check("it is detected as invoices", got.get("kind") == "invoices", got)
    r.check("it returns counts, the window and as_of",
            got.get("rows") == 3 and got.get("window_start") == "2026-01-01"
            and got.get("window_end") == "2026-03-31"
            and got.get("as_of") == "2026-04-07T09:15:00-04:00", got)
    r.check("the snapshot is beside the store",
            (snap / "invoices.json").exists(), sorted(os.listdir(st.path.parent)))
    r.check("no store file changed -- not even the changelog",
            _files(st.path) == before,
            sorted(set(_files(st.path)) ^ set(before)) or "a file's bytes changed")
    doc = json.loads((snap / "invoices.json").read_text())
    r.check("its source is export", doc.get("source") == "export", doc.get("source"))

    got = st.call("load_qbo_export", path=str(txn))
    r.check("a vendor transaction list is detected by its header",
            got.get("ok") is True and got.get("kind") == "vendor_transactions", got)
    r.check("... with counts by transaction type",
            got.get("by_type") == {"Purchase Order": 1, "Bill": 1,
                                   "Bill Payment (Check)": 1, "Expense": 1,
                                   "Journal Entry": 1}, got.get("by_type"))
    r.check("the invoice snapshot is still there, untouched by the other kind",
            json.loads((snap / "invoices.json").read_text()).get("rows")
            == doc.get("rows"))

    prior = (snap / "invoices.json").read_bytes()
    bad = T._xlsx(tmp / "bad.xlsx", T._titled(
        "Invoice List by Date", "January 1-March 31, 2026",
        T.INV_HEADER[:7] + ["Balance"], T.INV_BODY))
    got = st.call("load_qbo_export", path=str(bad))
    r.check("neither export -> refused, not raised", got.get("ok") is False
            and "_raised" not in got, got)
    r.check("... returning the header it found",
            got.get("found_header") == T.INV_HEADER[:7] + ["Balance"], got)
    r.check("... and the snapshot on disk is untouched",
            (snap / "invoices.json").read_bytes() == prior)
    got = st.call("load_qbo_export", path=str(tmp / "missing.xlsx"))
    r.check("a path that does not exist -> refused in a sentence",
            got.get("ok") is False and "_raised" not in got, got)

    # ---- 3. load_qbo_rows ----------------------------------------------------
    r.section("load_qbo_rows: strict validation")
    good = [{"type": "Invoice", "num": "7001", "date": "2026-01-05",
             "due_date": "2026-02-04", "name": "Ace Manufacturing",
             "amount_cents": 1250000, "open_cents": 0},
            {"type": "Invoice", "num": "7002", "date": "2026-02-10",
             "due_date": None, "name": None, "amount_cents": 29,
             "open_cents": 29, "id": "118"}]
    W = dict(as_of="2026-04-18", window_start="2026-01-01",
             window_end="2026-04-18")
    got = st.call("load_qbo_rows", kind="invoices", rows=good, **W)
    r.check("valid connector rows load", got.get("ok") is True, got)
    doc = json.loads((snap / "invoices.json").read_text())
    r.check("... as source connector, replacing the export wholesale",
            doc.get("source") == "connector" and len(doc.get("rows") or []) == 2,
            (doc.get("source"), len(doc.get("rows") or [])))
    r.check("... with no store write", _files(st.path) == before)

    def refused(label, kind, rows, **kw):
        prior = {p.name: p.read_bytes() for p in snap.iterdir()}
        args = dict(W, **kw)
        got = st.call("load_qbo_rows", kind=kind, rows=rows, **args)
        ok = got.get("ok") is False and "_raised" not in got
        r.check(f"refused: {label}", ok, got)
        r.check(f"... snapshot untouched ({label})",
                {p.name: p.read_bytes() for p in snap.iterdir()} == prior)
        return got

    got = refused("an unknown field", "invoices",
                  [dict(good[0], customer_id="X")])
    r.check("... the refusal names the field",
            "customer_id" in str(got.get("error")), got.get("error"))
    refused("float cents", "invoices", [dict(good[0], amount_cents=12500.0)])
    refused("a string of cents", "invoices", [dict(good[0], amount_cents="1250000")])
    refused("a boolean in cents", "invoices", [dict(good[0], open_cents=False)])
    refused("a missing required field", "invoices",
            [{k: v for k, v in good[0].items() if k != "open_cents"}])
    got = refused("two invoices with one (type, number)", "invoices",
                  [good[0], dict(good[1], num=" 7001 ")])
    r.check("... the refusal names the number",
            "7001" in str(got.get("error")), got.get("error"))
    refused("a date that is not ISO", "invoices", [dict(good[0], date="1/5/2026")])
    refused("a window that ends before it starts", "invoices", good,
            window_start="2026-05-01", window_end="2026-04-01")
    refused("an as_of that is not a date", "invoices", good, as_of="last week")
    refused("an unknown kind", "payments", good)
    refused("rows that are not a list of objects", "invoices", ["7001"])

    vt = {"vendor": "Cobalt Freight", "date": "2026-01-20", "type": "Bill",
          "num": "INV-88", "posting": True, "account": "Accounts Payable",
          "split_account": None, "amount_cents": 420000}
    got = st.call("load_qbo_rows", kind="vendor_transactions",
                  rows=[dict(vt, linked_po="1167"),
                        dict(vt, type="Expense", num=None, customer_ref="acme"),
                        dict(vt, type="Purchase Order", num="1167",
                             posting=False, open_status="open"),
                        dict(vt, type="Bill", num="INV-88")], **W)
    r.check("the optional connector fields load where they mean something, "
            "and two bills may share a vendor's Num", got.get("ok") is True, got)
    refused("linked_po on something that is not a bill", "vendor_transactions",
            [dict(vt, type="Expense", linked_po="1167")])
    refused("customer_ref on something that is not an expense",
            "vendor_transactions", [dict(vt, customer_ref="acme")])
    refused("open_status on something that is not a PO", "vendor_transactions",
            [dict(vt, open_status="open")])
    refused("an open_status that is not open or closed", "vendor_transactions",
            [dict(vt, type="Purchase Order", open_status="maybe")])
    refused("posting that is not a boolean", "vendor_transactions",
            [dict(vt, posting="Yes")])

    cash = [{"account": "Operating Checking", "balance_cents": 5012345,
             "account_type": "Bank"},
            {"account": "Company Card", "balance_cents": -120000}]
    got = st.call("load_qbo_rows", kind="cash_balances", rows=cash, **W)
    r.check("cash balances load through the connector path", got.get("ok") is True, got)
    refused("two balances for one account", "cash_balances", [cash[0], cash[0]])

    # ---- qbo_snapshot_info ---------------------------------------------------
    r.section("qbo_snapshot_info")
    info = st.call("qbo_snapshot_info")
    k = (info.get("kinds") or {})
    r.check("it reports every kind", info.get("ok") is True
            and set(k) == {"invoices", "vendor_transactions", "cash_balances"}, info)
    r.check("rows, as_of and window per kind",
            (k.get("invoices") or {}).get("rows") == 2
            and (k.get("invoices") or {}).get("as_of") == "2026-04-18"
            and (k.get("invoices") or {}).get("window_end") == "2026-04-18",
            k.get("invoices"))
    r.check("age in days from as_of to today (frozen 2026-04-20): 2",
            (k.get("invoices") or {}).get("age_days") == 2, k.get("invoices"))
    st.call("load_qbo_rows", kind="cash_balances", rows=cash,
            as_of="2026-04-10", window_start="2026-01-01", window_end="2026-04-10")
    k = (st.call("qbo_snapshot_info").get("kinds") or {})
    r.check("more than 7 days old reads stale; 2 days does not",
            (k.get("cash_balances") or {}).get("stale") is True
            and (k.get("invoices") or {}).get("stale") is False,
            (k.get("cash_balances"), k.get("invoices")))
    (snap / "vendor_transactions.json").write_text("{ not json")
    info = st.call("qbo_snapshot_info")
    vk = (info.get("kinds") or {}).get("vendor_transactions") or {}
    r.check("a corrupt snapshot is reported in words, not raised",
            info.get("ok") is True and vk.get("loaded") is False
            and vk.get("error"), info)
    os.remove(snap / "vendor_transactions.json")
    k = (st.call("qbo_snapshot_info").get("kinds") or {})
    r.check("a kind never loaded says so",
            (k.get("vendor_transactions") or {}).get("loaded") is False, k)

    # ---- 4. no network ---------------------------------------------------
    r.section("no network: socket.socket raises during every load and read")
    # AF_UNIX stays: asyncio's event loop (the MCP dispatch itself) opens a
    # local socketpair for its self-pipe. Every INTERNET socket raises, as do
    # the two calls that reach one without constructing it here.
    real_socket, real_cc = socket.socket, socket.create_connection
    real_gai = socket.getaddrinfo
    touched = []

    class NoNet(real_socket):
        def __init__(self, family=-1, *a, **kw):
            if family in (-1, socket.AF_INET, socket.AF_INET6):
                touched.append("socket")
                raise OSError("network is forbidden in this test")
            super().__init__(family, *a, **kw)

    def no_net(name):
        def f(*a, **kw):
            touched.append(name)
            raise OSError("network is forbidden in this test")
        return f

    socket.socket, socket.create_connection = NoNet, no_net("create_connection")
    socket.getaddrinfo = no_net("getaddrinfo")
    try:
        calls = [
            ("load_qbo_export", dict(path=str(inv))),
            ("load_qbo_export", dict(path=str(txn))),
            ("load_qbo_rows", dict(kind="cash_balances", rows=cash, **W)),
            ("qbo_snapshot_info", {}),
            ("crm_metrics", {}),
            ("crm_metrics", dict(report="qbo_drift")),
            ("list_companies", {}),
            ("get_company", dict(ref="acme")),
            ("list_invoices", {}),
            ("lookup_number", dict(n="7001")),
        ]
        results = [(t, st.call(t, **a)) for t, a in calls]
    finally:
        socket.socket, socket.create_connection = real_socket, real_cc
        socket.getaddrinfo = real_gai
    for t, got in results:
        r.check(f"{t} succeeds with the network gone",
                got.get("ok") is True, str(got)[:200])
    r.check("... and nothing even tried to open a socket", not touched, touched)

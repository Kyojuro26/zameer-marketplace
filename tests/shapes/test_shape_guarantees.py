"""SHAPE 3 -- a stated guarantee that nothing enforces.

Comments and docstrings in this repo make load-bearing promises. Several were
false when checked:

  "DRAFTS ONLY -- nothing here can send mail"   (graph.py)
      a crafted message_id retargets /createReply to /reply, which sends.
  "Anything ambiguous is flagged in needs_review.json, never dropped"
      (normalize.py) -- four skip paths drop rows with no flag.
  "Every project_no / invoice_no comparison MUST go through this" (_key)
      -- nineteen sites used bare str().

Each promise below is turned into an executable assertion. If a guarantee is
softened or removed, delete its test here in the same commit -- deliberately,
rather than discovering later that it had quietly stopped being true.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result, Store, company, project, invoice  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def run(server, crm_dir=None):
    r = Result("SHAPE/guarantees", since="all")
    crm = Path(crm_dir) if crm_dir else REPO / "plugins/unrivaled-solutions/skills/crm"
    s = Store(server)

    # ------------------------------------------------------------------ 1 --
    r.section('graph.py: "DRAFTS ONLY -- nothing here can send mail"')
    graph_src = (crm / "mcp" / "graph.py").read_text()
    promises_drafts_only = "nothing here can send mail" in graph_src.lower()
    if promises_drafts_only:
        # the id is interpolated into the URL path; a '/' or '#' in it can
        # select a different Graph action, and /reply sends immediately
        call_sites = re.findall(r'f"/me/messages/\{message_id\}[^"]*"', graph_src)
        encoded = re.search(r"quote\(\s*message_id", graph_src)
        r.check("a message_id reaching a Graph URL path is percent-encoded",
                bool(encoded) or not call_sites,
                "unencoded: a message_id of '<id>/reply#' turns createReply "
                "(drafts) into reply (SENDS), and the failure is silent")
        # and the response must be proved to be a draft, not merely not-a-draft
        r.check("the draft check is positive (is not True), not fail-open (is False)",
                "is not True" in graph_src or "is False" not in graph_src,
                "an empty 202 body passes an `isDraft is False` test")

    # ------------------------------------------------------------------ 2 --
    r.section('normalize.py: "anything ambiguous is flagged, never dropped"')
    nrm = crm / "pipeline" / "normalize.py"
    nrm_src = nrm.read_text() if nrm.exists() else ""
    promises_never_drop = "never dropped" in nrm_src.lower()
    if promises_never_drop:
        # every `continue` inside a row loop should be accompanied by a
        # needs_review append somewhere in its vicinity
        lines = nrm_src.split("\n")
        unflagged = []
        for i, ln in enumerate(lines):
            if re.match(r"\s+continue\s*$", ln):
                window = "\n".join(lines[max(0, i - 12):i + 1])
                if "needs_review" not in window and "review.append" not in window \
                        and "flag(" not in window:
                    unflagged.append(i + 1)
        r.check("every row-skip path records a needs_review entry",
                not unflagged,
                f"unflagged `continue` at lines {unflagged[:8]}"
                f"{'...' if len(unflagged) > 8 else ''} -- a dropped row is a "
                f"receivable that never exists")
        # and the row caps must not silently truncate
        caps = re.findall(r"max_row\s*=\s*(\d+)", nrm_src)
        r.check("no hard max_row cap truncates a growing ledger without a flag",
                not caps,
                f"caps present: {caps} -- rows beyond these vanish with no signal, "
                f"and the ledger grows past them on its own")

    # ------------------------------------------------------------------ 3 --
    r.section('server.py _key: "every comparison MUST go through this"')
    srv_src = (crm / "mcp" / "server.py").read_text()
    bare = re.findall(r'str\(\s*\w+(?:\.get\()?["\']?(?:project_no|invoice_no)'
                      r'["\']?\)?\s*\)\s*==', srv_src)
    r.check("no identifier comparison uses a bare str()",
            not bare, f"{len(bare)} bare str() comparison(s) remain")

    # ------------------------------------------------------------------ 4 --
    r.section('server.py: "effective_due_on ... never persisted"')
    s.reset(companies=[company()])
    s.call("create_invoice", company_id="acme",
           fields={"invoice_no": "7001", "invoice_date": "2026-03-01"})
    s.call("update_invoice", company_id="acme", invoice_no="7001",
           fields={"payment_status": "paid"})
    s.call("rename_invoice", company_id="acme", old_invoice_no="7001",
           new_invoice_no="7002")
    on_disk = s.read("invoices")
    r.check("effective_due_on is returned but never written to disk",
            all("effective_due_on" not in i for i in on_disk),
            str([sorted(i) for i in on_disk])[:120])

    # ------------------------------------------------------------------ 5 --
    r.section('server.py: importer provenance "cannot be set by a caller"')
    s.reset(companies=[company()])
    locked = ("source", "payment_status_raw", "sheet_row")
    for f in locked:
        r.check(f"{f} is refused on create",
                s.call("create_invoice", company_id="acme",
                       fields={"invoice_no": "1", f: "x"}).get("ok") is False)
        s.reset(companies=[company()], invoices=[invoice("9001")])
        r.check(f"{f} is refused on update",
                s.call("update_invoice", company_id="acme", invoice_no="9001",
                       fields={f: "x"}).get("ok") is False)

    # ------------------------------------------------------------------ 6 --
    r.section('server.py: a tool returns {ok:false}, never a raw exception')
    s.reset(companies=[company(display_name=["a", "list"])],
            projects=[{"company_id": "acme"}],
            invoices=[invoice("9001", project_no=True)])
    for tool, args in (("get_company", {"ref": "a"}), ("list_companies", {"query": "a"}),
                       ("list_invoices", {}), ("list_projects", {}),
                       ("list_shipments", {}), ("crm_info", {})):
        res = s.call(tool, **args)
        r.check(f"{tool} never raises across the wire",
                "_raised" not in res, res.get("_raised", ""))

    # ------------------------------------------------------------------ 7 --
    r.section('docs: a refusal must not name a tool that also refuses')
    # an error that routes the operator into a tool which then refuses (or,
    # worse, corrupts) was a real defect twice
    s.reset(companies=[company()],
            projects=[project("4521", archived=True), project("4521")])
    msg = str(s.call("create_invoice", company_id="acme",
                     fields={"invoice_no": "1", "project_no": "4521"}).get("error", ""))
    if "rename_project" in msg:
        follow = s.call("rename_project", old_project_no="4521",
                        new_project_no="4599")
        r.check("a message naming rename_project leads somewhere that works",
                follow.get("ok") is True,
                "the advised tool also refuses -- the operator is in a loop")
    else:
        r.check("the ambiguity refusal does not route into a dead end", True)

    return r

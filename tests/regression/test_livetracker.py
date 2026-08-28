"""The Live Tracker's IMPORT half: status decoded from a cell FILL COLOUR.

Nothing else in this system reads formatting. Every other field is a value in a
cell, and `values_only=True` -- which the importer used everywhere -- never
materialises a cell object, so the fill was invisible to five releases. That
makes this module's failure mode unlike the rest of the suite's: the import
still succeeds, every count still looks right, and the single most meaningful
field on the sheet is simply absent or, worse, wrong.

Four decisions are asserted here because each one has an obvious alternative
that is silently wrong:

 1. THE LEGEND IS FOUND BY STRUCTURE, NOT BY COLOUR. The legend rows sit below
    the last row carrying a project key. Scanning for "rows with a bucket
    colour" instead reads the first coloured *data* row as the legend -- and
    then reads the actual legend rows as live projects. The fixture below has
    exactly that trap in it (row 7): a real, unkeyed, cyan data row above the
    boundary. A colour-anchored implementation passes every count and gets
    both halves backwards.

 2. FF00FF00 IS REGISTERED AS NEVER-A-BUCKET. It marks the second table's
    section headers. With no entry it is an unknown colour and raises a review
    flag on every single import, which is how a review list becomes noise.

 3. AN UNKNOWN COLOUR IS NEVER GUESSED. Nearest-colour matching is the obvious
    thing to do and it would file a job under the wrong person's name with no
    trace. Status stays unset and the entry names the ARGB and the row.

 4. THE NOTE BELONGS TO THE PROJECT. It used to live only on shipments, copied
    onto every leg -- five copies on the busiest row, so editing one left four
    disagreeing -- and no copy at all on a row with no legs. Row 3 of the
    fixture is that row: a live project, a real note, zero vendor legs.

Fixture names are invented. This repo is PUBLIC and the whole tree is swept.
The bucket LABELS in particular are read from the sheet at import and stored,
never written into source -- on the real workbook they name people.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402

MAGENTA = "FFFF00FF"        # -> action_admin
YELLOW = "FFFFFF00"         # -> action_owner
CYAN = "FF00FFFF"           # -> awaiting_materials
GREEN = "FF00FF00"          # registered as explicitly NOT a bucket
UNKNOWN = "FFAB12CD"        # in no table at all -- must never be guessed

# Invented legend text. On the real sheet these name people.
L_ADMIN = "Waiting on the office"
L_OWNER = "With the rep"
L_AWAIT = "Waiting on materials"

NOTE_NO_LEGS = "Quote re-issued 7/2; customer still deciding on the guarding."
NOTE_FIVE_LEGS = ("Frames from two suppliers, one short-shipped. Chase the "
                  "balance before the crate ships.")


def _load(crm_dir, name):
    import importlib.util
    p = Path(crm_dir) / "pipeline" / name
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_lt_{name}", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tracker_row(key, client, note, legs=(), client_po=None):
    """One Open Orders row. A=key, B=client PO, C=start, D=client, E=location,
    F=note, then G.. as vendor PO / ship-date pairs.

    The client PO always carries digits, as a real one does: pick_client scans
    B through E for the first name-shaped cell, and a digitless "PO-X" reads as
    a company name rather than as a PO."""
    row = [key, client_po or f"PO-{key or '9090'}", None, client,
           "Dayton OH", note]
    for po, date in legs:
        row += [po, date]
    return row


def _build_workbook(path, legend=(L_ADMIN, L_OWNER, L_AWAIT)):
    """The Project Tracker sheet, with fills, laid out exactly like the real
    one: data rows, then a blank, then the legend, then the second table.

    `legend` is the three labels in bucket order. A None entry writes the
    coloured legend row with no text in it -- a bucket the sheet never names."""
    import openpyxl
    from openpyxl.styles import PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Tracker 2026"
    ws.append(["Project#", "Date", "Customer", "Description", "Location",
               "Status", "PO Y/N", "Client PO#", "Invoice #", "Revenue",
               "Total Cost", "Total GP", "Margain", "Notes"])
    for pno, cust, desc in (
            ("5001", "Brightwater Fabrication", "Conveyor upgrade"),
            ("5002", "Brightwater Fabrication", "Guarding package"),
            ("5003", "Ironvale Supply", "Frame set"),
            ("5004", "Ironvale Supply", "Spare parts"),
            ("5005", "Kestrel Works", "Retrofit"),
            ("5006", "Kestrel Works", "Empty-note job")):
        ws.append([pno, None, cust, desc, "Dayton OH", "won", "N", None, None,
                   10000, 6000, 4000, 0.4, ""])

    pt = wb.create_sheet("Project Tracker")
    pt.append(["Unrivaled Project#:", "Client PO#:", "Start Date:",
               "Client Name:", "Client Location:", "Open Orders Notes:",
               "Vendor 1 PO#:", "Vendor 1 Ship Date:"])
    # row 2 -- magenta, matches project 5001
    pt.append(_tracker_row("5001", "Brightwater Fabrication", "On the bench",
                           [("VPO-1", "2026-09-01")]))
    # row 3 -- yellow, a real note and NO vendor legs at all. This is the row
    # the old shipment-only note could not represent.
    pt.append(_tracker_row("5002", "Brightwater Fabrication", NOTE_NO_LEGS))
    # row 4 -- cyan, five legs, the fifth in column U/V (vendor 8). The old
    # loop stopped at S/T and dropped a filled U in silence.
    pt.append(_tracker_row("5003", "Ironvale Supply", NOTE_FIVE_LEGS, [
        ("VPO-A", "2026-09-02"), ("VPO-B", "2026-09-03"),
        ("VPO-C", "2026-09-04"), ("VPO-D", "2026-09-05"),
        (None, None), (None, None), (None, None), ("VPO-U8", "2026-09-06"),
    ]))
    # row 5 -- a colour in no table. Must not be guessed at.
    pt.append(_tracker_row("5004", "Ironvale Supply", "Unknown fill here"))
    # row 6 -- GREEN. Registered as never-a-bucket, so: no status, and no flag.
    pt.append(_tracker_row("5005", "Kestrel Works", "Green section marker"))
    # row 7 -- yellow, and its notes cell is EMPTY. Status is the fill, not the
    # text, so it must still bucket -- and no note must be written over it.
    pt.append(_tracker_row("5006", "Kestrel Works", None))
    # row 8 -- THE TRAP. A real data row, cyan, with content but no project
    # number, sitting ABOVE the boundary. A colour-anchored legend scan reads
    # THIS as the legend and the rows below as live work.
    pt.append(_tracker_row(None, "Meridian Corp", "No number on this one yet",
                           [("VPO-M1", "2026-09-08")]))
    # row 9 -- keyed, but the deal log has nothing answering to it. LAST KEYED
    # ROW, so this is where the boundary sits.
    pt.append(_tracker_row("5999", "Ironvale Supply", "Keyed but unmatched",
                           [("VPO-Z", None)]))
    pt.append([None] * 8)                                       # row 10, blank
    for lab in legend:                                          # rows 11-13
        pt.append([None] * 5 + [lab])
    pt.append([None] * 5 + ["CLIENT INVOICES BELOW"])           # row 14 header
    pt.append(["Invoice Number:", "PO#", "Invoice Date", "DUE Date",
               "Client", "Notes"])                              # row 15

    for row, argb in ((2, MAGENTA), (3, YELLOW), (4, CYAN), (5, UNKNOWN),
                      (6, GREEN), (7, YELLOW), (8, CYAN), (9, CYAN),
                      (11, MAGENTA), (12, YELLOW), (13, CYAN), (14, GREEN)):
        pt.cell(row=row, column=6).fill = PatternFill(
            start_color=argb, end_color=argb, fill_type="solid")

    cc = wb.create_sheet("Client Contacts")
    cc.append(["Client Business", "Client Name", "Email", "Phone Number",
               "Job Title", "Location", "Action Taken and Notes",
               "Last Date of Action"])
    vc = wb.create_sheet("Vendor Contacts")
    vc.append(["Company", "Headquarters Location", "Sales Rep/Contact",
               "Contact Email", "Contact Phone Number", "Offerings",
               "Send PO's to", "Send Invoices to"])
    wb.save(path)


def _build_edge_workbook(path, *, trailing_unkeyed=False, stray_col_a=False,
                         theme_row=False, default_fill_row=False,
                         keyed_bodyless_unknown=False, footer_stray_leg=False,
                         legend_unreadable=False):
    """A minimal sheet for the boundary and fill-decode edge cases.

    Kept separate from the main fixture: each flag here changes what the
    boundary or the decoder is being asked, and folding them into one sheet
    would make a failure ambiguous about which rule broke.
    """
    import openpyxl
    from openpyxl.styles import Color, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Tracker 2026"
    ws.append(["Project#", "Date", "Customer", "Description", "Location",
               "Status", "PO Y/N", "Client PO#", "Invoice #", "Revenue",
               "Total Cost", "Total GP", "Margain", "Notes"])
    for pno in ("6001", "6002", "6003"):
        ws.append([pno, None, "Brightwater Fabrication", f"Job {pno}",
                   "Dayton OH", "won", "N", None, None,
                   10000, 6000, 4000, 0.4, ""])

    pt = wb.create_sheet("Project Tracker")
    pt.append(["Unrivaled Project#:", "Client PO#:", "Start Date:",
               "Client Name:", "Client Location:", "Open Orders Notes:",
               "Vendor 1 PO#:", "Vendor 1 Ship Date:"])
    pt.append(_tracker_row("6001", "Brightwater Fabrication", "on the bench"))
    pt.append(_tracker_row("6002", "Brightwater Fabrication", "theme fill here"))
    # row 4 is the LAST row that is both keyed and carries a body, so the
    # boundary sits here and everything below is footer as far as position goes
    pt.append(_tracker_row("6003", "Brightwater Fabrication", "default fill"))
    if keyed_bodyless_unknown:
        # Keyed but with nothing else on it, so it does not move the boundary
        # -- and therefore sits below it. Its fill is still unrecognised and
        # its flag must still fire: a row with a key is a data row wherever it
        # sits, and tying the flag to the boundary lost both the status and
        # any mention of it.
        pt.append(["6004"] + [None] * 7)
    elif trailing_unkeyed:
        # A real job appended at the bottom before it has a number -- the
        # normal way a row gets added. It sits BELOW the boundary.
        pt.append(_tracker_row(None, "Meridian Corp", "new job, no number yet",
                               [("VPO-N1", "2026-09-09")]))
    else:
        pt.append([None] * 8)
    pt.append([None] * 8)
    for lab in (L_ADMIN, L_OWNER, L_AWAIT):
        pt.append([None] * 5 + [lab])
    if footer_stray_leg:
        # A footer line with its label AND one stray character in a vendor-PO
        # column. One cell is not a job; treating it as one invents a vendor
        # leg on a phantom project, one click from create_project.
        pt.append([None] * 5 + ["Colour key updated 8/9", "x", None])
    elif stray_col_a:
        # A date stamp typed under the legend. Column A, nothing else. Enough,
        # once, to drag the boundary past the whole legend block.
        pt.append(["Updated 8/9/26"] + [None] * 7)
    else:
        pt.append([None] * 8)
    pt.append(["Invoice Number:", "PO#", "Invoice Date", "DUE Date",
               "Client", "Notes"])

    solid = {2: MAGENTA, 4: None}
    for row, argb in solid.items():
        if argb:
            pt.cell(row=row, column=6).fill = PatternFill(
                start_color=argb, end_color=argb, fill_type="solid")
    if keyed_bodyless_unknown:
        pt.cell(row=5, column=6).fill = PatternFill(
            start_color=UNKNOWN, end_color=UNKNOWN, fill_type="solid")
    if theme_row:
        # A colour from the top row of Excel's fill dropdown. openpyxl hands
        # back the RGB DESCRIPTOR here, not a string.
        pt.cell(row=3, column=6).fill = PatternFill(
            fill_type="solid", fgColor=Color(theme=4, tint=0.4))
    if default_fill_row:
        # solid with no explicit foreground -> openpyxl reports '00000000'
        pt.cell(row=4, column=6).fill = PatternFill(fill_type="solid")
    for row in (7, 8, 9):
        argb = {7: MAGENTA, 8: YELLOW, 9: CYAN}[row]
        pt.cell(row=row, column=6).fill = PatternFill(
            start_color=argb, end_color=argb, fill_type="solid")
    if footer_stray_leg:
        pt.cell(row=10, column=6).fill = PatternFill(
            start_color=MAGENTA, end_color=MAGENTA, fill_type="solid")
    if legend_unreadable:
        # The legend row is right there on the sheet; only its colour cannot be
        # read. Reporting that as "no legend row found" sends him looking for a
        # row that is not missing.
        pt.cell(row=7, column=6).fill = PatternFill(
            fill_type="solid", fgColor=Color(theme=4, tint=0.4))

    for n in ("Client Contacts", "Vendor Contacts"):
        wb.create_sheet(n).append(["x"])
    wb.save(path)


def _import_edge(nrm, crm, tmp, name, **kw):
    xl = tmp / f"{name}.xlsx"
    _build_edge_workbook(xl, **kw)
    out = tmp / f"store-{name}"
    out.mkdir()
    added = str(crm / "pipeline")
    did = added not in sys.path
    if did:
        sys.path.insert(0, added)
    err = None
    try:
        nrm.run(str(xl), str(out), force=False, mode="merge")
    except Exception as exc:                                  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        if did:
            try:
                sys.path.remove(added)
            except ValueError:
                pass

    def load(entity):
        p = out / f"{entity}.json"
        return json.loads(p.read_text()) if p.exists() else None
    return err, load


def _import(nrm, crm, tmp, name, **wbkw):
    """Build a fixture workbook, import it, return (error, loader)."""
    xl = tmp / f"{name}.xlsx"
    _build_workbook(xl, **wbkw)
    out = tmp / f"store-{name}"
    out.mkdir()
    added = str(crm / "pipeline")
    did_add = added not in sys.path
    if did_add:
        sys.path.insert(0, added)       # normalize imports merge as a sibling
    err = None
    try:
        nrm.run(str(xl), str(out), force=False, mode="merge")
    except Exception as exc:                                  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        if did_add:
            try:
                sys.path.remove(added)
            except ValueError:
                pass

    def load(entity):
        p = out / f"{entity}.json"
        return json.loads(p.read_text()) if p.exists() else None
    return err, load


def _merge_checks(r, crm, tmp):
    """Re-import behaviour for the tracker fields.

    Both cases here are UPGRADE-PATH bugs: they only appear on the second
    import, which is why asserting the REGENERATED set's source text was not
    enough. The screen the operator lands on is built from the merged store,
    not from the import."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lt_merge", crm / "pipeline" / "merge.py")
    merge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merge)

    def store(name, projects, changelog=None, dismissed=None):
        d = tmp / f"mg-{name}"
        d.mkdir(parents=True, exist_ok=True)
        if dismissed is not None:
            (d / "tracker_dismissed.json").write_text(json.dumps(dismissed))
        for e in ("companies", "contacts", "shipments", "vendors",
                  "needs_review", "invoices"):
            (d / f"{e}.json").write_text("[]")
        (d / "companies.json").write_text(json.dumps(
            [{"company_id": "acme", "display_name": "Ace", "role": "customer",
              "archived": False}]))
        (d / "projects.json").write_text(json.dumps(projects))
        if changelog is not None:
            (d / "changelog.jsonl").write_text(changelog)
        return d

    def fresh(projects, unlinked):
        return {"companies.json": [{"company_id": "acme", "display_name": "Ace",
                                    "role": "customer", "archived": False}],
                "contacts.json": [], "shipments.json": [], "invoices.json": [],
                "vendors.json": [], "needs_review.json": [],
                "tracker_buckets.json": [], "tracker_unlinked.json": unlinked,
                "projects.json": projects}

    # ---- add-only mode still has to land the status -----------------------
    # changelog.jsonl is created lazily, on the first edit. A store that was
    # imported and never edited has data and NO changelog, which puts merge in
    # add-only mode: every existing record untouched. That meant tracker_status
    # never reached a single pre-existing project, so the operator upgraded,
    # imported, landed on the new default screen and read "No live projects
    # yet" -- permanently, on every subsequent import too.
    r.section("upgrading a store with no changelog still fills the tracker")
    d = store("addonly", [{"project_no": "4521", "company_id": "acme",
                           "status": "won", "revenue": 50000,
                           "archived": False}])
    merged, rep = merge.merge_all(
        fresh([{"project_no": "4521", "company_id": "acme", "status": "won",
                "revenue": 50000, "archived": False,
                "tracker_status": "action_admin", "tracker_row": 4,
                "open_orders_notes": "from the sheet"}], []), str(d))
    got = merged["projects.json"][0]
    r.check("add-only mode is what is under test here",
            "no changelog" in str(rep.get("note") or ""),
            f"got note {rep.get('note')!r} -- if this is not add-only mode the "
            f"checks below prove nothing")
    r.check("the status colour reaches an existing project anyway",
            got.get("tracker_status") == "action_admin",
            f"got {got.get('tracker_status')!r} -- the workbook owns this "
            f"field outright and nothing in the app can edit it, so there is "
            f"no operator edit for add-only mode to be protecting")
    r.check("and so does the row it came from", got.get("tracker_row") == 4)
    r.check("the operator's own revenue figure is still untouched",
            got.get("revenue") == 50000)
    r.check("the note is NOT force-refreshed in add-only mode",
            "open_orders_notes" not in got,
            "unlike the status, the note IS writable through the tools, so in "
            "add-only mode it stays the operator's")
    r.check("and the report says the status is the exception",
            "status" in str(rep.get("note") or "").lower(),
            f"got {rep.get('note')!r} -- a mode that says it refreshed nothing "
            f"while refreshing something is worse than either")

    # The other direction. In add-only mode a cleared colour does NOT retire:
    # "absent from the fresh record" is indistinguishable from "the tracker
    # matched nothing this run" (normalize only attaches these fields to a
    # project a tracker row matched), and popping on absence emptied the whole
    # Live screen off one import from an older copy of the workbook -- and took
    # tracker_row with it, which the importer can never re-derive. A stale
    # bucket is recoverable by importing the right workbook. A wiped one is not.
    d = store("addonly-retire", [{"project_no": "4521", "company_id": "acme",
                                  "status": "won", "archived": False,
                                  "tracker_status": "action_admin",
                                  "tracker_row": 4}])
    merged, _ = merge.merge_all(
        fresh([{"project_no": "4521", "company_id": "acme", "status": "won",
                "archived": False}], []), str(d))
    got = merged["projects.json"][0]
    r.check("add-only mode refreshes the status but never removes it",
            got.get("tracker_status") == "action_admin",
            f"got {got.get('tracker_status')!r} -- in add-only mode an absent "
            f"field means 'this workbook told us nothing', not 'retired'")
    r.check("and keeps the row reference the adopt flow wrote",
            got.get("tracker_row") == 4,
            f"got {got.get('tracker_row')!r} -- only saveAdoptTrackerRow ever "
            f"writes this for a numberless row; the importer cannot put it back")

    # With a changelog present the ordinary rule applies and a cleared colour
    # DOES retire -- so the leniency above is scoped to add-only mode, not a
    # blanket refusal to ever retire a card.
    d = store("retire-normal", [{"project_no": "4521", "company_id": "acme",
                                 "status": "won", "archived": False,
                                 "tracker_status": "action_admin",
                                 "tracker_row": 4}],
              changelog=json.dumps({"entity": "project", "key": "4521",
                                    "op": "update", "fields": ["revenue"]}) + "\n")
    merged, _ = merge.merge_all(
        fresh([{"project_no": "4521", "company_id": "acme", "status": "won",
                "archived": False}], []), str(d))
    got = merged["projects.json"][0]
    r.check("a colour cleared in Excel retires normally",
            not got.get("tracker_status"),
            f"got {got.get('tracker_status')!r} -- the row is off the tracker, "
            f"so a card for it is work the sheet says is finished")

    # ---- the dismissal table, and the rule that bounds it -----------------
    #
    # Key-matching is gone. A row leaves the "Not in the CRM yet" list because
    # the OPERATOR said so -- adopting it, or dismissing it -- and never
    # because something derived a match from the sheet's free text.
    #
    # The one rule: a dismissal is scoped to the row AS IT EXISTS IN THE
    # CURRENT SHEET. Dismissals whose rows are absent from this import are
    # SWEPT. A dismissal store that accumulates is by_sheet_key with a new
    # name, and it would grow the same unbounded staleness.
    r.section("a dismissal suppresses its row, and only while the row exists")

    def fp_of(u):
        """The fingerprint normalize stamps. Tests read it off the row -- they
        never recompute it, for the same reason the view never does."""
        return u.get("fingerprint")

    # parsed_keys, as the real importer writes it: raw_key is for DISPLAY and
    # parsed_keys is for MATCHING, and they are not the same string -- a
    # numeric key cell reaches str() as "1419.0" while the project side
    # de-floats to "1419". by_key matches the parse, never the display text.
    ROW_A = {"sheet_row": 8, "reason": "no matching project", "raw_key": "1419",
             "parsed_keys": ["1419"],
             "client": "Ironvale Supply", "open_orders_notes": "live job",
             "legs": [], "fingerprint": "aaaaaaaaaaaaaaaa"}
    ROW_B = {"sheet_row": 9, "reason": "no project number",
             "client": "Meridian Corp", "open_orders_notes": "also live",
             "legs": [], "fingerprint": "bbbbbbbbbbbbbbbb"}

    d = store("dis-hold", [], dismissed=[{"fingerprint": "aaaaaaaaaaaaaaaa",
                                          "reason": "not_a_job",
                                          "client": "Ironvale Supply",
                                          "sheet_row": 8}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A), dict(ROW_B)]), str(d))
    unl = merged["tracker_unlinked.json"]
    shown = [u for u in unl if not u.get("dismissed")]
    r.check("a dismissed row is suppressed from the live list",
            [u.get("sheet_row") for u in shown] == [9],
            f"got {[u.get('sheet_row') for u in shown]}")
    r.check("but it is STILL in the store, flagged",
            any(u.get("sheet_row") == 8 and u.get("dismissed") for u in unl),
            f"got {unl} -- deleting it means the screen cannot show a count, "
            f"and a dismissal the operator cannot see is one that can hide a "
            f"live job")
    r.check("and the dismissal survives an import where its row is present",
            len(merged.get("tracker_dismissed.json") or []) == 1,
            "a dismissal must hold while its row is unchanged")

    # THE SWEEP. Row A is gone from this week's sheet, so its dismissal has
    # nothing to scope to and is dropped -- permanently, not banked.
    d = store("dis-sweep", [], dismissed=[{"fingerprint": "aaaaaaaaaaaaaaaa",
                                           "reason": "not_a_job", "sheet_row": 8},
                                          {"fingerprint": "bbbbbbbbbbbbbbbb",
                                           "reason": "already_adopted",
                                           "sheet_row": 9}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_B)]), str(d))
    kept = merged.get("tracker_dismissed.json")
    kept = kept if isinstance(kept, list) else []
    r.check("a dismissal whose row is absent is SWEPT",
            [x.get("fingerprint") for x in kept] == ["bbbbbbbbbbbbbbbb"],
            f"got {[x.get('fingerprint') for x in kept]} -- a dismissal that "
            f"outlives its row is the accumulation this replaced")
    r.check("and the report says how many it swept",
            rep.get("dismissals_swept") == 1,
            f"got {rep.get('dismissals_swept')!r}")

    # The flag on the ROW is derived; tracker_dismissed.json is the authority.
    # A row arriving with dismissed:true stamped from a previous import, whose
    # dismissal has since been swept, must come back -- otherwise the flag
    # outlives the record that justified it and hides the row forever.
    d = store("dis-stale-flag", [], dismissed=[])
    merged, rep = merge.merge_all(
        fresh([], [dict(ROW_A, dismissed=True)]), str(d))
    shown = [u for u in merged["tracker_unlinked.json"] if not u.get("dismissed")]
    r.check("a stale dismissed flag with no dismissal behind it is stripped",
            [u.get("sheet_row") for u in shown] == [8],
            f"got {merged['tracker_unlinked.json']} -- the flag is derived "
            f"from the table; a flag that can outvote it is a second "
            f"authority, and the two will disagree")

    # THE BOUND, asserted directly rather than inferred from the sweep.
    r.check("the table can never exceed this import's unlinked row count",
            len(kept) <= len(merged["tracker_unlinked.json"]),
            f"{len(kept)} dismissals vs "
            f"{len(merged['tracker_unlinked.json'])} rows -- the table is "
            f"bounded by construction or it is not bounded at all")

    # THE RETITLE, asserted as EXACTLY once. He dismissed the row; he then
    # edits it on the sheet; it comes back for a fresh look; he dismisses the
    # NEW row; it stays gone. A third import with no further change must not
    # resurface it -- that would be an unbounded loop, not a bounded one.
    d = store("dis-retitle", [], dismissed=[{"fingerprint": "aaaaaaaaaaaaaaaa",
                                             "reason": "already_adopted",
                                             "sheet_row": 8}])
    RETITLED = dict(ROW_A, client="Ironvale Supply Co",
                    fingerprint="cccccccccccccccc")
    merged, rep = merge.merge_all(fresh([], [dict(RETITLED)]), str(d))
    shown = [u for u in merged["tracker_unlinked.json"] if not u.get("dismissed")]
    r.check("a retitled row reappears once",
            [u.get("sheet_row") for u in shown] == [8],
            f"got {shown} -- its content changed, so the operator gets one "
            f"fresh look rather than a matcher deciding for him")
    r.check("and the stale dismissal went with it",
            merged.get("tracker_dismissed.json") == [],
            "the old fingerprint scopes to a row that no longer exists")
    # he dismisses it again
    d = store("dis-retitle2", [], dismissed=[
        {"fingerprint": "cccccccccccccccc", "reason": "already_adopted",
         "sheet_row": 8}])
    merged, rep = merge.merge_all(fresh([], [dict(RETITLED)]), str(d))
    shown = [u for u in merged["tracker_unlinked.json"] if not u.get("dismissed")]
    r.check("and once dismissed again it stays gone -- EXACTLY once",
            shown == [],
            f"got {shown} -- reappearing a second time with nothing changed "
            f"would be an unbounded loop wearing a bounded rule's clothes")

    r.section("a row retires itself once its number is a project")
    # by_key is KEPT: the sheet's parsed number against the numbers currently in
    # the store. One time horizon, both sides read now. This is what makes the
    # migration burn down -- adopt a row and it retires itself next import,
    # instead of needing a second click on the one pass that matters.
    d = store("bykey-num", [{"project_no": "1419", "company_id": "acme",
                             "status": "won", "archived": False}],
              changelog=json.dumps({"entity": "project", "key": "1419",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    left = [u.get("sheet_row") for u in merged["tracker_unlinked.json"]]
    r.check("a row whose number is now a project retires itself",
            left == [], f"got {left}")
    r.check("and the report names it",
            "1419" in str(rep.get("adopted")), f"got {rep.get('adopted')!r}")

    # Archiving is this product's delete. A mistakenly-adopted project that has
    # been archived must RELEASE its row rather than keep suppressing it --
    # otherwise the job is on neither list and the only way back is a tool call
    # through chat. There is no second suppression path left to disagree.
    d = store("bykey-arch", [{"project_no": "1419", "company_id": "acme",
                              "status": "won", "archived": True}],
              changelog=json.dumps({"entity": "project", "key": "1419",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    left = [u.get("sheet_row") for u in merged["tracker_unlinked.json"]]
    r.check("an ARCHIVED project releases its row again",
            left == [8],
            f"got {left} -- archiving is delete; a row suppressed by a deleted "
            f"project is on neither list")
    # by_sheet_key is the half that was deleted: the sheet's own free-text key,
    # recorded on the project at adoption and accumulated forever.
    d = store("nokey-phrase", [{"project_no": "1500", "company_id": "acme",
                                "status": "won", "archived": False,
                                "tracker_key": "1419"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    shown = [u for u in merged["tracker_unlinked.json"] if not u.get("dismissed")]
    r.check("a stored tracker_key suppresses nothing",
            [u.get("sheet_row") for u in shown] == [8],
            f"got {shown} -- it accumulated a key from every adoption ever "
            f"made and compared it against a sheet that turns over, so a row "
            f"nobody adopted was retired by a phrase somebody adopted months "
            f"ago. tracker_key is provenance now, read by nothing")

    r.section("the sweep does not destroy what it could not read")
    d = store("dis-preserve", [])
    (d / "tracker_dismissed.json").write_text("{ half writ")
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    r.check("an unreadable dismissal file is LEFT ALONE, not rewritten empty",
            "tracker_dismissed.json" not in merged,
            "_finish writes every key of the merged dict, so putting an empty "
            "list there deletes the file the report just told him to fix -- "
            "and a half-written OneDrive file is readable again in ten minutes")
    r.check("and the file on disk still holds what it held",
            (d / "tracker_dismissed.json").read_text() == "{ half writ")

    r.section("replace mode is not silent about what it swept")
    d = store("repl-report", [], dismissed=[
        {"fingerprint": "gone-from-the-sheet", "reason": "not_a_job"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    # EXECUTED, not grepped. This was a source-text assertion that the word
    # "report" appeared inside sweep_dismissals_only -- and it stayed green
    # over a format_report that raised KeyError on the very report that
    # function produces. A check that reads the source cannot tell whether the
    # thing it names works.
    d = store("repl-crash", [], dismissed=[
        {"fingerprint": "gone-from-the-sheet", "reason": "not_a_job"}])
    _m, _rep = merge.sweep_dismissals_only(
        fresh([], [dict(ROW_A)]), str(d))
    blew = None
    try:
        printed = merge.format_report(_rep)
    except Exception as exc:                                  # noqa: BLE001
        printed, blew = "", f"{type(exc).__name__}: {exc}"
    r.check("replace mode's report can actually be PRINTED",
            blew is None,
            f"{blew} -- the import has already written every file by then, so "
            f"this is a traceback and exit 1 on top of a successful import, "
            f"and he never sees the line it was raising about")
    r.check("and it says what it swept",
            "CLEARED" in printed and "1" in printed, f"got:\n{printed}")

    r.section("an unvalidated reason from the store does not mislabel a card")
    d = store("dis-badreason", [], dismissed=[
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "whatever he typed"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    _rows = merged["tracker_unlinked.json"]
    row = _rows[0] if _rows else {}
    r.check("an unrecognised reason is normalised, not passed through",
            row.get("reason_dismissed") in ("not_a_job", "already_adopted",
                                            "adopted_here"),
            f"got {row.get('reason_dismissed')!r} -- the card maps three "
            f"literals and falls through to 'not a job', so a hand-edited "
            f"reason silently relabels a row he dismissed as already-in-the-CRM")

    r.section("the report still names what the workbook stopped listing")
    # A RANGE deletion took these out with the dead report["adopted"] block.
    # merge_all still populates both, so records the workbook no longer lists
    # were being kept SILENTLY -- the exact silence this module exists to end,
    # reintroduced by a tidy-up.
    out = merge.format_report({"note": "", "refreshed": 1, "added": 0,
                               "preserved": [], "untouched": 3,
                               "kept": [{"file": "invoices.json", "key": "7001",
                                         "why": "not in the workbook"}]})
    r.check("records kept but no longer in the workbook are named",
            "7001" in out and "no longer" in out.lower(),
            f"got:\n{out}")
    r.check("and untouched records are counted",
            "3 record(s)" in out and "untouched" in out, f"got:\n{out}")

    r.section("de-duplication is not reported as sweeping")
    d = store("dis-count", [], dismissed=[
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "not_a_job"},
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "not_a_job"},
        {"fingerprint": "bbbbbbbbbbbbbbbb", "reason": "not_a_job"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    r.check("only the row that LEFT the sheet counts as swept",
            rep.get("dismissals_swept") == 1,
            f"got {rep.get('dismissals_swept')} -- counting a duplicate as a "
            f"sweep makes the counter that is supposed to prove the bound is "
            f"working into evidence nobody can trust")
    out = merge.format_report(rep)
    r.check("and the sentence it prints is true",
            "CLEARED 1 dismissal" in out, f"got:\n{out}")

    r.section("the sweep de-duplicates, so the count means something")
    d = store("dis-dupes", [], dismissed=[
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "not_a_job"},
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "not_a_job"},
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "already_adopted"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    r.check("three entries for one row collapse to one",
            len(merged["tracker_dismissed.json"]) == 1,
            f"got {merged['tracker_dismissed.json']} -- a conflicted copy "
            f"concatenated by OneDrive would report 'HOLDING 3 rows' for one")
    r.check("and the reported count matches the rows",
            rep.get("dismissed") == 1, f"got {rep.get('dismissed')}")

    r.section("a legacy row with no fingerprint is never swept up by accident")
    d = store("dis-legacy", [], dismissed=[{"fingerprint": None}])
    merged, rep = merge.merge_all(
        fresh([], [{"sheet_row": 8, "client": "Old", "legs": []}]), str(d))
    r.check("a null fingerprint does not match a row that has none",
            not any(u.get("dismissed") for u in merged["tracker_unlinked.json"]),
            f"got {merged['tracker_unlinked.json']} -- str(None) is 'None' on "
            f"both sides, which flags EVERY pre-upgrade row at once")

    r.section("the reason survives the round trip to the screen")
    d = store("dis-reason", [], dismissed=[{"fingerprint": "aaaaaaaaaaaaaaaa",
                                            "reason": "already_adopted"}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    out_rows = merged["tracker_unlinked.json"]
    # .get on a possibly-empty list, not [0]: a mutant that DELETES the
    # dismissed row instead of flagging it would crash here, and a module that
    # dies has evaluated nothing -- which this suite scores as no evidence
    # rather than as a kill.
    row = out_rows[0] if out_rows else {}
    r.check("the dismissed row is kept, and carries WHY",
            len(out_rows) == 1 and row.get("reason_dismissed") == "already_adopted",
            f"got {out_rows} -- deleting it leaves the screen no count to "
            f"show, and without the reason a project he adopted is labelled "
            f"'not a job' after any refresh")

    r.section("a row retired by its number takes its dismissal with it")
    # `live` was computed BEFORE the by_key drop, so a row that was both
    # dismissed and retired kept its dismissal while its row vanished: counted
    # in "HOLDING N dismissed" with zero cards on screen, no "Put it back", and
    # dismiss_tracker_row refusing it as "not on the current sheet". Archive
    # the project later and it came back ALREADY dismissed on a stale reason,
    # which defeats the archived exclusion for exactly the rows that used it.
    d = store("retire-sweeps", [{"project_no": "1419", "company_id": "acme",
                                 "status": "won", "archived": False}],
              dismissed=[{"fingerprint": "aaaaaaaaaaaaaaaa",
                          "reason": "already_adopted"}],
              changelog=json.dumps({"entity": "project", "key": "1419",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    r.check("the row is retired by its number", rep.get("adopted") == ["1419"],
            f"got {rep.get('adopted')}")
    r.check("and its dismissal is SWEPT, not stranded",
            merged.get("tracker_dismissed.json") == [],
            f"got {merged.get('tracker_dismissed.json')} -- a dismissal whose "
            f"row is gone is unreachable: no card, no button, and the tool "
            f"refuses it")
    r.check("so nothing claims to be holding it",
            not rep.get("dismissed"), f"got {rep.get('dismissed')}")

    r.section("an archived COMPANY releases its rows too")
    # by_key excluded archived PROJECTS. archive_company archives the company
    # record only, so the project stayed unarchived and by_key kept suppressing
    # its row -- while render_html drops archived companies' projects from the
    # page. The job was then on no list at all, which is the one thing this
    # screen exists to prevent.
    d = store("arch-co", [{"project_no": "1419", "company_id": "acme",
                           "status": "won", "archived": False}],
              changelog=json.dumps({"entity": "project", "key": "1419",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    (d / "companies.json").write_text(json.dumps(
        [{"company_id": "acme", "display_name": "Ace", "role": "customer",
          "archived": True}]))
    fr = fresh([], [dict(ROW_A)])
    fr["companies.json"] = [{"company_id": "acme", "display_name": "Ace",
                             "role": "customer", "archived": True}]
    merged, rep = merge.merge_all(fr, str(d))
    left = [u.get("sheet_row") for u in merged["tracker_unlinked.json"]]
    r.check("a row whose customer is archived comes back",
            left == [8],
            f"got {left} -- the project is off the page and the row is "
            f"suppressed, so the job is on no list and in no count")

    r.section("by_key matches NUMBERS, and only when it has them all")
    d = store("multi", [{"project_no": "4530", "company_id": "acme",
                         "status": "won", "archived": False}],
              changelog=json.dumps({"entity": "project", "key": "4530",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    merged, rep = merge.merge_all(
        fresh([], [dict(ROW_A, raw_key="4530 and 4531",
                        parsed_keys=["4530", "4531"])]), str(d))
    left = [u.get("sheet_row") for u in merged["tracker_unlinked.json"]]
    r.check("a row carrying TWO numbers stays until both are projects",
            left == [8],
            f"got {left} -- retiring on the first match drops the whole row "
            f"off the checklist while the second job never reaches the store")

    d = store("freetext", [{"project_no": "Word Offer", "company_id": "acme",
                            "status": "won", "archived": False}],
              changelog=json.dumps({"entity": "project", "key": "Word Offer",
                                    "op": "create", "fields": ["project_no"]}) + "\n")
    merged, rep = merge.merge_all(
        fresh([], [dict(ROW_A, raw_key="Word Proposal", parsed_keys=[])]), str(d))
    left = [u.get("sheet_row") for u in merged["tracker_unlinked.json"]]
    r.check("a phrase-keyed row is never matched against a project number",
            left == [8],
            f"got {left} -- the store really does hold free-text project_no "
            f"values ('Word Offer', 'Cash Deal?', 'INV 1065'), and falling "
            f"back to raw_key is the same free-text collision by_sheet_key "
            f"was deleted for")

    r.section("a corrupt dismissal file does not take down the import")
    d = store("dis-corrupt", [])
    (d / "tracker_dismissed.json").write_text("{ not json")
    try:
        merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
        blew = None
    except Exception as exc:                                  # noqa: BLE001
        merged, rep, blew = None, None, f"{type(exc).__name__}: {exc}"
    r.check("the import still completes", blew is None, str(blew))
    r.check("and it names the file rather than guessing it was empty",
            "tracker_dismissed" in str((rep or {}).get("dismissals_unreadable") or ""),
            f"got {(rep or {}).get('dismissals_unreadable')!r} -- a "
            f"half-written OneDrive file read as 'no dismissals' would "
            f"un-dismiss everything silently")

    # ---- an adopted row must not come back --------------------------------
    r.section("old_groups is append-only, which is what makes 334-335 safe")
    # ambiguous = {k for k,v in old_groups.items() if len(v) > 1}
    # old_by_key = {k: v[0] for k,v in old_groups.items() if len(v) == 1}
    # Two count shapes for one question. They are exact complements ONLY
    # because old_groups is built by setdefault(...).append(...), so no group
    # is ever empty. Seed it with empty lists for known keys and a zero-length
    # group is neither ambiguous nor prior -- `prior is None` then treats an
    # existing record as NEW and re-adds it. This was cleared by reasoning in
    # the commit before this one; here it is pinned instead.
    src = (crm / "pipeline" / "merge.py").read_text()
    blk = src.split("old_groups = {}", 1)[-1].split("ambiguous", 1)[0]
    r.check("groups are only ever appended to, never pre-seeded",
            "setdefault" in blk and ".append(" in blk and "= []" not in blk,
            f"got:\n{blk}\n-- any construction that can produce an EMPTY "
            f"group breaks the complement and silently re-adds records")
    d = store("groups-dupes", [{"project_no": "1419", "company_id": "acme",
                                "status": "won", "archived": False},
                               {"project_no": "1419", "company_id": "acme",
                                "status": "lost", "archived": True}],
              changelog=json.dumps({"entity": "project", "key": "1419",
                                    "op": "update", "fields": ["status"]}) + "\n")
    merged, rep = merge.merge_all(
        fresh([{"project_no": "1419", "company_id": "acme", "status": "pending"}],
              []), str(d))
    r.check("a duplicated key is reported ambiguous, not silently re-added",
            len(rep.get("ambiguous") or []) == 1
            and len(merged["projects.json"]) == 2,
            f"ambiguous={rep.get('ambiguous')} "
            f"projects={len(merged['projects.json'])} -- a third record here "
            f"is the zero-length-group failure arriving by another route")

    r.section("the sweep is reported where the operator will read it")
    # RETIRED, deliberately, rather than deleted: the checks that stood here
    # asserted by_key and by_sheet_key -- "the keyed row he adopted is gone",
    # "a .0-suffixed sheet key still matches the project it became", "a
    # phrase-keyed row he adopted is retired". Every one of them is now the
    # WRONG expectation. Nothing derives a match from the sheet any more, so a
    # row stays on the list until the operator adopts or dismisses it, and the
    # replacements are in "key-matching is gone, both halves" above plus the
    # adopt_tracker_row checks on the server side.
    #
    # The _idkey/".0" lesson those checks carried is not lost: it moved to the
    # fingerprint, which is built from the row's own content by ONE producer in
    # normalize.py, so there is no second parse to disagree with.
    #
    # What survives here is the rule the two `# skip-ok:` markers at the old
    # drop site claimed and this module exists to enforce: nothing leaves the
    # screen with nothing said.
    d = store("swept-report", [], dismissed=[
        {"fingerprint": "aaaaaaaaaaaaaaaa", "reason": "not_a_job", "sheet_row": 8},
        {"fingerprint": "bbbbbbbbbbbbbbbb", "reason": "already_adopted",
         "sheet_row": 9}])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_B)]), str(d))
    out = merge.format_report(rep)
    r.check("the printed report names the dismissals it swept",
            "1" in out and "dismiss" in out.lower(),
            f"got:\n{out}\n-- a dismissal disappearing with nothing said is "
            f"the same silence as a row disappearing")
    r.check("and names how many rows are being held dismissed",
            "held dismissed" in out.lower() or "dismissed" in out.lower(),
            f"got:\n{out}")

    d = store("clean-report", [])
    merged, rep = merge.merge_all(fresh([], [dict(ROW_A)]), str(d))
    out = merge.format_report(rep)
    r.check("and says nothing at all when there is nothing to say",
            "dismiss" not in out.lower(),
            f"got:\n{out} -- a line printed on every clean import is a line "
            f"he stops reading, and then misses the one that matters")


def run(server, crm_dir=None):
    r = Result("live-tracker/import", since="0.1.31")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    nrm = _load(crm, "normalize.py")
    if nrm is None:
        r.check("pipeline/normalize.py exists", False)
        return r

    # ---- the colour table itself --------------------------------------------
    # Asserted before the import runs, because every check below reads its
    # answers through it: if the constants are wrong the fixture is wrong too
    # and the whole module agrees with itself about nothing.
    r.section("the colour table")
    have = getattr(nrm, "BUCKET_BY_ARGB", None)
    if not isinstance(have, dict):
        r.check("BUCKET_BY_ARGB exists", False, "no colour table to decode with")
        return r
    r.check("three bucket colours, no more", len(have) == 3,
            f"got {sorted(have)} -- a fourth would group live work under a "
            f"heading the legend never names")
    for argb, key in ((MAGENTA, "action_admin"), (YELLOW, "action_owner"),
                      (CYAN, "awaiting_materials")):
        r.check(f"{argb} decodes to {key}", have.get(argb) == key,
                f"got {have.get(argb)!r}")
    nonb = getattr(nrm, "NON_BUCKET_ARGB", {})
    r.check("FF00FF00 is registered as explicitly NOT a bucket",
            GREEN in nonb,
            "without an entry it is an unknown colour and flags every import, "
            "which is how the review list becomes noise nobody reads")
    r.check("and it is not ALSO in the bucket table", GREEN not in have,
            "the second table's section headers would become live projects")
    r.check("the never-a-bucket entry says what the colour is",
            bool(str(nonb.get(GREEN, "")).strip()),
            "a bare colour code in a suppression list is unmaintainable")

    # A label read from the sheet must never be committed to source. On the
    # real workbook these name people and this repo is public.
    src = (crm / "pipeline" / "normalize.py").read_text()
    r.check("no bucket LABEL is hardcoded in the importer",
            "tracker_buckets.json" in src
            and not any(w in src for w in ("action_admin\":", "= \"Waiting")),
            "the labels are read from the legend at import; a hardcoded one "
            "both leaks a name and stops following a retitled bucket")

    # ---- the import, against a real workbook with real fills ----------------
    import openpyxl  # noqa: F401 -- see test_importer.py on why this is bare
    tmp = Path(tempfile.mkdtemp(prefix="crmlt-"))
    try:
        err, load = _import(nrm, crm, tmp, "full")
        r.check("the import runs to completion", err is None, err or "")
        if err is not None:
            return r

        buckets = load("tracker_buckets")
        unlinked = load("tracker_unlinked")
        projects = load("projects")
        shipments = load("shipments")
        review = load("needs_review")
        by_no = {str(p.get("project_no")): p for p in (projects or [])}

        r.check("tracker_buckets.json is written", isinstance(buckets, list),
                "the view falls back to raw keys and the screen names nobody")
        r.check("tracker_unlinked.json is written", isinstance(unlinked, list))
        if buckets is None or unlinked is None:
            return r

        # ---- the legend, found by structure -------------------------------
        r.section("the legend is anchored on the last keyed row, not on colour")
        labels = {b.get("key"): b.get("label") for b in buckets}
        r.check("the magenta bucket takes its name from the legend",
                labels.get("action_admin") == L_ADMIN,
                f"got {labels.get('action_admin')!r}")
        r.check("the yellow bucket takes its name from the legend",
                labels.get("action_owner") == L_OWNER,
                f"got {labels.get('action_owner')!r}")
        r.check("the cyan bucket takes its name from the legend",
                labels.get("awaiting_materials") == L_AWAIT,
                f"got {labels.get('awaiting_materials')!r}")
        r.check("exactly three buckets are produced", len(buckets) == 3,
                f"got {[b.get('key') for b in buckets]}")
        rows = {b.get("key"): b.get("legend_row") for b in buckets}
        r.check("each bucket records which legend row named it",
                rows == {"action_admin": 11, "action_owner": 12,
                         "awaiting_materials": 13},
                f"got {rows} -- expected the three rows BELOW the last keyed "
                f"row (9), not the coloured data rows above it")

        # The trap, stated as its own assertion: row 7 is cyan, above the
        # boundary, and carries text in the notes column. A colour-anchored
        # scan names the cyan bucket after it.
        r.check("a coloured DATA row above the boundary is not read as legend",
                labels.get("awaiting_materials") != "No number on this one yet",
                "row 8 is a real unkeyed job, cyan, with a note. Scanning for "
                "colour finds it first and the sheet's actual legend then gets "
                "imported as live work")

        # ...and the other half of the same bug: the footer must not become work.
        pnos = set(by_no)
        r.check("no legend row was imported as a project",
                not (pnos & {L_ADMIN, L_OWNER, L_AWAIT}),
                f"project keys were {sorted(pnos)}")
        notes_seen = {str(p.get("open_orders_notes")) for p in projects}
        r.check("no legend label ended up as a project's note",
                not (notes_seen & {L_ADMIN, L_OWNER, L_AWAIT}),
                "the five footer rows were swept into the live list once")
        r.check("the second table's header row is not a project",
                "CLIENT INVOICES BELOW" not in pnos and
                "CLIENT INVOICES BELOW" not in notes_seen)

        # ---- decoding a bucket off a fill ---------------------------------
        r.section("status comes off the fill colour")
        r.check("a magenta row is action_admin",
                by_no.get("5001", {}).get("tracker_status") == "action_admin",
                f"got {by_no.get('5001', {}).get('tracker_status')!r}")
        r.check("a yellow row is action_owner",
                by_no.get("5002", {}).get("tracker_status") == "action_owner",
                f"got {by_no.get('5002', {}).get('tracker_status')!r}")
        r.check("a cyan row is awaiting_materials",
                by_no.get("5003", {}).get("tracker_status") == "awaiting_materials",
                f"got {by_no.get('5003', {}).get('tracker_status')!r}")
        r.check("the row it came from is recorded",
                by_no.get("5001", {}).get("tracker_row") == 2,
                f"got {by_no.get('5001', {}).get('tracker_row')!r} -- without "
                f"it a review entry cannot be looked up in the sheet")

        # ---- an unknown colour is never guessed ----------------------------
        r.section("an unrecognised fill is flagged, not guessed")
        r.check("an unknown ARGB leaves the status unset",
                by_no.get("5004", {}).get("tracker_status") is None,
                f"got {by_no.get('5004', {}).get('tracker_status')!r} -- "
                f"nearest-colour matching files a job under the wrong person")
        unk = [x for x in review
               if x.get("type") == "tracker_unknown_status_colour"]
        r.check("exactly one unknown-colour entry is raised", len(unk) == 1,
                f"got {len(unk)}: {[x.get('sheet_row') for x in unk]}")
        if unk:
            r.check("it names the ARGB it could not decode",
                    UNKNOWN in str(unk[0].get("detail", "")),
                    f"got {unk[0].get('detail')!r}")
            r.check("and the row and sheet to look it up in",
                    unk[0].get("sheet_row") == 5
                    and unk[0].get("sheet") == "Project Tracker",
                    f"got row {unk[0].get('sheet_row')!r} "
                    f"sheet {unk[0].get('sheet')!r}")

        r.section("FF00FF00 is never a bucket and never a complaint")
        r.check("a green row gets no status",
                by_no.get("5005", {}).get("tracker_status") is None,
                f"got {by_no.get('5005', {}).get('tracker_status')!r}")
        r.check("and raises NO unknown-colour flag",
                all(x.get("sheet_row") != 6 for x in unk),
                "one flag per import per green row is what buries the real ones")
        r.check("green produced no bucket to group under",
                all(b.get("argb") != GREEN for b in buckets),
                f"got {[b.get('argb') for b in buckets]}")

        r.check("a complete legend raises no missing-legend flag",
                not [x for x in review
                     if x.get("type") == "tracker_legend_missing"],
                "this fixture has all three legend rows; a flag here means the "
                "scan is not finding them and every label check above is "
                "passing for some other reason")

        # ---- the note is a property of the row -----------------------------
        r.section("the note belongs to the project, not to each leg")
        r.check("a project with NO vendor legs still carries its note",
                by_no.get("5002", {}).get("open_orders_notes") == NOTE_NO_LEGS,
                f"got {by_no.get('5002', {}).get('open_orders_notes')!r} -- on "
                f"the shipment this note had nowhere to live at all")
        legs_5002 = [s for s in shipments if str(s.get("project_no")) == "5002"]
        r.check("and that project really has no legs", len(legs_5002) == 0,
                f"got {len(legs_5002)} -- the check above would be trivial")
        r.check("a project with five legs carries ONE note",
                by_no.get("5003", {}).get("open_orders_notes") == NOTE_FIVE_LEGS,
                f"got {by_no.get('5003', {}).get('open_orders_notes')!r}")
        legs_5003 = [s for s in shipments if str(s.get("project_no")) == "5003"]
        r.check("the five-leg row really has five legs", len(legs_5003) == 5,
                f"got {len(legs_5003)} -- if the U/V pair is dropped this is 4, "
                f"and the busiest live row loses a vendor with no error")
        r.check("the leg in column U/V is imported",
                any(s.get("vendor_po_raw") == "VPO-U8" for s in legs_5003),
                f"got {[s.get('vendor_po_raw') for s in legs_5003]} -- the old "
                f"bound stopped at S/T")
        r.check("the note is read from the notes column",
                by_no.get("5001", {}).get("open_orders_notes") == "On the bench",
                "this check was once labelled as covering the EMPTY-cell case "
                "while asserting a non-empty one, so the `if clean(cells[5])` "
                "branch had no coverage at all -- 5006 below is the real case")
        r.check("a row whose notes cell IS empty gets no note",
                by_no.get("5006", {}).get("open_orders_notes") in (None, ""),
                f"got {by_no.get('5006', {}).get('open_orders_notes')!r} -- an "
                f"empty cell must not write an empty string over anything")
        r.check("and still gets its status, which is the fill not the text",
                by_no.get("5006", {}).get("tracker_status") == "action_owner",
                f"got {by_no.get('5006', {}).get('tracker_status')!r}")

        # ---- unlinked rows: shown, never invented --------------------------
        r.section("a row that cannot be matched is kept whole, not keyed")
        by_row = {u.get("sheet_row"): u for u in unlinked}
        r.check("exactly two rows are unlinked", len(unlinked) == 2,
                f"got rows {sorted(by_row)} -- expected 8 (no number) and "
                f"9 (no matching project)")
        u7, u8 = by_row.get(8), by_row.get(9)
        r.check("the row with no project number is kept", u7 is not None)
        r.check("the row keyed to nothing in the deal log is kept",
                u8 is not None)
        if u7:
            r.check("it says WHY it is unlinked",
                    u7.get("reason") == "no project number",
                    f"got {u7.get('reason')!r}")
            r.check("its client survives", u7.get("client") == "Meridian Corp",
                    f"got {u7.get('client')!r}")
            r.check("its note survives in full",
                    u7.get("open_orders_notes") == "No number on this one yet",
                    f"got {u7.get('open_orders_notes')!r}")
            r.check("its status bucket survives",
                    u7.get("tracker_status") == "awaiting_materials",
                    f"got {u7.get('tracker_status')!r} -- it is cyan on the "
                    f"sheet and the screen groups it by that")
            r.check("its vendor legs survive",
                    [l.get("vendor_po_raw") for l in u7.get("legs", [])]
                    == ["VPO-M1"],
                    f"got {u7.get('legs')!r}")
        if u8:
            r.check("the unmatched-key row says why",
                    u8.get("reason") == "no matching project",
                    f"got {u8.get('reason')!r}")
            r.check("it carries the PARSED key merge matches on",
                    u8.get("parsed_keys") == ["5999"],
                    f"got {u8.get('parsed_keys')!r} -- without this the merge "
                    f"falls back to the display string, which for a numeric "
                    f"key cell is '5999.0' and matches no project")
            r.check("and keeps the key the sheet actually carried",
                    str(u8.get("raw_key")) == "5999",
                    f"got {u8.get('raw_key')!r} -- he needs to recognise the "
                    f"row when he gives it a real number")
        r.check("NO synthetic project key was minted for either",
                "5999" not in pnos and len(projects) == 6,
                f"project keys were {sorted(pnos)} -- an invented key silently "
                f"mis-attaches the next edit made against it")
        r.check("both rows are ALSO named in the review list",
                len([x for x in review if x.get("type") in
                     ("open_order_row_without_project",
                      "tracker_row_without_matching_project")]) == 2,
                "the screen shows them; the review list is what he reads when "
                "he is not on that screen")

        # ---- a bucket the legend never names -------------------------------
        # Only its NAME is missing. The projects still have to group under it,
        # and the importer has to say the name is missing rather than drop the
        # bucket -- a dropped bucket takes its live projects off the screen.
        r.section("every unlinked row carries a fingerprint, from ONE producer")
        # The fingerprint is what a dismissal is scoped to. It is built HERE,
        # by the importer that produces the row, and read everywhere else --
        # merge sweeps on it, the server validates against it, the view sends
        # it back untouched. A second implementation anywhere is a second parse
        # to disagree with, which is the ".0" bug the old matcher carried.
        fp = getattr(nrm, "unlinked_fingerprint", None)
        r.check("normalize exposes the fingerprint function",
                callable(fp), "nothing else may compute one")
        if callable(fp):
            base = {"sheet_row": 8, "client": "Ironvale", "raw_key": "1419",
                    "start_date": "2026-01-05", "open_orders_notes": "live",
                    "legs": [{"vendor_po_raw": "PO-1", "ship_date": "2026-02-01"}]}
            r.check("it is stable for identical content",
                    fp(dict(base)) == fp(dict(base)))
            r.check("and it does NOT move when the row moves",
                    fp(dict(base, sheet_row=41)) == fp(dict(base)),
                    "rows shift week to week; a dismissal that dies on a "
                    "reordering resurrects everything every import")
            for field, val in (("client", "Ironvale Supply Co"),
                               ("open_orders_notes", "changed"),
                               ("raw_key", "1420"),
                               ("start_date", "2026-01-06")):
                r.check(f"and it DOES move when {field} changes",
                        fp(dict(base, **{field: val})) != fp(dict(base)),
                        "a material edit must offer the row again rather than "
                        "leave it hidden on a decision about different text")
            r.check("and it moves when a vendor leg changes",
                    fp(dict(base, legs=[{"vendor_po_raw": "PO-2",
                                         "ship_date": "2026-02-01"}])) != fp(dict(base)))
            r.check("it is a short hex string, not the row itself",
                    isinstance(fp(dict(base)), str) and 12 <= len(fp(dict(base))) <= 64
                    and all(c in "0123456789abcdef" for c in fp(dict(base))),
                    f"got {fp(dict(base))!r} -- it travels through the page and "
                    f"back, so it must carry no customer text")

        r.section("two rows the operator cannot tell apart still dismiss apart")
        # THE COLLISION. The fingerprint is content, and sheet_row is excluded
        # so a reordering does not resurrect every dismissal. That means two
        # rows whose every visible field is identical hash the same, and ONE
        # dismissal retired BOTH -- one of them live work, hidden, with its
        # note and legs rendered nowhere.
        #
        # The fix is NOT to make the fingerprint stickier (sheet_row back in);
        # that is the matcher tuning this release removes. It is to make it
        # DISCRIMINATING: among rows sharing a payload, an occurrence ordinal
        # in sheet order. Identical rows are interchangeable to the operator,
        # so "the first of them" is a meaningful thing to dismiss.
        stamp = getattr(nrm, "stamp_fingerprints", None)
        r.check("normalize exposes the row-list stamper",
                callable(stamp),
                "the ordinal cannot be computed one row at a time")
        if callable(stamp):
            twin = {"sheet_row": 8, "client": "Meridian Corp", "legs": [],
                    "open_orders_notes": "", "raw_key": ""}
            out = stamp([dict(twin), dict(twin, sheet_row=9),
                         dict(twin, client="Other")])
            # IDENTICAL ROWS ARE ONE DECISION, and the card says so.
            #
            # sheet_row is excluded so a reordering does not resurrect every
            # dismissal, which means two rows identical on every field the card
            # shows hash the same. That is not a defect to engineer around: the
            # operator cannot tell them apart either, so they are one decision
            # and one click clears both.
            #
            # Two attempts to engineer around it were both worse. An occurrence
            # ORDINAL gave them distinct handles, but the handle depended on
            # which OTHER rows were present, so it re-bound when the population
            # changed and walked a dismissal onto a row nobody had adopted.
            # REFUSING to fingerprint them left an undismissable card instead.
            r.check("identical rows share one fingerprint",
                    out[0]["fingerprint"] == out[1]["fingerprint"],
                    f"got {[x.get('fingerprint') for x in out]}")
            r.check("and the row SAYS how many it speaks for",
                    out[0].get("shares_fingerprint") == 2
                    and out[1].get("shares_fingerprint") == 2,
                    f"got {out} -- one click clearing two cards has to be said "
                    f"on the card, or it reads as a bug")
            r.check("a row with no twin says nothing extra",
                    isinstance(out[2].get("fingerprint"), str)
                    and "shares_fingerprint" not in out[2], f"got {out[2]}")
            moved = stamp([dict(twin, sheet_row=41), dict(twin, client="Other"),
                           dict(twin, sheet_row=42)])
            r.check("and none of it depends on position",
                    [x.get("shares_fingerprint") for x in moved] == [2, None, 2]
                    and moved[1]["fingerprint"] == out[2]["fingerprint"],
                    f"got {[(x.get('fingerprint'), x.get('shares_fingerprint')) for x in moved]}"
                    f" -- a fingerprint must be a function of its own row only")
            # The payload has to cover what actually distinguishes rows.
            r.check("the bucket the row sits in is part of its identity",
                    fp(dict(twin, tracker_status="action_admin"))
                    != fp(dict(twin, tracker_status="awaiting_materials")),
                    "two rows in different buckets are not the same row")
            r.check("and so is why it could not be matched",
                    fp(dict(twin, reason="no project number"))
                    != fp(dict(twin, reason="no matching project")),
                    "a keyless row and an unmatched-key row are different rows")

        r.section("a bucket with no legend row still groups")
        err2, load2 = _import(nrm, crm, tmp, "nolegend",
                              legend=(L_ADMIN, L_OWNER, None))
        r.check("the import survives a legend row with no text", err2 is None,
                err2 or "")
        if err2 is None:
            b2 = load2("tracker_buckets") or []
            k2 = {b.get("key"): b for b in b2}
            r.check("the unnamed bucket is still present",
                    "awaiting_materials" in k2,
                    f"got {sorted(k2)} -- dropping it takes its live projects "
                    f"off the screen entirely")
            r.check("with no invented name",
                    k2.get("awaiting_materials", {}).get("label") is None,
                    f"got {k2.get('awaiting_materials', {}).get('label')!r}")
            r.check("and the two named ones keep their names",
                    k2.get("action_admin", {}).get("label") == L_ADMIN
                    and k2.get("action_owner", {}).get("label") == L_OWNER)
            miss = [x for x in (load2("needs_review") or [])
                    if x.get("type") == "tracker_legend_missing"]
            r.check("the missing legend is reported once", len(miss) == 1,
                    f"got {len(miss)}")
            if miss:
                r.check("and names the colour that has no label",
                        CYAN in str(miss[0].get("detail", "")),
                        f"got {miss[0].get('detail')!r}")
            p2 = {str(p.get("project_no")): p for p in (load2("projects") or [])}
            r.check("its projects still carry the bucket key",
                    p2.get("5003", {}).get("tracker_status")
                    == "awaiting_materials",
                    f"got {p2.get('5003', {}).get('tracker_status')!r}")

        # ---- the boundary, in the direction the trap row does not cover ----
        #
        # Row 7 above proves a coloured DATA row cannot be mistaken for the
        # legend. These prove the other two things the boundary must not do:
        # swallow a real row that happens to sit below it, and be moved by
        # something that is not a data row at all.
        r.section("the boundary skips footer rows without eating data")
        err3, load3 = _import_edge(nrm, crm, tmp, "trailing",
                                   trailing_unkeyed=True)
        r.check("the import survives a trailing unkeyed row", err3 is None,
                err3 or "")
        if err3 is None:
            u3 = load3("tracker_unlinked") or []
            rv3 = load3("needs_review") or []
            r.check("a real unkeyed job BELOW the boundary is still rescued",
                    [x.get("sheet_row") for x in u3] == [5],
                    f"got rows {[x.get('sheet_row') for x in u3]} -- appending "
                    f"a job at the bottom before it has a number is the normal "
                    f"way a row gets added, and it was being dropped in total "
                    f"silence: no review entry, no card, note and legs gone")
            r.check("and it is flagged as well as shown",
                    any(x.get("type") == "open_order_row_without_project"
                        and x.get("sheet_row") == 5 for x in rv3),
                    "before this feature existed the row was flagged wherever "
                    "it sat; the boundary made the importer quieter about real "
                    "data than it used to be")
            r.check("its legs come with it",
                    bool(u3) and [l.get("vendor_po_raw")
                                  for l in u3[0].get("legs", [])] == ["VPO-N1"],
                    f"got {u3[:1]}")
            r.check("the legend rows are still NOT rescued as work",
                    not ({L_ADMIN, L_OWNER, L_AWAIT} &
                         {x.get("open_orders_notes") for x in u3}),
                    "a footer row carries nothing but a notes cell; that is "
                    "what makes it a footer row rather than its position")
            b3 = {b.get("key"): b.get("label") for b in (load3("tracker_buckets") or [])}
            r.check("and the legend is still read",
                    b3.get("action_admin") == L_ADMIN, f"got {b3}")

        err4, load4 = _import_edge(nrm, crm, tmp, "stray", stray_col_a=True)
        r.check("the import survives a stray value under the legend",
                err4 is None, err4 or "")
        if err4 is None:
            b4 = {b.get("key"): b.get("label") for b in (load4("tracker_buckets") or [])}
            r.check("a column-A-only row below the legend does not move the "
                    "boundary",
                    b4 == {"action_admin": L_ADMIN, "action_owner": L_OWNER,
                           "awaiting_materials": L_AWAIT},
                    f"got {b4} -- a date stamp, a TOTAL, or the text of a "
                    f"merged footer comment all land in column A, and any one "
                    f"of them used to blank all three bucket names")
            u4 = load4("tracker_unlinked") or []
            r.check("and does not turn the legend into adoptable cards",
                    not ({L_ADMIN, L_OWNER, L_AWAIT} &
                         {x.get("open_orders_notes") for x in u4}),
                    f"got {[x.get('open_orders_notes') for x in u4]} -- these "
                    f"render with an 'Add to CRM' button on the operator's own "
                    f"legend text")
            r.check("no missing-legend flags either",
                    not [x for x in (load4("needs_review") or [])
                         if x.get("type") == "tracker_legend_missing"])

        # ---- a fill that is there but cannot be read -----------------------
        r.section("an unreadable fill is flagged, not treated as no fill")
        err5, load5 = _import_edge(nrm, crm, tmp, "theme", theme_row=True,
                                   default_fill_row=True)
        r.check("the import survives a theme fill", err5 is None, err5 or "")
        if err5 is None:
            p5 = {str(p.get("project_no")): p for p in (load5("projects") or [])}
            rv5 = [x for x in (load5("needs_review") or [])
                   if x.get("type") == "tracker_unknown_status_colour"]
            r.check("a theme-coloured row gets no guessed bucket",
                    p5.get("6002", {}).get("tracker_status") is None,
                    f"got {p5.get('6002', {}).get('tracker_status')!r}")
            r.check("but it IS reported, naming the row",
                    any(x.get("sheet_row") == 3 for x in rv5),
                    f"got {[x.get('sheet_row') for x in rv5]} -- a theme colour "
                    f"made .rgb return a descriptor rather than a string, the "
                    f"row was dropped from the fills map, and the project then "
                    f"vanished off the Live screen with nothing said anywhere")
            r.check("the entry says the colour could not be read, not that it "
                    "was unrecognised",
                    any("theme" in str(x.get("detail", "")) for x in rv5),
                    f"got {[x.get('detail') for x in rv5]}")
            r.check("a solid fill with no foreground colour is NOT reported",
                    not any(x.get("sheet_row") == 4 for x in rv5),
                    "'00000000' is the default, i.e. no colour -- reporting it "
                    "puts an entry in the review list on every single import")
            r.check("and gets no bucket either",
                    p5.get("6003", {}).get("tracker_status") is None,
                    f"got {p5.get('6003', {}).get('tracker_status')!r}")

        err6, load6 = _import_edge(nrm, crm, tmp, "bodyless",
                                   keyed_bodyless_unknown=True)
        r.check("the import survives a keyed row with nothing else on it",
                err6 is None, err6 or "")
        if err6 is None:
            rv6 = [x for x in (load6("needs_review") or [])
                   if x.get("type") == "tracker_unknown_status_colour"]
            r.check("a keyed row below the boundary still gets its colour flag",
                    any(x.get("sheet_row") == 5 for x in rv6),
                    f"got rows {[x.get('sheet_row') for x in rv6]} -- a row "
                    f"with a key is a data row wherever it sits; tying the flag "
                    f"to the boundary lost the status AND any mention of it")

        err7, load7 = _import_edge(nrm, crm, tmp, "strayleg",
                                   footer_stray_leg=True)
        r.check("the import survives a footer line with a stray cell",
                err7 is None, err7 or "")
        if err7 is None:
            u7b = load7("tracker_unlinked") or []
            r.check("one stray cell in a footer line is not a vendor leg",
                    not any("Colour key updated" in str(x.get("open_orders_notes"))
                            for x in u7b),
                    f"got {u7b!r} -- it renders as a phantom project carrying "
                    f"an invented leg, with an 'Add to CRM' button on it")
            b7 = {b.get("key"): b.get("label") for b in (load7("tracker_buckets") or [])}
            r.check("and it does not move the boundary either",
                    b7.get("action_admin") == L_ADMIN, f"got {b7}")

        err8, load8 = _import_edge(nrm, crm, tmp, "legendfill",
                                   legend_unreadable=True)
        r.check("the import survives an unreadable legend fill", err8 is None,
                err8 or "")
        if err8 is None:
            rv8 = load8("needs_review") or []
            unread = [x for x in rv8
                      if x.get("type") == "tracker_legend_unreadable_colour"]
            r.check("an unreadable fill on a legend row says so",
                    len(unread) == 1,
                    f"got {[x.get('type') for x in rv8]} -- otherwise the row "
                    f"falls through to 'no legend row found for the FFFF00FF "
                    f"bucket', pointing him at a row that is right there")
            if unread:
                r.check("and names the legend text it could not colour-match",
                        L_ADMIN in str(unread[0].get("detail", "")),
                        f"got {unread[0].get('detail')!r}")

        # ---- the regeneration interlock ------------------------------------
        # Both files are the importer's reading of THIS run. Merging them by key
        # would resurrect a row he has already adopted into the CRM.
        r.section("the rows the importer writes carry their fingerprint")
        _e1, _l1 = _import_edge(nrm, crm, tmp, "fp-a", trailing_unkeyed=True)
        _u = _l1("tracker_unlinked") or []
        r.check("every unlinked row the importer wrote has one",
                bool(_u) and all(x.get("fingerprint") for x in _u),
                f"got {[x.get('fingerprint') for x in _u]} -- a row with no "
                f"fingerprint can never be dismissed, and the button must not "
                f"be offered on it")
        _e2, _l2 = _import_edge(nrm, crm, tmp, "fp-b", trailing_unkeyed=True)
        r.check("and the same workbook produces the same ones",
                [x.get("fingerprint") for x in (_l2("tracker_unlinked") or [])]
                == [x.get("fingerprint") for x in _u],
                "an unstable fingerprint un-dismisses everything every import")

        r.section("--replace does not leave the dismissal table unswept")
        # merge_all runs only in merge mode, so under --replace nothing swept
        # and dismiss_tracker_row kept appending: the table grew past the
        # sheet it is supposed to be a subset of. That is the unbounded
        # accumulation this whole release removes, reappearing on the one path
        # nobody looked at.
        _e, _l = _import_edge(nrm, crm, tmp, "repl-a", trailing_unkeyed=True)
        _rows = _l("tracker_unlinked") or []
        _sdir = tmp / "store-repl-a"
        (_sdir / "tracker_dismissed.json").write_text(json.dumps(
            [{"fingerprint": "not-on-any-sheet-1", "reason": "not_a_job"},
             {"fingerprint": "not-on-any-sheet-2", "reason": "not_a_job"}]))
        nrm.run(str(tmp / "repl-a.xlsx"), str(_sdir), force=True, mode="replace")
        left = json.loads((_sdir / "tracker_dismissed.json").read_text())
        r.check("a --replace import sweeps dismissals like a merge does",
                left == [],
                f"got {left} -- neither of those fingerprints is on the sheet; "
                f"left unswept the table grows without bound, which is the "
                f"exact property this design claims is structural")

        r.section("both tracker files are regenerated, never merged")
        mg = (crm / "pipeline" / "merge.py").read_text()
        regen = mg.split("REGENERATED", 1)[-1].split("\n\n", 1)[0]
        r.check("tracker_unlinked.json is regenerated wholesale",
                "tracker_unlinked.json" in regen,
                "merged by key, a row adopted into the CRM comes back as an "
                "unadopted card on the next import")
        r.check("tracker_buckets.json is regenerated wholesale",
                "tracker_buckets.json" in regen,
                "a bucket he renamed in the sheet would keep its old label")

        # ---- re-import, where the tracker meets the operator's own work ----
        _merge_checks(r, crm, tmp)

        # ---- the fields have to be writable through the server -------------
        r.section("the new project fields are accepted by the write path")
        pf = getattr(server, "PROJECT_FIELDS", None) if server else None
        if pf is None:
            src_srv = (crm / "mcp" / "server.py").read_text()
            pf = set()
            for f in ("tracker_status", "open_orders_notes", "tracker_row"):
                if f'"{f}"' in src_srv:
                    pf.add(f)
        for f in ("tracker_status", "open_orders_notes", "tracker_row"):
            r.check(f"{f} is a writable project field", f in pf,
                    "adoption writes it through create_project; a field the "
                    "validator does not know is dropped on the floor")

        # ---- tracker_status is an enum, and every sibling enum is checked --
        #
        # It was the fourth state field on a project and the only one with no
        # validation. A value no bucket knows about left the project counted in
        # the header's "N active", rendered in no section, and still listed in
        # the sidebar -- a live job off the daily board with nothing said.
        r.section("tracker_status is validated like every other state field")
        keys = getattr(nrm, "TRACKER_BUCKET_KEYS", None) \
            or set(getattr(nrm, "BUCKET_BY_ARGB", {}).values())
        srv_keys = getattr(server, "TRACKER_STATUSES", None) if server else None
        if srv_keys is None:
            # The mutation runner calls run(None, crm_dir) -- there is no
            # imported server object there, so read the constant out of the
            # source. Without this the module fails at BASELINE and every
            # mutant result against server.py is a false positive.
            m = re.search(r"^TRACKER_STATUSES\s*=\s*\{([^}]*)\}",
                          (crm / "mcp" / "server.py").read_text(), re.M)
            if m:
                srv_keys = set(re.findall(r'"([^"]+)"', m.group(1)))
        if srv_keys is None:
            r.check("the server knows the bucket keys", False,
                    "no TRACKER_STATUSES -- nothing constrains the field")
        else:
            r.check("the server's bucket keys match the importer's",
                    set(srv_keys) == set(keys),
                    f"server {sorted(srv_keys)} vs importer {sorted(keys)} -- a "
                    f"key accepted by one and unknown to the other renders a "
                    f"live project into no section at all")
        # Load the server from THIS crm dir rather than using the one passed
        # in: the mutation runner calls run(None, crm_dir), so gating on the
        # argument meant every mutant of the validation itself survived while
        # only the constant was ever checked.
        from lib.harness import (Store, company, invoice, load_server,
                                 project, shipment)
        srv = server
        if srv is None:
            try:
                srv = load_server(str(crm))
            except Exception as exc:                          # noqa: BLE001
                r.check("the server module imports", False,
                        f"{type(exc).__name__}: {exc}")
        if srv is not None:
            st = Store(srv)
            st.reset(companies=[company()], projects=[project("4521")])
            ok = st.call("update_project", project_no="4521",
                         fields={"tracker_status": "action_admin"})
            r.check("a real bucket key is accepted", ok.get("ok") is True,
                    f"got {ok}")
            for bad in ("done", " action_admin", "Action Admin",
                        "awaiting_material", 5):
                res = st.call("update_project", project_no="4521",
                              fields={"tracker_status": bad})
                r.check(f"tracker_status {bad!r} is refused",
                        res.get("ok") is False and "_raised" not in res,
                        f"got {res} -- accepted, so the project is counted as "
                        f"live and rendered in no bucket")
            r.section("dismissing a tracker row, server side")
            ROW = {"sheet_row": 8, "reason": "no matching project",
                   "raw_key": "1419", "client": "Ironvale Supply",
                   "open_orders_notes": "live job", "legs": [],
                   "fingerprint": "aaaaaaaaaaaaaaaa"}
            OTHER = {"sheet_row": 9, "reason": "no project number",
                     "client": "Meridian", "open_orders_notes": "x", "legs": [],
                     "fingerprint": "bbbbbbbbbbbbbbbb"}

            def read_dis():
                f = st.path / "tracker_dismissed.json"
                if not f.exists():
                    return []
                try:
                    return json.loads(f.read_text())
                except Exception:                            # noqa: BLE001
                    return []

            def seed(rows):
                st.reset(companies=[company()], projects=[])
                (st.path / "tracker_unlinked.json").write_text(json.dumps(rows))
                st.rebind()

            seed([dict(ROW), dict(OTHER)])
            res = st.call("dismiss_tracker_row",
                          fingerprint="aaaaaaaaaaaaaaaa", reason="not_a_job")
            r.check("a dismissal is accepted", res.get("ok") is True, f"got {res}")
            dis = read_dis()
            r.check("and written to the store",
                    [d.get("fingerprint") for d in dis] == ["aaaaaaaaaaaaaaaa"],
                    f"got {dis}")
            r.check("with the reason recorded",
                    bool(dis) and dis[0].get("reason") == "not_a_job", f"got {dis}")

            tk = st.call("list_tracker")
            flags = {u.get("sheet_row"): bool(u.get("dismissed"))
                     for u in tk.get("tracker_unlinked") or []}
            r.check("list_tracker marks it dismissed without deleting it",
                    flags == {8: True, 9: False},
                    f"got {flags} -- the screen has to be able to show a count")

            # THE WRITE-SIDE BOUND. A fingerprint that is not on the current
            # sheet cannot be dismissed. With the import sweep this bounds the
            # table at BOTH ends, and a forged or stale value fails closed
            # instead of hiding some arbitrary row.
            res = st.call("dismiss_tracker_row", fingerprint="zzzzzzzzzzzzzzzz")
            r.check("a fingerprint not on the current sheet is REFUSED",
                    res.get("ok") is False,
                    f"got {res} -- unchecked, this writes a dismissal that "
                    f"nothing can sweep and that may match a future row")
            r.check("and the refusal names why",
                    "not on the current" in str(res.get("error", "")).lower()
                    or "no such" in str(res.get("error", "")).lower(),
                    f"got {res.get('error')!r}")

            res = st.call("restore_tracker_row", fingerprint="aaaaaaaaaaaaaaaa")
            r.check("a dismissal can be undone", res.get("ok") is True, f"got {res}")
            r.check("and the row comes back",
                    read_dis() == [],
                    "an undo that leaves the record is not an undo")

            # RETIRED with the tool. adopt_tracker_row created the project
            # and wrote the dismissal that retired its row under one lock. It
            # is gone: by_key retires an adopted row on the next import,
            # because the sheet's number is now a project's number. The two
            # halves it existed to keep together no longer exist -- there is
            # only the project create, which create_project already does.
            #
            # Its atomicity could not be delivered anyway. The lock does not
            # make a save() and a save_side() one transaction, and reporting
            # ok:false when the second failed put a project on disk under a
            # message saying nothing was written.
            r.section("the new writes are as hardened as every other write")
            src = (crm / "mcp" / "server.py").read_text()
            body = src.split("def save_side", 1)[-1].split("\n    def ", 1)[0]
            # after the docstring: the docstring NAMES os.replace to explain
            # why it is gone, and a check that reads its own explanation as
            # the defect is measuring the comment, not the code.
            body = body.split('"""')[-1]
            r.check("save_side goes through _write, not its own os.replace",
                    "self._write(" in body and "os.replace" not in body,
                    f"got:\n{body[:300]}\n-- _write carries the retry/backoff "
                    f"for the Windows case where OneDrive holds the target "
                    f"open, the StoreError translation, and a .~*.tmp name the "
                    f"startup sweep collects. A hand-rolled copy has none.")

            r.section("a dismissal is written to history, and never read back")
            seed([dict(ROW), dict(OTHER)])
            st.call("dismiss_tracker_row", fingerprint="aaaaaaaaaaaaaaaa",
                    reason="already_adopted")
            log = (st.path / "changelog.jsonl")
            entries = [json.loads(l) for l in log.read_text().splitlines()
                       if l.strip()] if log.exists() else []
            r.check("the dismissal is in the changelog",
                    any(e.get("entity") == "tracker_row" for e in entries),
                    f"got {entries} -- months from now 'why is that row not on "
                    f"the list' has to have an answer")
            src = (crm / "mcp" / "server.py").read_text() \
                + (crm / "pipeline" / "merge.py").read_text()
            r.check("and NOTHING reads the changelog to decide what is hidden",
                    "tracker_row" not in src.split("_entities_in_changelog", 1)[-1]
                    .split("def ", 1)[0],
                    "a log that decides what the screen shows is a second "
                    "authority beside tracker_dismissed.json, and the two "
                    "disagree the first time one is edited")

            r.section("list_tracker carries the reason to the card")
            seed([dict(ROW), dict(OTHER)])
            st.call("dismiss_tracker_row", fingerprint="aaaaaaaaaaaaaaaa",
                    reason="already_adopted")
            tk = st.call("list_tracker")
            got = {u.get("sheet_row"): u.get("reason_dismissed")
                   for u in tk.get("tracker_unlinked") or []}
            r.check("the dismissed row says WHY on the very next read",
                    got == {8: "already_adopted", 9: None},
                    f"got {got} -- the card reads it off the row, so without "
                    f"this every dismissal reads 'not a job'")

            # ---- moving a project must carry its legs ------------------
            #
            # rename_project cascades a number change and reassign_shipment
            # carries a leg to its new project's customer, but update_project
            # wrote company_id onto the project alone. The Live Tracker matches
            # legs on company AND number -- two customers can hold one number,
            # and one customer's leg must never surface on another's card -- so
            # after a move the card read "No vendor legs" and every lateness
            # flag on that job stopped firing, on the screen built to show them.
            st.reset(companies=[company(), company("mer", "Meridian Corp")],
                     projects=[project("4521", "acme",
                                       tracker_status="action_admin")],
                     shipments=[shipment("4521-L1", "4521", "acme"),
                                shipment("4521-L2", "4521", "acme")],
                     invoices=[invoice("7001", "acme", project_no="4521")])
            mv = st.call("update_project", project_no="4521",
                         fields={"company_id": "mer",
                                 "company_name": "Meridian Corp"})
            r.check("moving a project to another company succeeds",
                    mv.get("ok") is True, f"got {mv}")
            r.check("and reports how many legs went with it",
                    mv.get("shipments_moved") == 2,
                    f"got {mv.get('shipments_moved')!r}")
            moved = [x for x in (st.read("shipments") or [])
                     if x.get("company_id") == "mer"]
            r.check("both legs are filed under the new company",
                    len(moved) == 2,
                    f"got {[(x.get('shipment_id'), x.get('company_id')) for x in (st.read('shipments') or [])]}")
            r.check("the leg's client name follows too",
                    all(x.get("client_name") == "Meridian Corp" for x in moved),
                    f"got {[x.get('client_name') for x in moved]}")
            r.check("its invoice moves as well",
                    mv.get("invoices_moved") == 1
                    and all(i.get("company_id") == "mer"
                            for i in (st.read("invoices") or [])),
                    f"got {st.read('invoices')!r}")

            # a leg belonging to a DIFFERENT company that happens to share the
            # number must NOT be dragged along
            st.reset(companies=[company(), company("mer", "Meridian Corp"),
                                company("nor", "Northgate Tooling")],
                     projects=[project("4521", "acme")],
                     shipments=[shipment("4521-L1", "4521", "acme"),
                                shipment("x-4521-L1", "4521", "nor")])
            st.call("update_project", project_no="4521",
                    fields={"company_id": "mer"})
            other = [x for x in (st.read("shipments") or [])
                     if x.get("shipment_id") == "x-4521-L1"]
            r.check("another company's leg on the same number is left alone",
                    bool(other) and other[0].get("company_id") == "nor",
                    f"got {other!r} -- the same number can belong to two "
                    f"customers, which is why the match is on both")

            # an ordinary edit that does not move the project touches nothing
            st.reset(companies=[company()],
                     projects=[project("4521", "acme")],
                     shipments=[shipment("4521-L1", "4521", "acme")])
            plain = st.call("update_project", project_no="4521",
                            fields={"notes": "just a note"})
            r.check("an edit that does not move the project reports no move",
                    plain.get("ok") is True
                    and "shipments_moved" not in plain,
                    f"got {plain}")

            # ---- the tracker files must be readable at runtime ---------
            #
            # They are deliberately NOT in ENTITY_FILES -- that drives a
            # missing-file warning, and their absence is normal on any store
            # from before the tracker. So they need their own reader, or the
            # app can never refresh them and the Live screen's bucket headings
            # and unlinked section stay frozen at page-build time.
            st.reset(companies=[company()], projects=[project("4521")])
            (st.path / "tracker_buckets.json").write_text(json.dumps(
                [{"key": "action_admin", "label": "Office", "argb": "FFFF00FF"}]))
            (st.path / "tracker_unlinked.json").write_text(json.dumps(
                [{"sheet_row": 8, "raw_key": "1419", "client": "Ironvale"}]))
            st.rebind()
            tk = st.call("list_tracker")
            r.check("list_tracker returns the buckets", tk.get("ok") is True
                    and len(tk.get("tracker_buckets") or []) == 1, f"got {tk}")
            r.check("and the unlinked rows",
                    len(tk.get("tracker_unlinked") or []) == 1, f"got {tk}")
            st.reset(companies=[company()], projects=[project("4521")])
            tk = st.call("list_tracker")
            r.check("a store with no tracker files is not an error",
                    tk.get("ok") is True and tk.get("tracker_buckets") == []
                    and tk.get("tracker_unlinked") == [],
                    f"got {tk} -- absence is normal on any store seeded before "
                    f"the tracker shipped, and must not read as a broken store")
            (st.path / "tracker_unlinked.json").write_text("{}")
            st.rebind()
            tk = st.call("list_tracker")
            r.check("a tracker file of the wrong shape reads as empty",
                    tk.get("ok") is True and tk.get("tracker_unlinked") == [],
                    f"got {tk} -- the caller embeds this into a page that dies "
                    f"on the wrong type")
            (st.path / "tracker_unlinked.json").write_text("{ not json")
            st.rebind()
            tk = st.call("list_tracker")
            r.check("but a CORRUPT one is reported, not silently empty",
                    tk.get("ok") is False and "_raised" not in tk,
                    f"got {tk} -- a half-written OneDrive file is not an empty "
                    f"tracker")

            # One corrupt tracker file must not take the OTHER one down,
            # and the error must name WHICH file. Both loads shared a single
            # try, so a half-written tracker_buckets.json returned one
            # StoreError for the pair -- the good unlinked rows went with it,
            # and the message did not say which file was bad. crm_info two
            # tools away states the opposite rule for its own reads ("one
            # unreadable file reports as an error string for that entity
            # instead of taking down the whole health check"); this is that
            # rule applied where it was missing.
            st.reset(companies=[company()], projects=[project("4521")])
            (st.path / "tracker_buckets.json").write_text("{ not json")
            (st.path / "tracker_unlinked.json").write_text(json.dumps(
                [{"sheet_row": 8, "raw_key": "1419", "client": "Ironvale"}]))
            st.rebind()
            tk = st.call("list_tracker")
            r.check("a corrupt buckets file names the file that failed",
                    "tracker_buckets" in str(tk.get("problems") or tk.get("error") or ""),
                    f"got {tk} -- the operator cannot restore a file the error "
                    f"does not name")
            r.check("and does not discard the unlinked rows that read fine",
                    len(tk.get("tracker_unlinked") or []) == 1,
                    f"got {tk} -- one bad file took down a section whose own "
                    f"file was intact")
            r.check("while still reporting NOT ok", tk.get("ok") is False,
                    f"got {tk} -- the refresh must name list_tracker as stale "
                    f"rather than quietly showing a half-loaded tracker")

            # ---- tracker_key is a writable, text-coerced identifier ---------
            st.reset(companies=[company()], projects=[])
            mk = st.call("create_project", fields={
                "project_no": "1500", "company_id": "acme",
                "tracker_key": "Word Proposal", "status": "won"})
            r.check("a project can record the sheet key it was adopted from",
                    mk.get("ok") is True, f"got {mk}")
            r.check("and it is stored verbatim",
                    (st.read("projects") or [{}])[0].get("tracker_key")
                    == "Word Proposal",
                    f"got {(st.read('projects') or [{}])[0].get('tracker_key')!r}")
            st.reset(companies=[company()], projects=[])
            st.call("create_project", fields={
                "project_no": "1501", "company_id": "acme",
                "tracker_key": 1419.0, "status": "won"})
            r.check("a numeric sheet key is coerced to text like every other id",
                    (st.read("projects") or [{}])[0].get("tracker_key") == "1419",
                    f"got {(st.read('projects') or [{}])[0].get('tracker_key')!r} "
                    f"-- a float here would never match the string the importer "
                    f"writes into the unlinked row")

            st.reset(companies=[company()], projects=[project("4521")])
            res = st.call("update_project", project_no="4521",
                          fields={"tracker_status": None})
            r.check("clearing it back to unset is allowed",
                    res.get("ok") is True,
                    f"got {res} -- a row whose colour was removed in Excel has "
                    f"to be able to retire")
            shutil.rmtree(st.path, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r

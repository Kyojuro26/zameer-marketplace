"""The importer, end to end, against a real workbook.

Nothing in the suite built a workbook before this file, so every defect in
normalize.py's decisions was invisible: a gutted payment_words.py scored a
clean 180/180 while reading "hasn't paid" and "paid - check returned NSF" as
PAID. Grepping a module's source is not testing it.

These cases are the wording a small manufacturer actually types into a
collection-notes column. Both error directions cost money:
  reading an UNPAID note as paid  -> a live receivable drops off the list
  flagging a genuinely PAID one   -> he chases a customer who already paid,
                                     and the review list becomes noise
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import Result  # noqa: E402

# (note as it would appear in the workbook, must-be-collected?)
UNPAID = [
    "NOT PAID as of 7/1 - chasing", "NOT PAID IN FULL - 50% short",
    "Will be paid in full 8/30", "COD - paid on delivery",
    "Paid less freight, $340 still owed", "Was paid, then charged back",
    "We paid freight; invoice to client still open", "Paid $5,000 of $12,500",
    "paid in full? confirm with Sherry", "2 of 3 invoices paid",
    "paid 1st installment", "partially paid", "paid 50%", "hasn't paid",
    "still owes, paid nothing", "paid - check returned NSF",
    "paid deposit only, balance due 6/1", "paid, awaiting the rest",
    "paid? unsure", "will be paid net 60", "50% paid, balance due",
    "Never paid - write off", "paid - REVERSED",
    # every one of these was written off by a previous version of this module.
    # Three successive blacklists each shipped a gap at the NEXT spelling, which
    # is why the implementation is now a whitelist -- see payment_words.py.
    "Paid, $12,500 still outstanding", "Paid but balance outstanding",
    "Paid 3/1, $500 still due", "Paid after installation sign-off",
    "Part paid", "Paid before shipment", "Paid, balance $8,000",
    "Paid - amount due 5000", "Paid; outstanding items to bill",
    "Paid assuming the credit clears", "Paid less shipping",
    "paid short", "Paid, would clear next week", "Paid pending credit note",
]
PAID = [
    "Paid in full, balance $0", "paid - no balance due",
    "Paid, nothing outstanding", "Paid 6/1 check 8812", "paid in full",
    "PAID", "paid off", "Paid 5/2", "paid in full 3/14 ck 9912",
    "Paid $12,500", "paid via wire 6/1", "Paid 6/1, thanks",
    "PAID IN FULL", "paid ck #8812", "Paid 06/01/2026",
]
NO_MENTION = ["Open", "awaiting payment", "unpaid", "", "net 30"]

# a percentage next to a commission is a payout rate, never a collection status
COMMISSION = ["10% comm to D", "10% commission to D", "10% commissions to D",
              "10% comms to D", "10% cmsn to D", "10% to D", "15% for JS",
              "20% rep split"]
NOT_COMMISSION = ["50%", "25% deposit received", "10% for freight",
                  "2% discount", "50% collected"]


def _load(crm_dir, name):
    import importlib.util
    p = Path(crm_dir) / "pipeline" / name
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_imp_{name}", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(server, crm_dir=None):
    r = Result("importer", since="0.1.28")
    crm = Path(crm_dir) if crm_dir else \
        Path(__file__).resolve().parents[2] / "plugins/unrivaled-solutions/skills/crm"
    pw = _load(crm, "payment_words.py")
    nrm = _load(crm, "normalize.py")
    if pw is None:
        r.check("payment wording has a single definition", False,
                "pipeline/payment_words.py missing")
        return r

    r.section("an unpaid receivable is never recorded as collected")
    for note in UNPAID:
        r.check(f"not collected: {note!r}", pw.says_paid(note) is None,
                f"says_paid={pw.says_paid(note)!r} -- a live receivable would "
                f"drop off the collections list, unflagged")

    r.section("a genuinely paid one is not flagged as ambiguous")
    for note in PAID:
        r.check(f"collected: {note!r}", pw.says_paid(note) is True,
                f"says_paid={pw.says_paid(note)!r} -- the operator chases a "
                f"customer who has already paid, and the real flags get buried")

    r.section("no payment mentioned at all")
    for note in NO_MENTION:
        r.check(f"no mention: {note!r}", pw.says_paid(note) is False,
                f"says_paid={pw.says_paid(note)!r}")

    if nrm and hasattr(nrm, "commission_like"):
        r.section("a commission rate is never read as a collection percentage")
        for note in COMMISSION:
            r.check(f"commission: {note!r}", nrm.commission_like(note) is True,
                    "a rep's payout rate would be stored as percent collected")
        for note in NOT_COMMISSION:
            r.check(f"not commission: {note!r}",
                    nrm.commission_like(note) is False,
                    "a real collection percentage would be discarded")

    r.section("the importer mints unique shipment ids")
    if nrm:
        src = (crm / "pipeline" / "normalize.py").read_text()
        r.check("leg numbering does not restart per row",
                "_next_leg" in src and "L{leg_no}" not in src,
                "a project number on two open-order rows mints the same "
                "shipment_id twice, and no tool can then tell the legs apart")
    return r

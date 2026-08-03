"""Payment wording: the single definition of "did the source say this was paid".

Lives on its own, with no dependencies, because THREE modules need it --
normalize.py (deciding), audit_workbook_vs_store.py (checking) and
audit_qualified_paid.py (finding what was already mis-decided) -- and a checker
that drifts from the importer cannot catch the importer's mistake. That is not
hypothetical: all three carried their own copy of a bare r"\bpaid\b" and so
agreed, wrongly, that "NOT PAID" meant paid, for five releases.

Import it. Do not copy it.
"""
import re


def st_text(v):
    return "" if v is None else str(v)


PAID_RE = re.compile(r"\bpaid\b", re.IGNORECASE)
# Wording that CONFIRMS payment, used ONLY to overrule a partial-payment
# signal ("paid in full, balance $0", "paid - no balance due"). It must never
# overrule negation, futurity or doubt: an earlier version checked it FIRST and
# read "NOT PAID IN FULL - 50% short" as paid, because "in full" appears in it.
# Nine of ten realistic unpaid notes were written off that way.
PAID_CONFIRM_RE = re.compile(
    r"\b(?:paid\s+in\s+full|in\s+full|"
    r"balance\s*(?:is\s*)?\$?\s*0(?:\.00)?\b|"
    r"no\s+balance|nothing\s+(?:outstanding|owed|owing|due)|"
    r"paid\s+off|zero\s+balance)\b", re.IGNORECASE)

# NEGATED.
PAID_NEGATION_RE = re.compile(
    r"\b(?:not|never|non|isn'?t|wasn'?t|aren'?t|won'?t|hasn'?t|haven'?t|didn'?t|"
    r"unpaid|no\s+payment|still\s+ow(?:e|es|ed|ing)|still\s+open|"
    r"yet\s+to|owes?\s+us|write\s*-?\s*off|bad\s+debt)\b", re.IGNORECASE)

# Has not happened YET -- terms, promises, conditions.
PAID_FUTURE_RE = re.compile(
    r"\b(?:will|shall|should|going\s+to|supposed\s+to|due\s+to\s+pay|"
    r"expect(?:ed|ing|s)?|promis(?:ed|es)|pending|awaiting|chas(?:e|ing)|"
    r"c\.?o\.?d\.?|on\s+delivery|upon\s+(?:delivery|receipt|shipment)|"
    r"if|unless|once|when|to\s+be\s+paid)\b", re.IGNORECASE)

# Only PART of it.
PAID_PARTIAL_RE = re.compile(
    r"\b(?:partial(?:ly)?|deposit|down\s*payment|instal?lment|1st|2nd|first|"
    r"remaind(?:er|ing)|remaining|the\s+rest|rest\s+(?:in|on|due)|"
    r"balance\s+(?:due|owed|owing|remains)|less\s+\w+|short(?:paid)?)\b"
    r"|\d{1,3}\s*%"
    r"|\$?[\d,]+(?:\.\d\d)?\s+of\s+\$?[\d,]+"      # "$5,000 of $12,500"
    r"|\b\d+\s+of\s+\d+\b", re.IGNORECASE)           # "2 of 3 invoices paid"

# Paid, then un-paid.
PAID_REVERSAL_RE = re.compile(
    r"\b(?:bounced|nsf|returned|revers(?:e|ed|al)|charge[ds]?\s*back|"
    r"chargeback|void(?:ed)?|stopped|cancell?ed|refund(?:ed)?|"
    r"insufficient|dishonou?red)\b", re.IGNORECASE)

# Somebody is not sure.
PAID_DOUBT_RE = re.compile(
    r"\?|\b(?:disput(?:e|ed|ing)|confirm|verify|check\s+with|unclear|"
    r"unsure|claims?|says?\s+(?:they|he|she|it))\b", re.IGNORECASE)

# We paid somebody; the client still owes us.
PAID_WRONG_PARTY_RE = re.compile(
    r"\b(?:we|us|our)\s+paid\b"
    r"|\bpaid\s+(?:to\s+|the\s+)?(?:vendor|supplier|freight|carrier|factory|"
    r"mfg|manufacturer|shipper)\b", re.IGNORECASE)


def says_paid(text):
    """Did the source say this was PAID?

    True (paid), False (no mention), None (qualified -- do not guess).

    ORDER MATTERS, and getting it wrong is expensive in both directions.
    Reversal and wrong-party beat everything. Negation, futurity and doubt are
    checked BEFORE any confirmation, because "not paid in full", "will be paid
    in full" and "paid in full? confirm" all contain a confirmation phrase and
    none of them means paid. A confirmation then overrules only a PARTIAL
    signal, which is the case it exists for: "paid in full, balance $0" and
    "paid - no balance due" are payments, not part-payments.
    """
    t = st_text(text)
    if not PAID_RE.search(t):
        return False
    if PAID_REVERSAL_RE.search(t) or PAID_WRONG_PARTY_RE.search(t):
        return None
    if (PAID_NEGATION_RE.search(t) or PAID_FUTURE_RE.search(t)
            or PAID_DOUBT_RE.search(t)):
        return None
    if PAID_CONFIRM_RE.search(t):
        return True
    if PAID_PARTIAL_RE.search(t):
        return None
    return True

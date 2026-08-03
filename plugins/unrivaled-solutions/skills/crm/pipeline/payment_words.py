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
# Wording that CONFIRMS payment. Checked first, because the plain-English way
# to confirm a payment reuses words that also appear in qualifications --
# "paid in full, balance $0" and "paid - no balance due" were both being
# flagged as ambiguous, which sends the operator chasing customers who have
# already paid and buries the real flags in noise.
PAID_CONFIRM_RE = re.compile(
    r"\b(?:paid\s+in\s+full|in\s+full|"
    r"balance\s*(?:is\s*)?\$?\s*0(?:\.00)?\b|"
    r"no\s+balance|nothing\s+(?:outstanding|owed|owing|due)|"
    r"paid\s+off|settled\s+in\s+full|zero\s+balance)\b", re.IGNORECASE)

# Wording that NEGATES a nearby "paid".
PAID_NEGATION_RE = re.compile(
    r"\b(?:not|never|non|isn'?t|wasn'?t|aren'?t|won'?t|hasn'?t|haven'?t|"
    r"unpaid|no\s+payment|still\s+owes?|yet\s+to)\b", re.IGNORECASE)

# Payment that has not happened YET -- terms, promises, conditions.
PAID_FUTURE_RE = re.compile(
    r"\b(?:will\s+be|to\s+be|shall|should|going\s+to|supposed\s+to|"
    r"expect(?:ed|ing|s)?|promis(?:ed|es)|pending|awaiting|chas(?:e|ing)|"
    r"if|unless|once|when)\b", re.IGNORECASE)

# Only PART of it was paid.
PAID_PARTIAL_RE = re.compile(
    r"\b(?:partial(?:ly)?|deposit|down\s*payment|instal?lment|"
    r"remaind(?:er|ing)|remaining|balance\s+(?:due|owed|owing|remains)|"
    r"short(?:paid|\s+paid)?)\b|\d{1,3}\s*%", re.IGNORECASE)

# Paid, then un-paid.
PAID_REVERSAL_RE = re.compile(
    r"\b(?:bounced|nsf|returned|reversed|revers(?:al)?|charge\s*back|"
    r"chargeback|void(?:ed)?|stopped|cancell?ed|refund(?:ed)?|"
    r"insufficient)\b", re.IGNORECASE)

# Somebody is not sure.
PAID_DOUBT_RE = re.compile(
    r"\?|\b(?:disput(?:e|ed|ing)|confirm|verify|check\s+with|unclear|"
    r"unsure|claims?|says?\s+(?:they|he|she|it))\b", re.IGNORECASE)

# Paid to somebody who is not us.
PAID_WRONG_PARTY_RE = re.compile(
    r"\bpaid\s+(?:to|the)\s+(?:vendor|supplier|freight|carrier|factory|"
    r"mfg|manufacturer)\b", re.IGNORECASE)


def says_paid(text):
    """Did the source say this was PAID?

    True (paid), False (no mention), or None (a paid-ish word is present but
    qualified -- do not guess). None is the important one: this module's
    contract is that anything ambiguous is FLAGGED, never guessed, and guessing
    here is the difference between a collected receivable and one nobody is
    chasing.

    Both directions cost money. Reading "paid 50%" or "was paid but check
    bounced" as PAID writes off a live receivable; flagging "paid in full,
    balance $0" makes the operator chase someone who has already paid and
    turns the review list into noise he stops reading. Confirmations are
    therefore checked before qualifiers, and a reversal beats a confirmation.
    """
    t = st_text(text)
    if not PAID_RE.search(t):
        return False
    if PAID_REVERSAL_RE.search(t) or PAID_WRONG_PARTY_RE.search(t):
        return None                      # beats any confirmation
    if PAID_CONFIRM_RE.search(t):
        return True
    if (PAID_NEGATION_RE.search(t) or PAID_FUTURE_RE.search(t)
            or PAID_PARTIAL_RE.search(t) or PAID_DOUBT_RE.search(t)):
        return None
    return True

"""Parsers for the two QuickBooks Online exports the operator can download.

    Invoice List by Date          -> kind "invoices"
    Transaction List by Vendor    -> kind "vendor_transactions"

Both are READ-ONLY on their input and return a dict

    {"kind", "as_of", "window_start", "window_end", "rows"}

which server.py writes as a snapshot beside the store. Nothing here touches
the store, and nothing here talks to QuickBooks.

Layout, as exported: three title rows (company, report name, window), a blank
row, the header row, the data, then blank rows and a footer carrying the time
the report was run. Columns are found by HEADER NAME. A header that does not
match is refused whole -- the refusal carries the header found -- and no row
is ever returned from a file that was refused.

Money is integer cents. An amount that is not a whole number of cents is
refused, never rounded. Nums are kept exactly as the cell holds them; every
comparison goes through server._key() at read time, not a normaliser here.

There is deliberately no cash parser: no Balance Sheet or bank export sample
exists yet. cash_balances arrives only through the connector path.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

try:
    import openpyxl
except ImportError:                                   # pragma: no cover
    openpyxl = None

INVOICE_LIST_HEADER = ("Date", "Transaction type", "Num", "Name", "Memo",
                       "Due date", "Amount", "Open balance")
# The first column has no header: it holds the vendor group rows.
VENDOR_TXN_HEADER = (None, "Date", "Track 1099", "Transaction type", "Num",
                     "Posting (Y/N)", "Memo", "Account full name",
                     "Item split account", "Amount")

HEADER_ROW = 4          # 0-based: three title rows, a blank row, the header
WINDOW_ROW = 2

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"), 1)}
# "January 1-March 31, 2026" / "December 1, 2025-January 31, 2026" /
# "September 1-17, 2026" / "September 17, 2026"
_WINDOW_RE = re.compile(
    r"^\s*(?P<m1>[A-Za-z]+)\s+(?P<d1>\d{1,2})(?:,\s*(?P<y1>\d{4}))?"
    r"(?:\s*[-–]\s*(?:(?P<m2>[A-Za-z]+)\s+)?(?P<d2>\d{1,2}))?"
    r",\s*(?P<y2>\d{4})\s*$")
# " Thursday, September 17, 2026 02:06 PM GMT-04:00"
_FOOTER_RE = re.compile(
    r"^\s*[A-Za-z]+,\s+(?P<m>[A-Za-z]+)\s+(?P<d>\d{1,2}),\s+(?P<y>\d{4})\s+"
    r"(?P<h>\d{1,2}):(?P<mi>\d{2})\s*(?P<ap>AM|PM)\s+GMT(?P<tz>[+-]\d{2}:\d{2})\s*$")
_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


class QboExportError(Exception):
    """A file this module will not load. `found_header` is the header row it
    read, when the refusal is about the header."""

    def __init__(self, message, found_header=None):
        super().__init__(message)
        self.found_header = found_header


def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _date(v, where):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    m = _DATE_RE.match(v) if isinstance(v, str) else None
    if not m:
        raise QboExportError(f"{where}: {v!r} is not a date (MM/DD/YYYY)")
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        raise QboExportError(f"{where}: {v!r} is not a date") from None


def _cents(v, where):
    """Integer cents, exactly, or a refusal. None stays None."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise QboExportError(f"{where}: {v!r} is not an amount")
    if isinstance(v, int):
        return v * 100
    try:
        # repr() of a float is the shortest string that round-trips, so
        # 0.29 reads as Decimal("0.29"), not 0.28999999999999998
        d = Decimal(repr(v)) if isinstance(v, float) else \
            Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise QboExportError(f"{where}: {v!r} is not an amount") from None
    c = d * 100
    if not c.is_finite() or c != c.to_integral_value():
        raise QboExportError(f"{where}: {v!r} is not a whole number of cents")
    return int(c)


def _yes_no(v, where):
    if _empty(v):
        return None
    t = str(v).strip().lower()
    if t in ("yes", "no"):
        return t == "yes"
    raise QboExportError(f"{where}: {v!r} is not Yes or No")


def _window(text):
    m = _WINDOW_RE.match(text) if isinstance(text, str) else None
    if not m:
        raise QboExportError(f"title row 3: cannot read the report window "
                             f"from {text!r}")
    y2 = int(m.group("y2"))
    y1 = int(m.group("y1")) if m.group("y1") else y2
    m1 = _MONTHS.get(m.group("m1").lower())
    m2 = _MONTHS.get(m.group("m2").lower()) if m.group("m2") else m1
    if m1 is None or m2 is None:
        raise QboExportError(f"title row 3: cannot read the report window "
                             f"from {text!r}")
    d1 = int(m.group("d1"))
    d2 = int(m.group("d2")) if m.group("d2") else d1
    try:
        start, end = date(y1, m1, d1), date(y2, m2, d2)
    except ValueError:
        raise QboExportError(f"title row 3: {text!r} is not a real date range") \
            from None
    if end < start:
        raise QboExportError(f"title row 3: {text!r} ends before it starts")
    return start.isoformat(), end.isoformat()


def _footer_as_of(v):
    """The report's run time as ISO 8601 with its offset, or None."""
    m = _FOOTER_RE.match(v) if isinstance(v, str) else None
    if not m or m.group("m").lower() not in _MONTHS:
        return None
    h = int(m.group("h")) % 12 + (12 if m.group("ap") == "PM" else 0)
    try:
        dt = datetime(int(m.group("y")), _MONTHS[m.group("m").lower()],
                      int(m.group("d")), h, int(m.group("mi")))
    except ValueError:
        return None
    return dt.isoformat() + m.group("tz")


def _read(path, expected):
    """(rows, column index by header name, window, as_of) -- or a refusal."""
    if openpyxl is None:
        raise QboExportError("openpyxl is not installed: pip install openpyxl")
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as e:                            # noqa: BLE001
        raise QboExportError(f"cannot open {path} as a workbook ({e})") from None
    try:
        rows = [tuple(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()
    if len(rows) <= HEADER_ROW:
        raise QboExportError("the file ends before its header row",
                             found_header=[])
    found = list(rows[HEADER_ROW])
    while found and _empty(found[-1]):
        found.pop()
    names = [None if _empty(h) else str(h).strip() for h in found]
    if sorted(names, key=str) != sorted(expected, key=str):
        raise QboExportError(
            f"the header row does not match: expected {list(expected)}, "
            f"found {found}", found_header=found)
    col = {n: i for i, n in enumerate(names)}
    start, end = _window(rows[WINDOW_ROW][0] if rows[WINDOW_ROW] else None)
    body = rows[HEADER_ROW + 1:]
    # the footer is the last non-empty row, and only if it is the run time
    as_of = None
    for r in reversed(body):
        if any(not _empty(c) for c in r):
            as_of = _footer_as_of(r[0])
            break
    return body, col, (start, end), as_of


def _cell(row, i):
    return row[i] if i < len(row) else None


def _result(kind, window, as_of, rows):
    return {"kind": kind,
            # without a footer the only date the file vouches for is the
            # window's end
            "as_of": as_of or window[1],
            "window_start": window[0], "window_end": window[1],
            "rows": rows}


def _blank_or_footer(row):
    if all(_empty(c) for c in row):
        return True
    return _footer_as_of(_cell(row, 0)) is not None and \
        all(_empty(c) for c in row[1:])


def _skippable(row, first):
    """Blank, the grand TOTAL, or the footer: never data."""
    if isinstance(first, str) and first.strip().upper() == "TOTAL":
        return True
    return _blank_or_footer(row)


def _text(v, where):
    """A text column's cell as the file holds it. A date or time here means
    Excel re-typed the cell, and no snapshot can hold it honestly."""
    if v is None or (isinstance(v, (str, int, float)) and not isinstance(v, bool)):
        return v
    raise QboExportError(f"{where}: {v!r} is not text")


def parse_invoice_list(path):
    """Invoice List by Date (.xlsx) -> kind "invoices"."""
    body, col, window, as_of = _read(path, INVOICE_LIST_HEADER)
    out = []
    for n, row in enumerate(body, HEADER_ROW + 2):
        g = lambda name: _cell(row, col[name])        # noqa: E731
        if _skippable(row, _cell(row, 0)):
            continue
        where = f"row {n}"
        amount = _cents(g("Amount"), f"{where} Amount")
        open_ = _cents(g("Open balance"), f"{where} Open balance")
        if amount is None or open_ is None:
            raise QboExportError(f"{where}: an invoice with no Amount or "
                                 f"Open balance")
        out.append({"date": _date(g("Date"), f"{where} Date"),
                    "type": _text(g("Transaction type"), f"{where} Transaction type"),
                    "num": _text(g("Num"), f"{where} Num"),
                    "name": _text(g("Name"), f"{where} Name"),
                    "memo": _text(g("Memo"), f"{where} Memo"),
                    "due_date": None if _empty(g("Due date"))
                    else _date(g("Due date"), f"{where} Due date"),
                    "amount_cents": amount,
                    "open_cents": open_})
    return _result("invoices", window, as_of, out)


def parse_vendor_transactions(path):
    """Transaction List by Vendor (.xlsx) -> kind "vendor_transactions".

    A vendor row has the name in the first column and nothing under Date;
    every transaction below it belongs to it until the next vendor row.
    "Total for ..." rows and the grand TOTAL are skipped. A blank split
    account means QuickBooks split the amount across several accounts: it is
    recorded as null and never guessed.
    """
    body, col, window, as_of = _read(path, VENDOR_TXN_HEADER)
    out, vendor = [], None
    for n, row in enumerate(body, HEADER_ROW + 2):
        g = lambda name: _cell(row, col[name])        # noqa: E731
        first = g(None)
        if _blank_or_footer(row):
            continue
        where = f"row {n}"
        if not _empty(first):
            # A vendor row carries nothing but the name -- even a vendor named
            # "Total". A total carries an amount. Anything else is a row this
            # parser does not know.
            if _empty(g("Date")) and _empty(g("Amount")):
                vendor = str(first).strip()
                continue
            t = str(first).strip()
            if _empty(g("Date")) and (t.startswith("Total for")
                                      or t.upper() == "TOTAL"):
                continue
            raise QboExportError(f"{where}: {first!r} is neither a vendor "
                                 f"row nor a total")
        if vendor is None:
            raise QboExportError(f"{where}: a transaction above any vendor row")
        out.append({"vendor": vendor,
                    "date": _date(g("Date"), f"{where} Date"),
                    "track_1099": _yes_no(g("Track 1099"), f"{where} Track 1099"),
                    "type": _text(g("Transaction type"), f"{where} Transaction type"),
                    "num": _text(g("Num"), f"{where} Num"),
                    "posting": _yes_no(g("Posting (Y/N)"),
                                       f"{where} Posting (Y/N)"),
                    "memo": _text(g("Memo"), f"{where} Memo"),
                    "account": _text(g("Account full name"),
                                     f"{where} Account full name"),
                    "split_account": None if _empty(g("Item split account"))
                    else _text(g("Item split account"),
                               f"{where} Item split account"),
                    "amount_cents": _cents(g("Amount"), f"{where} Amount")})
    return _result("vendor_transactions", window, as_of, out)

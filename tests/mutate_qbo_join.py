#!/usr/bin/env python3
"""Mutation-test the QuickBooks tools, the invoiced-amount join, number lookup
and the two view surfaces they feed (0.1.38, B2-B4).

Every mutant is the tempting shortcut: accept an unknown field or float
cents, compare numbers without _key, let a connector-only field sit on any
row, log a snapshot load to the changelog, key a composite invoice by its
leading (quote) number, pick one of two matching rows, call an invoice dated
outside the window "missing", let the CRM's paid status override QuickBooks'
open balance, blend QuickBooks into the quoted exposure, count a Credit Memo
as an invoice, return only the first match for a number, read a PO inside a
leg's parentheses, refuse (or re-warn on) a legitimate write, and -- in the
view -- round QuickBooks cents, drop the stale marker, collapse hits, or
swallow the warning.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
SERVER, EXPORTS, VIEW = "mcp/server.py", "pipeline/qbo_exports.py", "view/build_view.py"

TOOLS = [
 ("an unknown field is accepted",
  "        unknown = sorted(set(row) - set(fields))",
  "        unknown = []"),
 # SURVIVES BY DESIGN, and that is the information: _save_qbo_snapshot refuses
 # non-integer cents itself (graded in mutate_qbo_snapshots.py), so a float
 # that slips past the connector's schema is still refused one layer down.
 # Masked, not missed: the refusal the test asserts still happens.
 ("float cents are accepted",
  '        return type(v) is int\n    if spec == "bool":',
  '        return isinstance(v, (int, float))\n    if spec == "bool":'),
 ("duplicate (type, num) is accepted",
  "            if key in seen:", "            if False:"),
 ("uniqueness compares raw numbers, not _key",
  '            key = tuple(_key(row.get(f)) for f in sch["unique"])',
  '            key = tuple(row.get(f) for f in sch["unique"])'),
 ("a connector-only field is accepted on any transaction type",
  '            if only and v is not None and row.get("type") != only:',
  "            if False:"),
 ("a window that ends before it starts is accepted",
  "    if we < ws:", "    if False:"),
 ("loading an export writes a changelog line",
  "    by_type = {}\n",
  '    STORE.log("load", "qbo_snapshot", parsed["kind"], {})\n    by_type = {}\n'),
 ("stale regardless of age",
  '"age_days": age, "stale": age > QBO_STALE_DAYS}\n',
  '"age_days": age, "stale": age >= 0}\n'),
 ("a corrupt snapshot takes qbo_snapshot_info down",
  '        except StoreError as e:\n            kinds[k] = {"loaded": False, "error": str(e)}\n            continue\n',
  "        except StoreError as e:\n            raise\n"),
]
DETECT = [
 ("every export is read as an invoice list",
  "    return parse_vendor_transactions(path)\n", "    raise\n"),
]
JOIN = [
 ("a composite invoice is keyed by its leading (quote) number",
  "    return _key(m.group(1) if m else invoice_no)",
  "    return _key(invoice_no.split()[0] if isinstance(invoice_no, str) and invoice_no.split() else invoice_no)"),
 ("two matching rows: the first is picked",
  '        if any(len(h) > 1 for h in found):\n            return None, "ambiguous_qbo_match"\n', ""),
 ("one QuickBooks invoice claimed by two CRM invoices counts twice",
  '            if any(self.qbo_claims.get(k, 0) > 1 for k in keys):\n                return None, "qbo_match_shared"\n', ""),
 ("a pair prices when only one of its two invoices matches",
  '            if len(matched) < len(keys):\n                return None, "partial_qbo_match"\n', ""),
 ("the shared check is skipped for a pair",
  "            if any(self.qbo_claims.get(k, 0) > 1 for k in keys):",
  "            if len(keys) == 1 and self.qbo_claims.get(keys[0], 0) > 1:"),
 ("a pair's numbers are not counted as claims",
  '            for k in _qbo_invoice_keys(i.get("invoice_no")):',
  '            for k in (_qbo_invoice_keys(i.get("invoice_no")) if not _INV_PAIR_RE.match(str(i.get("invoice_no") or "")) else ()):'),
 ("an invoice outside the window reads as missing from QuickBooks",
  '        if not ws <= d.date() <= we:\n            return None, "outside_snapshot_window"\n', ""),
 ("an undated invoice reads as missing from QuickBooks",
  '        if not inv.get("invoice_date"):\n            return None, "no_date"\n', ""),
 ("a Credit Memo is matched as an invoice",
  '                if row.get("type") != "Invoice":\n                    continue\n', ""),
 ("the CRM's paid status overrides QuickBooks' open balance",
  '            amt += row["amount_cents"]; opn += row["open_cents"]; n += 1',
  '            amt += row["amount_cents"]; n += 1\n'
  '            opn += 0 if str(i.get("payment_status") or "").startswith("paid") else row["open_cents"]'),
 ("QuickBooks is blended into the quoted exposure",
  '        exposure = _shape(owed, "usd", owed_n, _tally(owed_exc),',
  '        exposure = _shape(owed + ((self.qbo_totals(invoices)[1]["value_cents"] or 0) // 100), "usd", owed_n, _tally(owed_exc),'),
 ("a corrupt snapshot takes every read down",
  "        except StoreError as e:\n            self.qbo_error = str(e)\n",
  "        except ZeroDivisionError as e:\n            self.qbo_error = str(e)\n"),
 ("the drift's CRM side counts invoices outside the window",
  '                   if self.qbo_match(i)[1] == "not_in_qbo_snapshot"]',
  '                   if self.qbo_match(i)[1] in ("not_in_qbo_snapshot", "outside_snapshot_window")]'),
 ("the drift's QuickBooks side counts Credit Memos",
  '        q_rows = ([r_ for r_ in self.qbo["rows"] if r_.get("type") == "Invoice"]',
  '        q_rows = ([r_ for r_ in self.qbo["rows"]]'),
 ("a snapshot whose window is reversed is read, not refused",
  '          and _iso_date(doc["window_start"]) <= _iso_date(doc["window_end"]))',
  "          )"),
 ("the INV reader drifts from the importer's (case-sensitive)",
  '_INV_NO_RE = re.compile(r"INV[\\s#-]*(\\d+)", re.IGNORECASE)',
  '_INV_NO_RE = re.compile(r"INV[\\s#-]*(\\d+)")'),
]
LOOKUP = [
 ("only the first match is returned",
  "    out.extend(groups.values())\n    return out, errors",
  "    out.extend(groups.values())\n    return out[:1], errors"),
 ("a number inside a leg's parentheses is its PO",
  '        u = _PAREN_RE.sub(" ", t)', "        u = t"),
 ("a composite CRM invoice is found by its leading number",
  '        if _qbo_invoice_key(i.get("invoice_no")) == k:',
  '        if _key(str(i.get("invoice_no")).split(" ")[0]) == k:'),
 ("a bill is not flagged as the vendor's own number",
  "                g[\"note\"] = BILL_NUM_NOTE\n", "                pass\n"),
 ("an Expense is reported as a bill",
  '        t = {"Purchase Order": "qbo_po", "Bill": "qbo_bill"}.get(row.get("type"))',
  '        t = {"Purchase Order": "qbo_po", "Bill": "qbo_bill", "Expense": "qbo_bill"}.get(row.get("type"))'),
 ("a PO's lines are each a separate match",
  '            g = groups.setdefault((t, row.get("vendor")), {',
  '            g = groups.setdefault((t, row.get("vendor"), id(row)), {'),
 ("the lookup does not go through _key",
  # re-anchored 0.1.39: the same line now also starts the unmatched-names list
  "    k = _key(n)\n    out, errors, unmatched = [], [], []",
  "    k = n\n    out, errors, unmatched = [], [], []"),
 ("the warning refuses the write",
  '            out = {"ok": True, "interface_version": VERSION,\n                   "invoice": _with_due_on([target[0]])[0]}\n            if warnings:',
  '            if warnings:\n                raise StoreError("number is also a PO")\n'
  '            out = {"ok": True, "interface_version": VERSION,\n                   "invoice": _with_due_on([target[0]])[0]}\n            if warnings:'),
 ("an echoed project_no warns on every save",
  "                        if _pno and not _echoed and _pno != _stored_pno else [])",
  "                        if _pno else [])"),
 ("an unreadable store file fails a write that was already saved",
  "        return _po_warnings(project_no)\n    except StoreError as e:",
  "        return _po_warnings(project_no)\n    except ZeroDivisionError as e:"),
 ("create_invoice never warns",
  "            warnings = _po_warnings_safe(pno) if pno else []", "            warnings = []"),
]
QBO_VIEW = [
 ("the stale marker is never shown",
  "      + (q.stale ? ", "      + (false ? "),
 ("the QBO open column shows the amount",
  "      <td class=\"num\">${qboCell(v, 'qbo_open_usd')}</td>",
  "      <td class=\"num\">${qboCell(v, 'qbo_amount_usd')}</td>"),
 ("the header sums rounded dollars, not cents",
  "    if(s.value_cents != null) out.value_cents += Number(s.value_cents)||0;",
  "    if(s.value != null) out.value_cents += Math.round(Number(s.value)||0)*100;"),
 ("the CRM figure is not labelled quoted",
  "  const quoted = q ? ', quoted' : '';", "  const quoted = '';"),
 ("an unpriced row gives no reason",
  "  if(sh.value_cents == null){", "  if(false){"),
 ("the header claims QuickBooks with no snapshot loaded",
  "    .filter(s => s && typeof s === 'object' && 'population' in s && s.snapshot_as_of);",
  "    .filter(s => s && typeof s === 'object' && 'population' in s);"),
]
QBO_VIEW_KEYS = [
 ("the per-invoice map is keyed by Python's str(), not the page's st()",
  '                "qbo_invoices": {_js_str(i.get("invoice_no")): self.invoice_qbo(i)',
  '                "qbo_invoices": {str(i.get("invoice_no")): self.invoice_qbo(i)'),
]
NUMBER_VIEW = [
 ("a hit of a type the page has no label for is dropped",
  "    .concat(Object.keys(groups).filter(t => !(t in NUMBER_TYPE_LABELS)));",
  "    .concat([]);"),
 ("hits collapse into one result",
  "  (r.matches || []).forEach(m => { (groups[m.type] = groups[m.type] || []).push(m); });",
  "  (r.matches || []).slice(0, 1).forEach(m => { (groups[m.type] = groups[m.type] || []).push(m); });"),
 ("groups are labelled by their code",
  "${esc(NUMBER_TYPE_LABELS[t] || String(t).replace(/_/g, ' '))}</div>", "${esc(t)}</div>"),
 ("the warning is swallowed after the save",
  "  const w = (r && r.warnings) || [];", "  const w = [];"),
 ("text that is not a number opens the panel",
  "  if(!/^\\d+$/.test(n)){ el.innerHTML = ''; return; }",
  "  if(!n){ el.innerHTML = ''; return; }"),
]


def main():
    worst = 0
    for title, target, test, mutants in (
            ("B2 TOOLS -- server.py", SERVER, "./tests/regression/test_qbo_tools.py", TOOLS),
            ("B2 DETECT -- qbo_exports.py", EXPORTS, "./tests/regression/test_qbo_tools.py", DETECT),
            ("B3 JOIN -- server.py", SERVER, "./tests/regression/test_qbo_invoiced.py", JOIN),
            ("B3 VIEW -- build_view.py", VIEW, "./tests/regression/test_qbo_view.js", QBO_VIEW),
            ("B3 VIEW KEYS -- server.py", SERVER, "./tests/regression/test_qbo_view.js", QBO_VIEW_KEYS),
            ("B4 LOOKUP -- server.py", SERVER, "./tests/regression/test_number_lookup.py", LOOKUP),
            ("B4 VIEW -- build_view.py", VIEW, "./tests/regression/test_number_view.js", NUMBER_VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

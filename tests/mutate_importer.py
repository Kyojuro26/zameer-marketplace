#!/usr/bin/env python3
"""Mutation-test the importer blocker fixes.

Two of these mutants are the bugs that actually shipped (the unbound rn, and
clean() used as a presence test). One is the TRAP: "fixing" clean() to drop
zeros, which loses a literal 0 identifier and would look like a tidy-up.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "pipeline/normalize.py"

M = [
 # ---- the eight a test-validity review found surviving at 95/95 -----------
 ("the keyless-row condition is INVERTED",
  "                if any(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):",
  "                if not any(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):"),
 ("any -> all over the financial columns",
  "                if any(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):",
  "                if all(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):"),
 ("only revenue counts as a financial column",
  "                if any(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):",
  "                if any(has_value(g(c)) for c in (c_rev,) if c):"),
 ("the reported row number is off by one",
  "                                              values_only=True), start=hrow + 1):",
  "                                              values_only=True), start=1):"),
 ("the send-PO header stops resolving",
  "        \"send_po\": [\"send po's to\", \"send po\u2019s to\"], \"send_inv\": [\"send invoices to\"],",
  "        \"send_po\": [\"send purchase orders to\"], \"send_inv\": [\"send invoices to\"],"),
 ("invoice_routing loses its has_value guard",
  "            \"invoice_routing\": clean(g(vc[\"send_inv\"])) if has_value(g(vc[\"send_inv\"])) else None,",
  "            \"invoice_routing\": clean(g(vc[\"send_inv\"])),"),
 ("po_routing_source hardcoded to non-sheet",
  "            \"po_routing_source\": \"sheet\" if has_value(g(vc[\"send_po\"])) else \"knowledge-base (to mine)\",",
  "            \"po_routing_source\": \"knowledge-base (to mine)\","),
 ("has_value loses comma stripping",
  "        return float(s.replace(\",\", \"\")) != 0.0",
  "        return float(s) != 0.0"),

 # ---- the sites the data-integrity review found were missed ---------------
 ("open-orders presence test reverts to str().strip()",
  "            if r and any(has_value(c) for c in r[1:]):\n                review.append({\n                    \"type\": \"open_order_row_without_project\",",
  "            if r and any(c is not None and str(c).strip() for c in r[1:]):\n                review.append({\n                    \"type\": \"open_order_row_without_project\","),
 ("the deal-log sheets lose their cap check again",
  "        _cap_check(ws, ROW_CAP, f'{sheet} sheet', review)\n", ""),
 ("the cap check flags formatted-empty padding as lost data",
  "    if last_real is None:\n        return                  # formatted-empty padding, nothing was lost\n", ""),
 # ---- the crash that shipped in 0.1.29 -----------------------------------
 ("rn unbound again (the 0.1.29 crash)",
  "        for rn, row in enumerate(ws.iter_rows(min_row=hrow + 1, max_row=ROW_CAP,\n"
  "                                              values_only=True), start=hrow + 1):",
  "        for row in ws.iter_rows(min_row=hrow + 1, max_row=ROW_CAP, values_only=True):"),

 # ---- the presence-vs-coercion bug ---------------------------------------
 ("clean() used as the presence test again (39,726 entries)",
  "                if any(has_value(g(c)) for c in (c_rev, c_gp, c_cost) if c):",
  "                if any(clean(g(c)) for c in (c_rev, c_gp, c_cost) if c):"),
 ("has_value treats numeric zero as present",
  "        return float(s.replace(\",\", \"\")) != 0.0",
  "        return True"),
 ("has_value treats every non-empty string as absent",
  "    except ValueError:\n        return True",
  "    except ValueError:\n        return False"),

 # ---- THE TRAP: the tidy-up that loses a real key ------------------------
 ("clean() 'fixed' to drop zeros -- loses a literal 0 identifier",
  "    s = str(v).strip()\n    return s if s else None",
  "    s = str(v).strip()\n    if s in ('0', '0.0'):\n        return None\n    return s if s else None"),

 # ---- the review entry has to be actionable ------------------------------
 ("the review entry stops naming its sheet",
  "                        \"sheet\": sheet,\n                        \"sheet_row\": rn,",
  "                        \"sheet_row\": rn,"),

 # ---- provenance ---------------------------------------------------------
 ("a zero send-PO cell is stored as the routing address again",
  "            \"po_routing\": clean(g(vc[\"send_po\"])) if has_value(g(vc[\"send_po\"])) else None,",
  "            \"po_routing\": clean(g(vc[\"send_po\"])),"),
 ("a zero send-PO cell claims sheet provenance again",
  "            \"po_routing_source\": \"sheet\" if has_value(g(vc[\"send_po\"])) else \"knowledge-base (to mine)\",",
  "            \"po_routing_source\": \"sheet\" if clean(g(vc[\"send_po\"])) else \"knowledge-base (to mine)\","),
]

sys.exit(mutate(SRC, "./tests/regression/test_importer.py", F, M))

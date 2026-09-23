#!/usr/bin/env python3
"""Mutation-test the customer/vendor link and QuickBooks name resolution
(0.1.39, Phase C): tests/regression/test_entity_links.py against mcp/server.py,
and tests/regression/test_entity_links_view.js (a live local_server.py driven
by headless Chromium) against view/build_view.py.

Every mutant is the tempting shortcut: let two companies share a vendor, link
an archived or missing vendor, link a company to itself or from a vendor,
stop deriving the vendor's side, count an archived company as the holder,
read the display name before qbo_name, give an ambiguous name to one record,
compare names without normalising them, resolve customer names against
vendor companies, drop the legal-suffix rule, suggest pairs already linked,
and -- in the view -- never send the link, or show no cross-reference.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("two companies may link one vendor",
  "    holder = _vendor_link_holder(value, companies, but=company_id)\n    if holder:",
  "    holder = None\n    if holder:"),
 ("an archived vendor may be linked",
  '    if v.get("archived") or (vco and vco.get("archived")):',
  "    if False:"),
 ("a vendor that does not exist may be linked",
  "    if v is None:\n        raise StoreError(f\"no vendor record '{value}'\")\n",
  "    if v is None:\n        return\n"),
 ("a company may link to itself",
  "    if _key(value) == _key(company_id):", "    if False:"),
 ("a vendor company may hold a link",
  '    if me is not None and me.get("role") == "vendor":', "    if False:"),
 ("the vendor side is not derived",
  '    return dict(v, linked_company_id=holder.get("company_id") if holder else None)',
  "    return dict(v)"),
 ("an archived company still reads as the vendor's link",
  '    holder = _vendor_link_holder(v.get("company_id"),\n'
  '                                 [c for c in companies if not c.get("archived")])',
  '    holder = _vendor_link_holder(v.get("company_id"), companies)'),
 ("the display name is read before qbo_name",
  "        for ids in (by_qbo.get(name.strip()), by_disp.get(_name_key(name))):",
  "        for ids in (by_disp.get(_name_key(name)), by_qbo.get(name.strip())):"),
 ("an ambiguous name is given to the first record",
  '            if ids:\n                return None, {"name": name, "reason": "ambiguous",',
  '            if ids:\n                return ids[0], {"name": name, "reason": "ambiguous",'),
 ("display names are compared raw, not normalised",
  '        k = _name_key(rec.get("display_name"))\n        if k:',
  '        k = rec.get("display_name")\n        if k:'),
 ("customer names resolve against vendor companies too",
  '                [c for c in self.companies if not c.get("archived")\n'
  '                 and c.get("role") != "vendor"])',
  '                [c for c in self.companies if not c.get("archived")])'),
 ("the caller's spelling of the vendor id is stored",
  '    return v.get("company_id")\n', "    return value\n"),
 ("an archived holder is refused without saying it is archived",
  '        where = ("; that company is archived -- restore it, unlink it, and "\n'
  '                 "archive it again" if holder.get("archived")\n'
  '                 else "; unlink it there first")',
  '        where = "; unlink it there first"'),
 ("the legal-suffix rule is dropped",
  "            elif cbase[0] and cbase[0] == vbase[0]:", "            elif False:"),
 ("a vendor linked elsewhere is suggested again",
  '            and _key(v.get("company_id")) not in held]', "            ]"),
 ("a company already linked is suggested again",
  '    cos = [c for c in live if c.get("role") in ("customer", "lead")\n'
  '           and not c.get("linked_vendor_id")]',
  '    cos = [c for c in live if c.get("role") in ("customer", "lead")]'),
]
VIEW = [
 ("the drawer never sends the link",
  "  if(lv && lv.value !== (lv.getAttribute('data-orig')||'')) fields.linked_vendor_id = lv.value || null;\n",
  ""),
 ("the vendor page shows no linked company",
  "    const lc = linkedCompanyOf(c.company_id);", "    const lc = null;"),
 ("the company's cross-reference does not open the vendor",
  "    <a href=\"#\" id=\"xref-vendor\" onclick=\"select('${jesc(vid)}');return false\">",
  "    <a href=\"#\" id=\"xref-vendor\" onclick=\"return false\">"),
]


def main():
    worst = 0
    for title, target, test, mutants in (
            ("SERVER -- mcp/server.py", "mcp/server.py",
             "./tests/regression/test_entity_links.py", SERVER),
            ("VIEW -- view/build_view.py", "view/build_view.py",
             "./tests/regression/test_entity_links_view.js", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

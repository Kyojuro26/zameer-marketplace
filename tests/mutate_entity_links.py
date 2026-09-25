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
 # re-anchored 0.1.44: qbo_name is looked up normalised, as the invoice match compares it
 ("the display name is read before qbo_name",
  "        for ids in (by_qbo.get(_name_key(name)), by_disp.get(_name_key(name))):",
  "        for ids in (by_disp.get(_name_key(name)), by_qbo.get(_name_key(name))):"),
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
  "    if ab and ab == bb:", "    if False:"),
 ("a vendor linked elsewhere is suggested again",
  '    vens = [v for v in live_vendors if _key(v.get("company_id")) not in held]',
  "    vens = live_vendors"),
 ("a company already linked is suggested again",
  '    cos = [c for c in sellers if not c.get("linked_vendor_id")]',
  "    cos = sellers"),
 # ---- C2: QuickBooks vendors that are CRM customers --------------------------
 ("a QuickBooks vendor must match a customer's name exactly (the suffix rule dropped)",
  '            fits = [(c, _names_match(c.get("display_name"), qn)) for c in sellers]',
  '            fits = [(c, "the same name" if c.get("display_name") == qn else None) for c in sellers]'),
 ("a looser rule: the QuickBooks name inside the customer's name",
  '            fits = [(c, _names_match(c.get("display_name"), qn)) for c in sellers]',
  '            fits = [(c, "inside" if _name_key(qn) and _name_key(qn) in _name_key(c.get("display_name")) else None) for c in sellers]'),
 ("a QuickBooks vendor name that fits two customers is given to the first",
  "            if len(fits) > 1:", "            if False:"),
 ("a customer already linked is suggested again",
  '            if not fits or fits[0][0].get("linked_vendor_id"):', "            if not fits:"),
 ("an existing vendor record for the QuickBooks name is not found",
  "            vid, _miss = vres(qn)", "            vid = None"),
 ("the confirm acts on a name that is not a suggestion",
  "    if not hit:\n        return _err(",
  "    if not hit:\n        hit = {\"vendor_id\": None}\n    if False:\n        return _err("),
 ("the confirm creates a second vendor record where one exists",
  '    vid, created = hit["vendor_id"], False', "    vid, created = None, False"),
]
VIEW = [
 ("the drawer lists no QuickBooks suggestion",
  "  const mine = (r.qbo_vendor_names || []).filter(x => st(x.company_id) === cid);",
  "  const mine = [];"),
 ("a confirmed link does not reach the page",
  "  if(i >= 0 && r.company) DATA.companies[i] = r.company;\n", ""),
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

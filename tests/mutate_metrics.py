#!/usr/bin/env python3
"""Mutation-test tests/regression/test_metrics.py against mcp/server.py.

Every metric is DERIVED, so a wrong one looks entirely plausible -- and the
shape exists precisely so a wrong denominator cannot hide. These mutants are
the plausible wrong versions: the ones a reasonable person would have written
(a missing amount as zero, paid invoices aged, an open leg judged late, the
share taken over the population instead of the counted total), plus the
mutants that attack the shape itself (an exclusion dropped from the tally,
a zero rendered where null belongs, metrics written to disk).

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_metrics.py"
F = "mcp/server.py"

M = [
 # ---- the shape itself --------------------------------------------------
 ("zero rendered when nothing was counted",
  '    sh = {"value": value if counted else None, "unit": unit,',
  '    sh = {"value": value if counted else 0, "unit": unit,'),
 ("population stops being counted plus the exclusions",
  '          "counted": counted, "population": counted + sum(exc.values()),',
  '          "counted": counted, "population": counted,'),
 ("an unknown exclusion reason is let through",
  "        if k not in EXCLUSION_REASONS:\n"
  "            raise StoreError(f\"internal: exclusion reason {k!r} is not in the vocabulary\")",
  "        pass"),
 ("a reason is renamed out from under the vocabulary",
  '    "no_project_link", "no_revenue_on_project", "no_cost_on_project", "paid",\n'
  '    "not_won", "no_won_revenue",',
  '    "no_project_link", "no_revenue", "no_cost_on_project", "paid",\n'
  '    "not_won", "no_won_revenue",'),
 ("an exclusion is dropped from the tally (no_revenue on exposure)",
  '        amt = _num(p.get("revenue"))\n'
  '        if amt is None:\n'
  '            return None, "no_revenue_on_project"\n'
  '        return amt, None',
  '        amt = _num(p.get("revenue"))\n'
  '        return (amt if amt is not None else 0), None'),
 ("the quoted qualifier is dropped from the profit basis",
  '                    "quoted revenue minus quoted total cost over won projects; "\n'
  '                    "quoted at the deal, not realised")',
  '                    "revenue minus total cost over won projects")'),
 ("the quoted qualifier is dropped from the profit NAME",
  '        return {"revenue_won_usd": rev, "quoted_gross_profit_usd": gp,',
  '        return {"revenue_won_usd": rev, "gross_profit_usd": gp,'),

 # ---- money --------------------------------------------------------------
 ("an unlinked invoice is given an amount of zero",
  '        pno = _key(inv.get("project_no"))\n'
  '        if not pno:\n'
  '            return None, "no_project_link"',
  '        pno = _key(inv.get("project_no"))\n'
  '        if not pno:\n'
  '            return 0, None'),
 ("the amount ignores which company the project belongs to",
  '        p = self.proj_by_key.get((pno, _hk(inv.get("company_id"))))',
  '        p = next((q for (k, _c), q in self.proj_by_key.items() if k == pno), None)'),
 ("part-payment percentage read as UNPAID rather than received",
  "        return (round(amt * (1 - pct)) if pct is not None else round(amt)), None",
  "        return (round(amt * pct) if pct is not None else round(amt)), None"),
 ("a paid invoice is excluded from exposure instead of counting as 0",
  '        if str(inv.get("payment_status") or "").startswith("paid"):\n'
  '            return 0, None\n'
  '        amt, why = self.invoice_amount(inv)',
  '        if str(inv.get("payment_status") or "").startswith("paid"):\n'
  '            return None, "paid"\n'
  '        amt, why = self.invoice_amount(inv)'),
 ("a paid invoice still owes its full value",
  '        if str(inv.get("payment_status") or "").startswith("paid"):\n'
  '            return 0, None\n'
  '        amt, why = self.invoice_amount(inv)',
  '        amt, why = self.invoice_amount(inv)'),
 ("pending projects count toward won revenue",
  '            if p.get("status") != "won":\n'
  '                exc.append("not_won"); continue\n'
  '            rev = _num(p.get("revenue"))',
  '            rev = _num(p.get("revenue"))'),
 ("a project with no cost is given a cost of zero",
  '            c_ = _num(p.get("total_cost"))\n'
  '            if c_ is None:\n'
  '                gp_exc.append("no_cost_on_project"); continue',
  '            c_ = _num(p.get("total_cost")) or 0'),

 # ---- dates and ageing ----------------------------------------------------
 ("paid invoices are aged",
  '        if str(inv.get("payment_status") or "").startswith("paid"):\n'
  '            return None, "paid"\n'
  '        due = _effective_due_on(inv)',
  '        due = _effective_due_on(inv)'),
 ("days late can go negative for an invoice not yet due",
  "        return max(0, (self.today - d.date()).days), None",
  "        return (self.today - d.date()).days, None"),
 ("an invoice due today lands in not_yet_due",
  "            if due > self.today:",
  "            if due >= self.today:"),
 ("the 31-60 bucket is off by one",
  "            elif d <= 60:", "            elif d < 60:"),
 ("the clock is read from the wall instead of the hook",
  "        self.today = _today()",
  "        self.today = datetime.now().date()"),
 ("an unreadable due_on override is treated as no date",
  '        if not d:\n'
  '            return None, "unparseable_date"\n'
  '        return max(0, (self.today - d.date()).days), None',
  '        if not d:\n'
  '            return None, "no_date"\n'
  '        return max(0, (self.today - d.date()).days), None'),

 # ---- cycle time ------------------------------------------------------------
 ("the latest leg is used instead of the earliest",
  "        days = (min(shipped) - start.date()).days",
  "        days = (max(shipped) - start.date()).days"),
 ("an EST date is read as an actual ship date",
  "            if d and not est:\n                shipped.append(d)",
  "            if d:\n                shipped.append(d)"),
 ("an Ordered leg with a planned date counts as shipped",
  '            if s.get("stage") not in SHIPPED_STAGES:\n'
  '                continue\n'
  '            d, est = _parse_ship_date(s.get("ship_date"))',
  '            d, est = _parse_ship_date(s.get("ship_date"))'),
 ("a negative cycle time is reported instead of excluded",
  '        if days < 0:\n'
  '            return _shape(None, "days", 0, {"ship_before_project_date": 1}, basis)\n',
  ''),
 ("a project with no legs reads as no_shipped_leg",
  '        if not legs:\n'
  '            return _shape(None, "days", 0, {"no_shipment": 1}, basis)\n',
  ''),

 # ---- vendor on-time --------------------------------------------------------
 ("cancelled legs are judged, and late",
  '            if s.get("stage") == "Cancelled":\n'
  '                why = "cancelled"\n'
  '            elif not vid or isinstance(vid, bool):',
  '            if not vid or isinstance(vid, bool):'),
 ("Ordered and On Hold legs are judged as shipped",
  'SHIPPED_STAGES = {"Shipped", "Delivered", "Installed"}',
  'SHIPPED_STAGES = {"Shipped", "Delivered", "Installed", "Ordered", "On Hold"}'),
 ("Delivered legs are no longer shipped",
  'SHIPPED_STAGES = {"Shipped", "Delivered", "Installed"}',
  'SHIPPED_STAGES = {"Shipped", "Installed"}'),
 ("an EST ship date is judged as actual",
  '                    if est:\n'
  '                        why = "ship_date_is_estimate"\n'
  '                    elif not shipped:',
  '                    if not shipped:'),
 ("on time is strictly before the ETA, not on or before",
  "            on_time = sum(1 for d in lates if d == 0)",
  "            on_time = sum(1 for d in lates if d < 0)"),
 ("a vendor with nothing judged is dropped from the rows",
  "        for vid in per_vendor_exc:\n            lates = judged.get(vid, [])",
  "        for vid in judged:\n            lates = judged.get(vid, [])"),

 # ---- concentration -----------------------------------------------------------
 ("the share is taken over the population instead of the counted total",
  '            r_["share"] = (r_["revenue_won_usd"] / total) if total else 0.0',
  '            r_["share"] = (r_["revenue_won_usd"] / (total + len(exc))) if total else 0.0'),
 ("vendors and leads join the customer population",
  '                     if not c.get("archived") and c.get("role") == "customer"]',
  '                     if not c.get("archived")]'),
 ("the year filter compares strictly, dropping a text year",
  '                projects = [p for p in projects if _key(p.get("year")) == _key(year)]',
  '                projects = [p for p in projects if p.get("year") == year]'),
 ("the year filter is ignored",
  '            if year is not None:\n'
  '                projects = [p for p in projects if _key(p.get("year")) == _key(year)]\n',
  ''),

 # ---- archived records ----------------------------------------------------------
 ("archived projects are in every population",
  '        self.projects = [p for p in STORE.load("projects")\n'
  '                         if not p.get("archived")\n'
  '                         and _hk(p.get("company_id")) not in self.arch_cids]',
  '        self.projects = list(STORE.load("projects"))'),
 ("invoices of archived companies are in the population",
  '        self.invoices = [i for i in STORE.load("invoices")\n'
  '                         if _hk(i.get("company_id")) not in self.arch_cids\n'
  '                         and not _invoice_hidden(i, self.arch_pnos)]',
  '        self.invoices = list(STORE.load("invoices"))'),
 ("legs of archived projects are in the population",
  '        self.shipments = [s for s in STORE.load("shipments")\n'
  '                          if _hk(s.get("company_id")) not in self.arch_cids\n'
  '                          and not _shipment_hidden(s, self.arch_pnos)]',
  '        self.shipments = list(STORE.load("shipments"))'),

 # ---- malformed records and shared numbers (second review round) -----------------
 ("an unhashable identifier raises instead of matching nothing",
  "    try:\n        hash(v)\n    except TypeError:\n        return None\n    return v",
  "    return v"),
 ("Infinity is treated as a revenue",
  '    return f if f == f and f not in (float("inf"), float("-inf")) else None',
  '    return f if f == f else None'),
 ("legs are keyed by project number alone, across customers",
  '                self.legs_by_key.setdefault((n, _hk(s.get("company_id"))), []).append(s)',
  '                self.legs_by_key.setdefault((n, None), []).append(s)\n'
  '        self.legs_by_key = {k: v for k, v in self.legs_by_key.items()}\n'
  '        _lk = self.legs_by_key\n'
  '        self.legs_by_key = type("L", (), {"get": lambda _s, k, d=None: _lk.get((k[0], None), d)})()'),
 ("an estimate needs a space after EST to be recognised",
  '    m = re.match(r"^\\s*est(?:imated)?\\.?\\s*(?=\\d)", t, re.I)',
  '    m = re.match(r"^\\s*est\\.?\\s+(?=\\d)", t, re.I)'),

 # ---- persistence ---------------------------------------------------------------
 ("metrics are written to disk on read",
  '    return [dict(p, metrics=ctx.project_metrics(p)) for p in projects]',
  '    for p in projects:\n'
  '        p["metrics"] = ctx.project_metrics(p)\n'
  '    STORE.save("projects", STORE.load("projects")[:0] + projects)\n'
  '    return projects'),
 ("metrics becomes a writable project field",
  '    "tracker_key",\n}',
  '    "tracker_key", "metrics",\n}'),
 ("an unknown report is served as all three instead of refused",
  '    if report is not None and report not in METRIC_REPORTS:\n'
  '        return _err(f"report must be one of {list(METRIC_REPORTS)} or omitted")\n',
  '    if report is not None and report not in METRIC_REPORTS:\n'
  '        report = None\n'),
]

# The view builder embeds the shapes by importing server.py. Its one rule: a
# BUILD reads the store and never writes it.
V = [
 ("the build constructs Store(), which writes into the store directory",
  "            st = _srv.Store.__new__(_srv.Store)\n"
  "            st.root = _P(store_dir)\n"
  "            _srv.STORE = st",
  "            _srv.STORE = _srv.Store(_P(store_dir))"),
 ("the build stops embedding shapes at all",
  "    _attach_metrics(data, store_dir)\n", ""),
]

worst = 0
print(f"=== METRICS -- mcp/server.py  ({len(M)} mutants) ===")
worst = max(worst, mutate(SRC, TEST, F, M))
print(f"\n=== BUILD -- view/build_view.py  ({len(V)} mutants) ===")
worst = max(worst, mutate(SRC, TEST, "view/build_view.py", V))
sys.exit(worst)

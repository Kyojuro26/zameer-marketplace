#!/usr/bin/env python3
"""Mutation-test the quote pipeline (0.1.41, Phase E): tests/regression/
test_quotes.py against mcp/server.py, and tests/regression/test_quotes_view.js
(a live local_server.py in headless Chromium) against view/build_view.py.

Every mutant is the tempting shortcut: let a quote go out before it was asked
for, judge only the fields sent, accept a revision with no request date, count
calendar days as business days, drop the SLA flag, drop an unreadable request
from sight, flag a follow-up that is in the future, list a won project as
awaiting, forget that an edit is activity, credit one customer's edit to
another's project, change a stale project, average instead of median, count a
quote with no request date, blend pending into the win rate, hard-code the
SLA -- and in the view: stop sending the date, send the wrong revision, or
never re-read the server.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"

SERVER = [
 ("a quote may go out before it was asked for",
  "    if rq and se and se.date() < rq.date():", "    if False:"),
 ("only the fields sent are judged, not the record as it will be saved",
  "            _check_quote_order(dict(target[0], **fields))", "            _check_quote_order(fields)"),
 ("a revision with no request date is accepted",
  "            if not rv.get(\"requested_on\"):\n                raise StoreError(",
  "            if False:\n                raise StoreError("),
 ("calendar days are counted as business days",
  "        if d.weekday() < 5:\n            days += 1", "        days += 1"),
 ("the SLA flag is dropped",
  "                            past_sla=(age > sla) if age is not None else None,",
  "                            past_sla=False if age is not None else None,"),
 ("an unreadable request date drops out of sight",
  '            if p.get("quote_requested_on") and not p.get("quote_sent_on"):',
  '            if req and not p.get("quote_sent_on"):'),
 ("a follow-up in the future still reads as none",
  "                                      no_follow_up=not (follow and follow > today)))",
  "                                      no_follow_up=True))"),
 ("a won project is listed as awaiting a decision",
  '            if p.get("status") != "pending":\n                continue\n            # sent, awaiting a decision',
  "            # sent, awaiting a decision"),
 ("an edit is not activity",
  '            touched = activity.get((_key(p.get("project_no")), _hk(p.get("company_id"))))',
  "            touched = None"),
 ("one customer's edit counts for another's project of the same number",
  '            touched = activity.get((_key(p.get("project_no")), _hk(p.get("company_id"))))',
  '            touched = max([v for (k_, c_), v in activity.items() if k_ == _key(p.get("project_no"))], default=None)'),
 ("the stale list marks projects lost",
  "            if days is None or days > n_stale:\n                stale.append(",
  "            if days is None or days > n_stale:\n                p[\"status\"] = \"lost\"\n                stale.append("),
 ("turnaround is the mean, not the median",
  "        turnaround = _shape(statistics.median(measured) if measured else None,",
  "        turnaround = _shape(statistics.mean(measured) if measured else None,"),
 ("a quote with no request date is measured anyway",
  "        measured = sorted(_business_days(rq, se) for rq, se, has in pairs\n                          if has and rq and se)",
  "        measured = sorted(_business_days(rq or se, se) for rq, se, has in pairs\n                          if se)"),
 ("pending projects are counted as decided in the win rate",
  "        win = _shape(won / (won + lost) if won + lost else None, \"ratio\", won + lost,",
  "        win = _shape(won / len(self.projects) if self.projects else None, \"ratio\", won + lost,"),
 ("the SLA is hard-coded, not the store's setting",
  '        sla, n_stale = cfg["quote_sla_business_days"], cfg["stale_pending_days"]',
  '        sla, n_stale = 2, cfg["stale_pending_days"]'),
 ("a bad settings file costs the company figures too",
  "            except Exception as ex:                           # noqa: BLE001\n                data[key] = None",
  "            except ZeroDivisionError as ex:\n                data[key] = None"),
]
VIEW = [
 ("'Mark sent' sends no date",
  "    else fields = {quote_sent_on: today};", "    else fields = {};"),
 ("'Mark sent' on a revision dates the first revision",
  "    if(kind === 'revision'){ revs[idx] = Object.assign({}, revs[idx], {sent_on: today});",
  "    if(kind === 'revision'){ revs[0] = Object.assign({}, revs[0], {sent_on: today});"),
 ("the list is not re-read from the server after an action",
  "  if(msg) msg.textContent = '\\u2713 saved';\n  await loadQuotes();",
  "  if(msg) msg.textContent = '\\u2713 saved';"),
]


def main():
    worst = 0
    for title, target, test, mutants in (
            ("SERVER -- mcp/server.py", "mcp/server.py", "./tests/regression/test_quotes.py", SERVER[:-1]),
            ("BUILD -- view/build_view.py", "view/build_view.py", "./tests/regression/test_quotes.py", SERVER[-1:]),
            ("VIEW -- view/build_view.py", "view/build_view.py", "./tests/regression/test_quotes_view.js", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

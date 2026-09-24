#!/usr/bin/env python3
"""Mutation-test completed_on (0.1.43 G1, G2). SERVER mutants in mcp/server.py are graded by
tests/regression/test_completed.py: a dated, operator-owned project field,
refused when unreadable or in the future (through the frozen clock), warned
about before the deal date, touching neither the bucket nor the collection
status. Its carry-over on a re-import is graded with the rest of
OPERATOR_ONLY by tests/mutate_operator_only.py. G2 adds next_action_due's
named exception (a completed job is not due) to the server set, and a VIEW set
in view/build_view.py graded by tests/regression/test_completed_view.js through
the real click path: Mark complete, the Completed list, Reopen, the drawer.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
T_COMPLETED = "./tests/regression/test_completed.py"
T_VIEW = "./tests/regression/test_completed_view.js"

_GATE = ("        readable = isinstance(v, str) and bool(_NEXT_ACTION_DATE_RE.fullmatch(v.strip()))\n"
         "        if not (readable and _parse_date_loose(v)):\n")

SERVER = [
 ("completed_on stops being a project field",
  '    "completed_on",\n}', '}'),
 ("null is refused, so nothing can be reopened",
  '    if "completed_on" in fields and fields["completed_on"] is not None:\n'
  '        v = fields["completed_on"]\n',
  '    if "completed_on" in fields:\n'
  '        v = fields["completed_on"]\n'),
 ("an unreadable date is stored",
  _GATE, _GATE.replace("readable and _parse_date_loose(v)", "readable")),
 ("the date gate accepts whatever strptime accepts",
  _GATE, _GATE.replace("readable and _parse_date_loose(v)",
                       "isinstance(v, str) and _parse_date_loose(v)")),
 ("the refusal does not name the value",
  '                             f"or null, not {v!r}")', '                             f"or null")'),
 ("a future completion is saved",
  "    if done > _today():\n", "    if False:\n"),
 ("today is refused (>= for >)",
  "    if done > _today():\n", "    if done >= _today():\n"),
 ("the future test reads the wall clock instead of the hook",
  "    if done > _today():\n", "    if done > datetime.now().date():\n"),
 ("the future refusal does not name today",
  '        raise StoreError(f"completed_on {v} is after today ({_today().isoformat()}) "',
  '        raise StoreError(f"completed_on {v} is after today "'),
 ("no warning before the deal date",
  "    if deal and done < deal.date():\n", "    if False:\n"),
 ("a completion before the deal date is refused instead of warned",
  "    if deal and done < deal.date():\n",
  "    if deal and done < deal.date():\n"
  "        raise StoreError(f\"completed_on {v} is before the deal date {record.get('date')}\")\n"),
 ("the warning does not name the deal date",
  "                f\"{record.get('date')} -- saved as given; check both dates\"]",
  "                f\"-- saved as given; check both dates\"]"),
 ("an unrelated edit repeats the warning",
  '    v = fields.get("completed_on")\n    if v is None:\n        return []\n',
  '    v = record.get("completed_on")\n    if v is None:\n        return []\n'),
 ("update_project skips the completion checks",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = []\n"),
 ("create_project skips the completion checks",
  "            warnings = _check_completed(record, fields)\n",
  "            warnings = []\n"),
 ("update_project drops the warnings from its response",
  '            if warnings:\n                out["warnings"] = warnings\n            if new_cid != old_cid:',
  '            if new_cid != old_cid:'),
 ("marking complete clears the Live Tracker bucket",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n"
  "            if fields.get(\"completed_on\"):\n"
  "                fields[\"tracker_status\"] = None\n"),
 ("marking complete marks it paid",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n",
  "            warnings = _check_completed(dict(target[0], **fields), fields)\n"
  "            if fields.get(\"completed_on\"):\n"
  "                fields[\"collection_status\"] = \"paid\"\n"),
 # G2: next_action_due, the named exception
 ("a completed project is still due",
  "                and not p.get(\"archived\") \\\n"
  "                and not _is_completed(p)", "                and not p.get(\"archived\")"),
 # re-anchored review round 1: _is_completed / isCompleted read a non-blank STRING only
 ("a blank completed_on counts as complete",
  '    return isinstance(v, str) and v.strip() != ""', '    return isinstance(v, str)'),
 ("completion is read as truthiness, so '  ' is complete",
  '    return isinstance(v, str) and v.strip() != ""', '    return bool(v)'),
 ("a completed_on that is not a string counts as complete (round 1)",
  '    return isinstance(v, str) and v.strip() != ""', '    return v is not None and str(v).strip() != ""'),
 ("the list_projects description drops the completed exclusion (round 1)",
  "    archived, status not lost, not completed (completed_on set) -- \"what is\n",
  "    archived, status not lost -- \"what is\n"),
]

# G2: the Live screen, graded through the real click path on a live server
VIEW = [
 ("a completed job stays on the Live screen",
  "st(p.tracker_status) && !isCompleted(p) && liveMatches(p, q))",
  "st(p.tracker_status) && liveMatches(p, q))"),
 # re-anchored review round 1: _is_completed / isCompleted read a non-blank STRING only
 ("isCompleted reads a blank as complete",
  "function isCompleted(p){ const v = p && p.completed_on; return typeof v === 'string' && v.trim() !== ''; }",
  "function isCompleted(p){ const v = p && p.completed_on; return typeof v === 'string'; }"),
 ("isCompleted reads a non-string as complete (round 1)",
  "function isCompleted(p){ const v = p && p.completed_on; return typeof v === 'string' && v.trim() !== ''; }",
  "function isCompleted(p){ return st(p && p.completed_on).trim() !== ''; }"),
 ("demo mode finds a project by number alone (round 1)",
  "    && (cid == null || String(x.company_id) === String(cid)));", "    );"),
 ("the Completed list is oldest first",
  "return a.iso < b.iso ? 1 : -1; }", "return a.iso < b.iso ? -1 : 1; }"),
 ("the date does not default to today",
  "  if(inp && !inp.value) inp.value = todayISO();\n", ""),
 ("the card moves on a refusal too (optimistic)",
  "  if(!r || !r.ok){\n    if(msgEl){ msgEl.textContent = '\\u2717 ' + ((r && r.error) || 'not saved'); }\n    return false;\n  }\n",
  "  if(!r || !r.ok){\n    if(msgEl){ msgEl.textContent = '\\u2717 ' + ((r && r.error) || 'not saved'); }\n  }\n"),
 ("the refusal is not shown",
  "    if(msgEl){ msgEl.textContent = '\\u2717 ' + ((r && r.error) || 'not saved'); }\n",
  "    if(msgEl){ msgEl.textContent = ''; }\n"),
 ("the local record is found by number alone, across customers",
  "  const p = (DATA.projects||[]).find(x=>st(x.project_no)===st(pno) && st(x.company_id)===st(cid));\n  if(p) Object.assign(p, r.project || {completed_on: value});",
  "  const p = (DATA.projects||[]).find(x=>st(x.project_no)===st(pno));\n  if(p) Object.assign(p, r.project || {completed_on: value});"),
 ("the sidebar is not repainted after a save",
  "  renderList(); renderMain();\n  return true;", "  renderMain();\n  return true;"),
 ("a numberless job is offered Mark complete",
  "    ${hasProjectNo(p) ? `<div class=\"lt-done\" hidden>", "    ${true ? `<div class=\"lt-done\" hidden>"),
 ("a numberless job is offered the Mark complete button",
  ": `<span class=\"muted nw\">${esc(NO_NUMBER_LIVE_NOTE)}</span>`}</span>",
  ": `<button class=\"pill-btn\" data-act=\"complete\" onclick=\"startComplete('${jesc(st(p.company_id))}','')\">Mark complete</button><span class=\"muted nw\">${esc(NO_NUMBER_LIVE_NOTE)}</span>`}</span>"),
 ("the numberless card does not say why",
  "'no number \\u2014 give it one in chat to edit here; it cannot be marked complete until then'",
  "'no number \\u2014 give it one in chat to edit here'"),
 ("Reopen sends an empty string instead of null",
  "  return setCompleted(cid, pno, null, row && row.querySelector('.lt-done-msg'),",
  "  return setCompleted(cid, pno, '', row && row.querySelector('.lt-done-msg'),"),
 ("the Completed count is dropped",
  '<span class="muted">${done.length} completed</span>', '<span class="muted"></span>'),
 ("collection status is not shown on a completed job",
  "Collection: ${coll ? esc(coll) : 'not set'}", "${''}"),
 ("leg stages are not shown on a completed job",
  "  const stages = r.legs.map(l=>`<span class=\"badge b-stage\">${esc(st(l.stage)||'no stage')}</span>`).join(' ')",
  "  const stages = [].join(' ')"),
 ("the drawer does not show completed_on",
  "${dateInput('f_done', p.completed_on)}", "${dateInput('f_done', null)}"),
 ("the drawer never sends a corrected completed_on",
  "  dateIfChanged('f_done', fields, 'completed_on');     // and for \"completed on\"\n", ""),
]

def main():
    worst = 0
    for title, test, target, mutants in (
            ("SERVER -- mcp/server.py", T_COMPLETED, "mcp/server.py", SERVER),
            ("VIEW -- view/build_view.py", T_VIEW, "view/build_view.py", VIEW)):
        print(f"\n=== {title}  ({len(mutants)} mutants) ===")
        worst = max(worst, mutate(SRC, test, target, mutants))
    return worst


sys.exit(main())

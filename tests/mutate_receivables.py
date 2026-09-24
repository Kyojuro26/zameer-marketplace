#!/usr/bin/env python3
"""Mutation-test tests/regression/test_receivables.js.

Every number on the Receivables screen is DERIVED -- outstanding, days late,
which bucket -- so a wrong answer here looks entirely plausible. These mutants
are the plausible wrong answers.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "view/build_view.py"

M = [
 # ---- the money ---------------------------------------------------------
 ("partial % read as UNPAID rather than received",
  "    if(paidPct >= 0 && paidPct <= 100) return Math.round(amt * (1 - paidPct/100));",
  "    if(paidPct >= 0 && paidPct <= 100) return Math.round(amt * (paidPct/100));"),
 ("a missing amount becomes zero instead of null",
  "  const amt = invoiceAmount(v); if(amt == null) return null;",
  "  const amt = invoiceAmount(v); if(amt == null) return 0;"),
 ("an unlinked invoice is given an amount of zero",
  "  const pno = st(v.project_no).trim(); if(!pno) return null;",
  "  const pno = st(v.project_no).trim(); if(!pno) return 0;"),
 ("the amount ignores which company the project belongs to",
  """  const p = DATA.projects.find(x => st(x.project_no).trim() === pno
                                 && st(x.company_id) === st(v.company_id));""",
  "  const p = DATA.projects.find(x => st(x.project_no).trim() === pno);"),
 ("a paid invoice still shows its full value outstanding",
  "  if(ps.startsWith('paid')) return 0;\n  const amt = invoiceAmount(v);",
  "  const amt = invoiceAmount(v);"),
 ("a project with no revenue is counted as zero",
  "  if(!p || p.revenue == null || String(p.revenue).trim() === '' || isNaN(Number(p.revenue))) return null;",
  "  if(!p) return null;\n  if(p.revenue == null) return 0;"),

 # ---- lateness and bucketing --------------------------------------------
 ("days late can go negative for a future invoice",
  "  return n > 0 ? n : 0;", "  return n;"),
 ("paid invoices fall into the overdue bucket",
  "  if(st(v.payment_status).startsWith('paid')) return 'Paid';\n", ""),
 ("an unreadable date is treated as overdue rather than unknown",
  "  if(!d) return 'No due date';", "  if(!d) return 'Overdue';"),
 ("the due-this-week window is dropped",
  "  if(d <= soon) return 'Due this week';\n", ""),
 ("the company page gets its own copy of the bucket rule",
  "    const bucketOf = (v)=> invoiceBucket(v, todayStr, soonStr);",
  "    const bucketOf = (v)=> st(v.payment_status).startsWith('paid') ? 'Paid'\n"
  "      : (dueOn(v) && dueOn(v) < todayStr ? 'Overdue' : 'Due later');"),

 # ---- ordering and totals -----------------------------------------------
 ("newest debt is listed first instead of oldest",
  "    if(ad!==bd) return ad.localeCompare(bd);",
  "    if(ad!==bd) return bd.localeCompare(ad);"),
 ("the total silently counts unpriced invoices as zero",
  "  const known = rows.filter(r => r.owed != null);",
  "  const known = rows.map(r => ({owed: r.owed || 0}));"),
 ("the total stops saying what it excludes",
  """      [unknown ? `excludes ${unknown} invoice${unknown>1?'s':''} with no amount on file` : '',""",
  """      ['',"""),
 ("the view opens on Paid rather than Overdue",
  "let recvBucket = 'Overdue';", "let recvBucket = 'Paid';"),

 # ---- presentation that carries meaning ---------------------------------
 ("an unparseable date renders blank instead of as stored",
  "  if(!iso) return t;                       // unparseable: show what is stored",
  "  if(!iso) return '';"),
 ("dates render raw again, so two formats reappear in one column",
  "      <td class=\"num\">${esc(fmtDate(r.due)||'—')}</td>",
  "      <td class=\"num\">${esc(st(r.due)||'—')}</td>"),
 ("a stored status string is shown to the operator raw",
  "  if(low.startsWith('partial')) return `<span class=\"badge b-pending\">Part paid${m?' '+m[1]+'%':''}</span>`;",
  "  if(low.startsWith('partial')) return `<span class=\"badge b-pending\">${esc(s)}</span>`;"),
 ("an unlinked invoice shows an empty project cell",
  "      : '<span class=\"badge b-stage\">Not linked</span>';", "      : '';"),

 # ---- the server's shape (0.1.36) -------------------------------------------
 ("the tile falls back to its own project sum when there is no shape",
  "  const recvN = ex && ex.value != null ? money(ex.value) : '\\u2014';",
  "  const recvN = ex && ex.value != null ? money(ex.value)\n"
  "    : money(curProjects.filter(p=>{const c=st(p.collection_status);return c && c!=='paid';}).reduce((a,p)=>a+num(p.revenue),0));"),
 ("a ledger with nothing counted renders $0",
  "  if(!out.counted) out.value = null;          // nothing counted is not $0",
  "  if(!out.counted) out.value = 0;"),
 ("the tile drops its denominator",
  "  const recvL = ex ? `Open receivables \\u00b7 ${ex.counted} of ${ex.population} invoice${ex.population===1?'':'s'} priced`",
  "  const recvL = ex ? `Open receivables`"),
 ("the population is summed from counted alone",
  "    out.counted += n(s.counted); out.population += n(s.population);",
  "    out.counted += n(s.counted); out.population += n(s.counted);"),
 ("exclusions are not carried into the ledger tally",
  "    Object.keys(s.excluded||{}).forEach(k => {\n"
  "      out.excluded[k] = (out.excluded[k]||0) + n(s.excluded[k]); });",
  ""),
 ("the header keeps its own bucket total instead of the server's figure",
  # re-anchored 0.1.38: the line now also carries ${quoted}, the label B3 adds
  # when a QuickBooks figure leads the header -- same decision, same line
  "        : `<span class=\"muted\">· ${money(ex.value)} outstanding${quoted} across ${esc(shapeCaveat(ex))}</span>`)",
  "        : `<span class=\"muted\">· ${money(total)} outstanding${quoted}</span>`)"),
 ("the page is built without the server's shapes",
  "    _attach_metrics(data, store_dir)\n", ""),
 ("build-time shapes come from a copy of the rule, not the server's builder",
  "        ctx = _srv._MetricsCtx()\n"
  "        data[\"companies\"] = [dict(c, metrics=ctx.company_metrics(c))\n"
  "                             for c in data[\"companies\"]]",
  "        data[\"companies\"] = [dict(c, metrics={\"exposure_open_receivable_usd\": {\n"
  "            \"value\": sum(float(p.get(\"revenue\") or 0) for p in data[\"projects\"]\n"
  "                         if p.get(\"company_id\") == c.get(\"company_id\")),\n"
  "            \"unit\": \"usd\", \"counted\": 1, \"population\": 1, \"excluded\": {}, \"basis\": \"b\"}})\n"
  "                             for c in data[\"companies\"]]"),

 ("a save no longer refreshes the shapes",
  "      refreshMetrics();     // the server's shapes predate this write\n", ""),
 ("the refresh replaces the company record instead of copying its metrics",
  "        if(fresh && fresh.metrics) c.metrics = fresh.metrics; else delete c.metrics;",
  "        if(fresh) Object.assign(c, fresh); else delete c.metrics;"),
 ("a failed refresh keeps the stale shapes",
  "    .catch(() => { DATA.companies.forEach(c => { delete c.metrics; }); })",
  "    .catch(() => {})"),
 ("row pricing compares project keys untrimmed",
  "  const p = DATA.projects.find(x => st(x.project_no).trim() === pno",
  "  const p = DATA.projects.find(x => st(x.project_no) === pno"),
 ("an empty-string revenue prices as $0 on the row",
  "  if(!p || p.revenue == null || String(p.revenue).trim() === '' || isNaN(Number(p.revenue))) return null;",
  "  if(!p || p.revenue == null || isNaN(Number(p.revenue))) return null;"),

 # ---- the company headline and the sidebar read the shape --------------
 ("the company headline goes back to the view's own sum",
  "  const m = c.metrics, sh = m && m.exposure_open_receivable_usd, od = m && m.oldest_overdue_days;",
  "  const m = c.metrics, od = m && m.oldest_overdue_days;\n"
  "  const sh = (()=>{ const invs=(invoicesByCo[c.company_id]||[]).filter(v=>!st(v.payment_status).startsWith('paid'));"
  " const known=invs.map(outstanding).filter(x=>x!=null);"
  " return {value: known.reduce((a,b)=>a+b,0), counted: invs.length, population: invs.length, excluded: {}}; })();"),
 ("nothing priced falls through to a dash figure instead of saying so",
  "  if(!sh.counted){\n    // Nothing priced is not $0.",
  "  if(false){\n    // Nothing priced is not $0."),
 ("the headline drops its denominator",
  "    <span class=\"muted\">· ${esc(shapeCaveat(sh))}</span>\n    ${late} ${see}\n  </p>`;",
  "    ${late} ${see}\n  </p>`;"),
 ("a company with no shape is shown as having nothing to say",
  "    return `<p class=\"co-sum\"><span class=\"muted\">needs the server · what this customer owes is a server figure, and this page has none for it</span> ${see}</p>`;",
  "    return '';"),
 ("the sidebar goes back to its own sum",
  "    const cm=c.metrics, csh=cm&&cm.exposure_open_receivable_usd, cod=cm&&cm.oldest_overdue_days;",
  "    const cm=c.metrics, cod=cm&&cm.oldest_overdue_days;\n"
  "    const csh=(()=>{ const invs=(invoicesByCo[c.company_id]||[]).filter(v=>!st(v.payment_status).startsWith('paid'));"
  " const known=invs.map(outstanding).filter(x=>x!=null);"
  " return {value: known.reduce((a,b)=>a+b,0), counted: invs.length, population: invs.length}; })();"),
 ("the sidebar hides how late an unpriced customer is",
  "    const late=cod&&cod.value>0?cod.value:0;",
  "    const late=csh&&csh.counted&&cod&&cod.value>0?cod.value:0;"),
 ("the refresh repaints the tile and nothing else",
  "    .then(() => { metricsRefresh = null; kpis(); renderList();\n"
  "      // the company headline and the Receivables header read the shapes too\n"
  "      if(filter === 'receivable' || (selected && filter !== 'live' && filter !== 'project')) renderMain(); });",
  "    .then(() => { metricsRefresh = null; kpis(); if(filter === 'receivable') renderMain(); });"),

 ("the build ships the invoices and legs of archived projects",
  "    _drop_archived_project_records(data)\n", ""),
 ("the archived-project filter runs after the company scrub, missing an archived customer's numbers",
  "    _drop_archived_project_records(data)\n"
  "    # archived companies never ship into the demo bootstrap\n"
  "    arch = {c[\"company_id\"] for c in data[\"companies\"] if c.get(\"archived\")}\n"
  "    data[\"companies\"] = [c for c in data[\"companies\"] if not c.get(\"archived\")]\n"
  "    for k in [\"contacts\", \"projects\", \"shipments\", \"invoices\"]:\n"
  "        data[k] = [x for x in data[k] if x.get(\"company_id\") not in arch]\n"
  "    data[\"vendors\"] = [v for v in data[\"vendors\"] if not v.get(\"archived\")]\n",
  "    # archived companies never ship into the demo bootstrap\n"
  "    arch = {c[\"company_id\"] for c in data[\"companies\"] if c.get(\"archived\")}\n"
  "    data[\"companies\"] = [c for c in data[\"companies\"] if not c.get(\"archived\")]\n"
  "    for k in [\"contacts\", \"projects\", \"shipments\", \"invoices\"]:\n"
  "        data[k] = [x for x in data[k] if x.get(\"company_id\") not in arch]\n"
  "    data[\"vendors\"] = [v for v in data[\"vendors\"] if not v.get(\"archived\")]\n"
  "    _drop_archived_project_records(data)\n"),
 ("the sidebar goes quiet where the headline says it needs the server",
  "    const needsServer=hasInv&&(!csh||!csh.population), moneyShown=!!(csh&&csh.population);",
  "    const needsServer=!csh&&hasInv, moneyShown=!!(csh&&csh.population);"),
 ("a customer the server lists no invoice for reads as settled",
  "  if(!sh.population) return (invoicesByCo[c.company_id]||[]).length\n"
  "    ? `<p class=\"co-sum\"><span class=\"muted\">needs the server · the server lists no invoice for this customer, so it has no figure for the ones shown below</span> ${see}</p>`\n"
  "    : '';",
  "  if(!sh.population) return '';"),

 # ---- wiring -------------------------------------------------------------
 ("the receivables KPI stops navigating",
  "    [recvL, recvN, 'receivable'],",
  "    [recvL, recvN, null],"),
 ("the KPI is mouse-only",
  """         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setFilter('${jesc(go)}')}\"""",
  '         data-nokeys="1"'),
 ("selecting a company leaves you stranded in the receivables list",
  "  if(filter === 'project' || filter === 'receivable' || filter === 'live' || filter === 'rankings'){ setFilter('all'); fetchEnrichment(id); return; }",
  "  if(filter === 'project' || filter === 'live' || filter === 'rankings'){ setFilter('all'); fetchEnrichment(id); return; }"),
]

sys.exit(mutate(SRC, "./tests/regression/test_receivables.js", F, M))

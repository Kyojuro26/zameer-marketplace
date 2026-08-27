#!/usr/bin/env python3
"""Build the interactive CRM view — a single self-contained HTML file.

    python3 build_view.py --store ../store --out ./unrivaled-crm.html

Wired to the Unrivaled CRM MCP (interface v0.1). The app picks a backend at
startup, in order:

  1. http     — mcp/local_server.py, a token-authenticated localhost server
                (production: this is what "Open Unrivaled CRM" launches)
  2. cowork   — window.cowork.callMcpTool, if a Cowork artifact ever exposes
                it with this plugin's tools allowlisted (not currently
                reachable through any tested Cowork surface as of 2026-07-16
                — kept as a fallback in case that changes)
  3. embedded — the data baked into this file; edits are session-only (demo)

In modes 1–2 every save persists through the MCP's validated write path and
the header pill shows "Live". Embedded data is always rendered instantly as
bootstrap, then replaced by a live refresh when a backend is present.
"""
import argparse, json, os, re, sys

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<!-- Defense in depth: no plugins, no <base> hijack, no framing; block any
     javascript:/external script that slips past output encoding. Inline
     script/style are still permitted (this file is self-contained). -->
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"/>
<title>Unrivaled CRM</title>
<style>
  :root{
    --bg:#f6f7f9; --panel:#ffffff; --ink:#1a2230; --muted:#5a687c; --line:#e4e8ee;
    --accent:#2563eb; --accent-soft:#eaf1ff; --green:#127a4b; --green-soft:#e4f5ec;
    --amber:#8a5a00; --amber-soft:#fdf1dc; --red:#a3282b; --red-soft:#fbe7e7; --slate:#475569;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--ink);font-size:14px;line-height:1.45}
  header{background:var(--panel);border-bottom:1px solid var(--line);padding:14px 20px;
         display:flex;align-items:center;gap:22px;position:sticky;top:0;z-index:5}
  .brand{font-weight:700;font-size:17px;letter-spacing:.2px}
  .brand span{color:var(--accent)}
  .kpis{display:flex;gap:22px;margin-left:auto;flex-wrap:wrap}
  .kpi{text-align:right}
  .kpi .n{font-weight:700;font-size:26px;letter-spacing:-.02em;line-height:1.05;
          font-variant-numeric:tabular-nums}
  .kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .kpi.go{cursor:pointer;border-radius:8px;padding:2px 8px;margin:-2px -8px}
  .kpi.go:hover{background:var(--bg)}
  /* the stylesheet had no :focus rule at all -- a keyboard user could not
     see where they were, which matters more now the drawer holds focus */
  :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
  .wrap{display:grid;grid-template-columns:320px 1fr;gap:0;height:calc(100vh - 59px)}
  .sidebar{border-right:1px solid var(--line);background:var(--panel);overflow-y:auto}
  .search{padding:12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
  .search input{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font-size:13px}
  .filters{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
  .subfilters{margin-top:8px;display:none;flex-direction:column;gap:6px}
  .sfrow{display:flex;gap:5px;align-items:center;flex-wrap:wrap}
  .sfrow .sfl{color:var(--muted);font-size:11px;min-width:64px}
  .sfrow button{flex:0 1 auto;padding:4px 8px;border:1px solid var(--line);background:#fff;
                border-radius:6px;font-size:11px;cursor:pointer;color:var(--muted);white-space:nowrap}
  .sfrow button.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:600}
  th.sortable{cursor:pointer;user-select:none}
  th.sortable:hover{color:var(--accent)}
  /* content-sized, not flex:1 with a min-width. The old rule pinned every
     button to 56px and let the LABEL overflow it, which is why "Projects" sat
     alone on a full-width second row and "Receivables" ran off the edge on a
     narrow window. */
  .filters button{flex:0 1 auto;padding:6px 10px;border:1px solid var(--line);background:#fff;
                  border-radius:7px;font-size:12px;cursor:pointer;color:var(--muted);
                  white-space:nowrap}
  .filters button.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:600}
  .clist{padding:6px}
  .citem{padding:9px 11px;border-radius:8px;cursor:pointer}
  .citem:hover{background:var(--bg)}
  .citem.sel{background:var(--accent-soft)}
  .citem .cn{font-weight:600}
  .citem .cm{color:var(--muted);font-size:12px;display:flex;gap:8px;margin-top:2px;flex-wrap:wrap}
  .citem .owed{color:var(--red);font-weight:600}
  .main{overflow-y:auto;padding:22px 26px}
  .muted{color:var(--muted)}
  .empty{color:var(--muted);text-align:center;margin-top:16vh}
  .co-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .co-head h1{font-size:22px;margin:0}
  .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;text-transform:capitalize;white-space:nowrap;display:inline-block}
  .b-customer{background:var(--accent-soft);color:var(--accent)}
  .b-vendor{background:#eef0f3;color:var(--slate)}
  .b-lead{background:var(--amber-soft);color:var(--amber)}
  .b-open{background:var(--accent-soft);color:var(--accent)}
  /* Live Tracker. The swatches echo the sheet's own colours so the grouping
     reads the way it does in Excel, without reproducing the raw magenta. */
  .b-admin{background:#fbe4f7;color:#8a2378}
  .b-owner{background:#fdf3d0;color:#7a5a00}
  .b-await{background:#dff2f6;color:#0f5f70}
  .swatch{width:10px;height:10px;border-radius:3px;display:inline-block;flex:none}
  .swatch.b-admin{background:#c0389f} .swatch.b-owner{background:#e0a800}
  .swatch.b-await{background:#2296ad} .swatch.b-stage{background:var(--muted)}
  .lt-head{display:flex;align-items:center;gap:9px;margin:0 0 10px;
           border-bottom:1px solid var(--line);padding-bottom:6px}
  .lt-head h2{font-size:13.5px;font-weight:650;color:var(--ink)}
  .lt-card{border:1px solid var(--line);border-radius:10px;background:var(--panel);
           padding:12px 14px;margin-bottom:10px}
  .lt-card.lt-unlinked{border-style:dashed}
  .lt-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13.5px}
  /* the note is the substance of this screen -- never truncated, wraps freely */
  .lt-note{margin:8px 0 0;font-size:13.5px;line-height:1.5;white-space:pre-wrap}
  .lt-legs{margin-top:9px;display:flex;flex-direction:column;gap:4px}
  .lt-leg{display:flex;gap:10px;align-items:center;font-size:12.5px;flex-wrap:wrap}
  .lt-po{color:var(--muted);min-width:190px}
  .lt-bad{color:var(--red);font-weight:600}
  .lt-warn{color:var(--amber);font-weight:600}
  .due-group{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);
             padding:10px 8px 4px;border-bottom:1px solid var(--line)}
  .due-group.od{color:var(--red)}
  .b-won{background:var(--green-soft);color:var(--green)}
  .b-pending{background:var(--amber-soft);color:var(--amber)}
  .b-lost{background:var(--red-soft);color:var(--red)}
  .b-stage{background:#eef0f3;color:var(--slate)}
  .section{margin-top:22px}
  /* was 12px uppercase muted -- SMALLER than the body text it headed, so a
     section title read as quieter than its own contents */
  .section h2{font-size:13.5px;font-weight:650;letter-spacing:-.005em;color:var(--ink);
              margin:0 0 8px;border-bottom:1px solid var(--line);padding-bottom:6px;
              text-transform:none}
  .co-sum{margin:2px 0 4px;font-size:13.5px;display:flex;gap:8px;flex-wrap:wrap;align-items:baseline}
  .co-sum .late{color:var(--red)}
  .co-sum .ok{color:var(--green);font-weight:600}
  .co-sum a{color:var(--muted);text-decoration:underline;text-underline-offset:2px}
  .empty-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 0;color:var(--muted)}
  .pill-btn.pri{background:var(--accent);color:#fff}
  .pill-btn.ghost{background:transparent;color:var(--muted);font-size:15px;line-height:1;padding:5px 9px}
  .pill-btn.ghost:hover{background:var(--bg);color:var(--ink)}
  .more{position:relative;display:inline-block}
  .more-menu{display:none;position:absolute;right:0;top:calc(100% + 6px);z-index:22;
             background:var(--panel);border:1px solid var(--line);border-radius:9px;
             box-shadow:0 8px 24px rgba(20,30,50,.14);padding:5px;min-width:190px}
  .more.show .more-menu{display:block}
  .more-menu button{display:block;width:100%;text-align:left;border:0;background:none;
                    font:inherit;font-size:13px;color:var(--ink);padding:7px 10px;
                    border-radius:6px;cursor:pointer;white-space:nowrap}
  .more-menu button:hover{background:var(--bg)}
  .more-menu button.danger{color:var(--red)}
  .more-menu button.danger:hover{background:var(--red-soft)}
  tfoot td{border-top:1px solid var(--line);border-bottom:0;font-weight:650;padding-top:10px}
  .nw{white-space:nowrap}
  /* The stylesheet had no breakpoint at all: at 1024px table cells wrapped
     mid-value and below ~700px the sidebar and main pane fought for width. */
  @media (max-width:900px){
    .wrap{grid-template-columns:1fr;height:auto}
    .sidebar{border-right:0;border-bottom:1px solid var(--line);max-height:42vh}
    .main{height:auto}
    header{flex-wrap:wrap;gap:10px}
    .kpis{margin-left:0;gap:14px;width:100%}
    .kpi .n{font-size:20px}
    .co-head h1{font-size:19px}
  }
  table{width:100%;border-collapse:collapse}
  .section{overflow-x:auto}
  th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);
     padding:6px 8px;border-bottom:1px solid var(--line)}
  td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
  tr.click{cursor:pointer}
  tr.click:hover{background:var(--bg)}
  .contact a{color:var(--accent);text-decoration:none}
  .contact a:hover{text-decoration:underline}
  .num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
  .drawer{position:fixed;top:0;right:0;width:440px;max-width:92vw;height:100vh;background:var(--panel);
          border-left:1px solid var(--line);box-shadow:-8px 0 24px rgba(20,30,50,.08);
          transform:translateX(100%);transition:transform .18s ease;z-index:20;overflow-y:auto}
  .drawer.open{transform:none}
  /* Sits between the page (z<19) and the drawer (z=20). Clicking it closes the
     drawer, and it also blocks clicks reaching the page underneath -- without
     it, clicking a company in the sidebar switched the main panel while the
     drawer stayed open still editing the PREVIOUS company's record. */
  .scrim{position:fixed;inset:0;background:rgba(20,30,50,.28);opacity:0;
         pointer-events:none;transition:opacity .18s ease;z-index:19}
  .scrim.open{opacity:1;pointer-events:auto}
  .drawer .dh{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
  .drawer .db{padding:20px}
  .drawer h3{margin:0;font-size:17px}
  .x{cursor:pointer;color:var(--muted);font-size:20px;border:none;background:none}
  .field{margin-bottom:14px}
  .field label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);margin-bottom:4px}
  .field input,.field select,.field textarea{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;font-size:13px;font-family:inherit}
  .field textarea{min-height:70px;resize:vertical}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .btn{background:var(--accent);color:#fff;border:none;padding:9px 16px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px}
  .btn:disabled{opacity:.55;cursor:wait}
  .btn.ghost{background:#fff;color:var(--slate);border:1px solid var(--line)}
  .saved{font-size:12px;margin-left:10px;opacity:0;transition:opacity .2s}
  .saved.show{opacity:1}
  .saved.okc{color:var(--green)}
  .saved.errc{color:var(--red)}
  .kv{display:flex;gap:8px;margin:4px 0;font-size:13px}
  .kv .k{color:var(--muted);min-width:110px}
  .pill-btn{background:var(--accent-soft);color:var(--accent);border:none;padding:5px 10px;border-radius:7px;
            font-size:12px;font-weight:600;cursor:pointer}
  .mvp{position:fixed;bottom:12px;left:12px;background:#111827;color:#cbd5e1;font-size:11px;
       padding:6px 10px;border-radius:6px;opacity:.9;z-index:30}
  .mvp.live{background:#0c5132;color:#d3f4e2}
</style>
</head>
<body>
<header id="apphdr">
  <div class="brand">Unrivaled <span>CRM</span></div>
  <div class="kpis" id="kpis"></div>
</header>
<div class="wrap" id="appwrap">
  <aside class="sidebar">
    <div class="search">
      <input id="q" placeholder="Search companies, contacts, projects, invoice #, vendor PO…" autocomplete="off"/>
      <div class="filters" id="filters">
        <button data-f="live" class="on">Live</button>
          <button data-f="all">All</button>
        <button data-f="customer">Customers</button>
        <button data-f="vendor">Vendors</button>
        <button data-f="lead">Leads</button>
        <button data-f="project">Projects</button>
          <button data-f="receivable">Receivables</button>
      </div>
      <div class="subfilters" id="subfilters">
        <div class="sfrow" id="sf_status"><span class="sfl">Status</span></div>
        <div class="sfrow" id="sf_year"><span class="sfl">Year</span></div>
        <div class="sfrow" id="sf_coll"><span class="sfl">Collection</span></div>
      </div>
      <div class="addrow" id="addrow" style="display:none;gap:6px;margin-top:8px">
        <button class="pill-btn" style="flex:1" onclick="openNewCompany('customer')">+ Add customer</button>
        <button class="pill-btn" style="flex:1" onclick="openNewCompany('vendor')">+ Add vendor</button>
        <button class="pill-btn" style="flex:1" onclick="openNewCompany('lead')">+ Add lead</button>
      </div>
    </div>
    <div class="clist" id="clist"></div>
  </aside>
  <main class="main" id="main"><div class="empty">Select a company to begin.</div></main>
</div>
<div class="scrim" id="scrim"></div>
<div class="drawer" id="drawer" tabindex="-1"><div class="dh"><h3 id="dtitle"></h3><button class="x" id="drawerX" onclick="requestCloseDrawer()">&times;</button></div><div class="db" id="dbody"></div></div>
<div class="mvp" id="modePill">Connecting…</div>

<script>
const DATA = __DATA__;

/* ---------------- CRM client: cowork MCP -> dev bridge -> embedded demo -- */
// Cowork names installed-plugin tools mcp__plugin_<plugin>_<server>__<tool>;
// bare mcp__<server>__ appears in dev / non-plugin contexts. Probe at startup
// instead of hardcoding — a wrong guess must degrade to Demo, never fake Live.
const TOOL_PREFIX_CANDIDATES = [
  'mcp__plugin_unrivaled-solutions_unrivaled-crm__',
  'mcp__unrivaled-crm__',
];
let TOOL_PREFIX = null;
let SERVER_VERSION = null;
const BRIDGE = '';  // same-origin: the local app server serves this page itself
const BRIDGE_TOKEN = '__BRIDGE_TOKEN__';  // per-launch secret; local_server.py fills this in

const CRM = {
  mode: 'embedded',
  async probeCowork(){
    for (const p of TOOL_PREFIX_CANDIDATES){
      try{
        const r = await window.cowork.callMcpTool(p + 'crm_info', {});
        if (r && !r.isError){
          const body = r.structuredContent ?? JSON.parse(r.content[0].text);
          // crm_info reports ok:false when a store file is degraded — that is
          // still a live server; only a non-answer means the prefix is wrong.
          if (body && (body.interface_version || body.server_version)){
            TOOL_PREFIX = p;
            SERVER_VERSION = body.server_version || body.version || null;
            return true;
          }
        }
      }catch(e){ /* try next candidate */ }
    }
    console.warn('cowork present but no CRM tool prefix answered crm_info; staying in demo mode');
    return false;
  },
  async detect(){
    if (window.cowork && window.cowork.callMcpTool){
      if (await this.probeCowork()) this.mode = 'cowork';
    }
    else {
      try{
        const c = new AbortController(); setTimeout(()=>c.abort(), 1200);
        const r = await fetch(BRIDGE + '/health', {signal: c.signal,
          headers:{'X-Bridge-Token': BRIDGE_TOKEN}});
        if (r.ok && (await r.json()).ok) this.mode = 'http';
      }catch(e){ /* stay embedded */ }
    }
    setModePill();
    if (this.mode !== 'embedded') await refreshData();
  },
  async call(tool, args){
    if (this.mode === 'cowork'){
      const r = await window.cowork.callMcpTool(TOOL_PREFIX + tool, args || {});
      if (r.isError) return {ok:false, error:(r.content && r.content[0] && r.content[0].text) || 'MCP error'};
      return r.structuredContent ?? JSON.parse(r.content[0].text);
    }
    if (this.mode === 'http'){
      const r = await fetch(BRIDGE + '/call', {method:'POST',
        headers:{'Content-Type':'application/json', 'X-Bridge-Token': BRIDGE_TOKEN},
        body: JSON.stringify({tool, args: args || {}})});
      if (r.status === 401) return {ok:false, error:'bridge auth rejected — reopen the app from its desktop shortcut'};
      return await r.json();
    }
    return embeddedCall(tool, args || {});
  }
};

function demoSlug(s){ return (s||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,''); }
function embeddedCall(tool, args){   // demo fallback — session-only mutation
  const f = args.fields || {};
  if (tool === 'update_project'){
    const p = DATA.projects.find(x => String(x.project_no) === String(args.project_no));
    if (!p) return {ok:false, error:'project not found'};
    Object.assign(p, args.fields); return {ok:true, project:p};
  }
  if (tool === 'update_shipment'){
    const s = DATA.shipments.find(x => x.shipment_id === args.shipment_id);
    if (!s) return {ok:false, error:'shipment not found'};
    Object.assign(s, args.fields); return {ok:true, shipment:s};
  }
  if (tool === 'update_company'){
    const c = companyById[args.company_id]; if(!c) return {ok:false,error:'company not found'};
    Object.assign(c, args.fields); return {ok:true, company:c};
  }
  if (tool === 'create_company'){
    if(!f.display_name) return {ok:false, error:'display_name is required'};
    const cid = f.company_id || demoSlug(f.display_name);
    if(DATA.companies.some(c=>c.company_id===cid)) return {ok:false, error:"company '"+cid+"' already exists"};
    return {ok:true, company:{company_id:cid, display_name:f.display_name, role:f.role||'customer',
      domains:[], locations:f.locations||[], primary_location:f.primary_location||null, archived:false}};
  }
  if (tool === 'create_vendor'){
    if(!f.display_name) return {ok:false, error:'display_name is required'};
    const cid = f.company_id || demoSlug(f.display_name);
    if((DATA.vendors||[]).some(v=>v.company_id===cid)) return {ok:false, error:"vendor '"+cid+"' already exists"};
    return {ok:true, vendor:Object.assign({company_id:cid, archived:false, po_routing_source:'manual'}, f)};
  }
  if (tool === 'update_vendor'){
    const v = vendorById[args.company_id] || {company_id:args.company_id};
    return {ok:true, vendor:Object.assign({}, v, args.fields)};
  }
  if (tool === 'create_invoice'){
    const no = String((f.invoice_no ?? '')).trim();
    if(!no) return {ok:false, error:'invoice_no is required'};
    if((DATA.invoices||[]).some(x=>x.company_id===args.company_id && st(x.invoice_no)===no))
      return {ok:false, error:"invoice '"+no+"' already exists for this customer"};
    const pn = String((f.project_no ?? '')).trim();
    if(pn && !DATA.projects.some(p=>st(p.project_no)===pn))
      return {ok:false, error:"project '"+pn+"' not found"};
    const co = companyById[args.company_id] || {};
    return {ok:true, invoice: Object.assign({}, f, {invoice_no:no,
      company_id:args.company_id, project_no: pn || null,
      payment_status: f.payment_status || 'open',
      client_name: f.client_name || co.display_name || null})};
  }
  if (tool === 'update_invoice'){
    const inv = (DATA.invoices||[]).find(x=>x.company_id===args.company_id && String(x.invoice_no)===String(args.invoice_no));
    if(!inv) return {ok:false, error:'invoice not found'};
    return {ok:true, invoice:Object.assign({}, inv, args.fields)};
  }
  if (tool === 'rename_project'){
    if(DATA.projects.some(p=>String(p.project_no)===String(args.new_project_no) && String(p.project_no)!==String(args.old_project_no)))
      return {ok:false, error:"project '"+args.new_project_no+"' already exists"};
    const p = DATA.projects.find(x=>String(x.project_no)===String(args.old_project_no));
    if(!p) return {ok:false, error:'project not found'};
    return {ok:true, project:Object.assign({}, p, {project_no:args.new_project_no}),
      shipments_updated:0, invoices_updated:0};
  }
  if (tool === 'archive_project' || tool === 'restore_project'){
    return {ok:true, project:{project_no:args.project_no, archived: tool==='archive_project'}};
  }
  if (tool === 'convert_lead'){
    const c = companyById[args.company_id];
    if(!c) return {ok:false, error:'company not found'};
    if(c.role !== 'lead') return {ok:false, error:'not currently a lead'};
    return {ok:true, company:Object.assign({}, c, {role:'customer'})};
  }
  if (tool === 'reassign_shipment'){
    const s = DATA.shipments.find(x=>x.shipment_id===args.shipment_id);
    if(!s) return {ok:false, error:'shipment not found'};
    const pn = args.new_project_no || null;
    return {ok:true, shipment:Object.assign({}, s, {project_no:pn,
      all_project_nos: pn?[pn]:[], linked_to_project: !!pn})};
  }
  if (tool === 'rename_invoice'){
    const list = DATA.invoices||[];
    if(args.new_invoice_no && list.some(x=>x.company_id===args.company_id
        && String(x.invoice_no)===String(args.new_invoice_no)
        && String(x.invoice_no)!==String(args.old_invoice_no)))
      return {ok:false, error:"invoice '"+args.new_invoice_no+"' already exists for this company"};
    const v = list.find(x=>x.company_id===args.company_id && String(x.invoice_no)===String(args.old_invoice_no));
    if(!v) return {ok:false, error:'invoice not found'};
    return {ok:true, invoice:Object.assign({}, v, {invoice_no:args.new_invoice_no}), shipments_updated:0};
  }
  if (tool === 'create_project'){
    if(!f.project_no) return {ok:false, error:'project_no is required'};
    if(DATA.projects.some(p=>String(p.project_no)===String(f.project_no)))
      return {ok:false, error:"project '"+f.project_no+"' already exists"};
    return {ok:true, project:Object.assign({owner:[],annotations:[]}, f)};
  }
  if (tool === 'create_shipment'){
    const n = 1 + DATA.shipments.filter(s=>String(s.project_no)===String(args.project_no)).length;
    const sid = f.shipment_id || (args.project_no+'-L'+n);
    return {ok:true, shipment:Object.assign({shipment_id:sid, project_no:args.project_no,
      stage:'Ordered', linked_to_project:true}, f)};
  }
  if (tool === 'upsert_contact'){
    if(!f.name) return {ok:false, error:'name is required'};
    return {ok:true, contact:Object.assign({}, f)};
  }
  if (tool === 'archive_company' || tool === 'restore_company'){
    return {ok:true, company:{company_id:args.company_id, archived: tool==='archive_company'}};
  }
  return {ok:false, error:'not available in demo mode: ' + tool};
}

async function refreshData(){
  try{
    const [co, ct, pr, sh, iv, tk] = await Promise.all([
      CRM.call('list_companies', {}), CRM.call('find_contacts', {}),
      CRM.call('list_projects', {}),  CRM.call('list_shipments', {}),
      CRM.call('list_invoices', {}),  CRM.call('list_tracker', {})]);
    if (co.ok) DATA.companies = co.companies;
    if (ct.ok) DATA.contacts  = ct.contacts;
    if (pr.ok) DATA.projects  = pr.projects;
    if (sh.ok) DATA.shipments = sh.shipments;
    if (iv && iv.ok) DATA.invoices = iv.invoices;
    // Without these the landing screen refreshed five of its seven inputs: the
    // bucket headings and the whole "Not in the CRM yet" section stayed frozen
    // at page-build time while everything around them updated, so the screen
    // LOOKED freshly refreshed with a third of it stale. Guarded because a
    // server older than this tool returns ok:false, and an older app must not
    // blank the section it cannot refresh.
    if (tk && tk.ok){
      if (Array.isArray(tk.tracker_buckets))  DATA.tracker_buckets  = tk.tracker_buckets;
      if (Array.isArray(tk.tracker_unlinked)) DATA.tracker_unlinked = tk.tracker_unlinked;
    }
    reindex(); kpis(); renderList();
    if (filter === 'project'){ renderSubfilters(); renderMain(); }
    // 'live' is a cross-company view AND the landing screen, so `selected` is
    // null on open -- without this the sidebar repainted from the refreshed
    // store while the cards beside it kept showing the build-time snapshot,
    // indefinitely. ('receivable' has the same gap; left alone here, it is
    // pre-existing and reachable only after an explicit tab switch.)
    else if (filter === 'live') renderMain();
    else if (selected) renderMain();
  }catch(e){
    console.warn('live refresh failed; keeping embedded data', e);
    const el = document.getElementById('modePill');
    if (el){ el.textContent = 'Live · refresh failed — showing last built data'; }
  }
}

function setModePill(){
  const el = document.getElementById('modePill');
  el.textContent = {
    cowork:   'Live · edits persist (CRM MCP' + (SERVER_VERSION ? ' v' + SERVER_VERSION : '') + ')',
    http:     'Live · edits persist (local app)',
    embedded: 'Demo · edits last this browser session only',
  }[CRM.mode];
  el.classList.toggle('live', CRM.mode !== 'embedded');
  const add = document.getElementById('addrow');
  if (add) add.style.display = 'flex';   // add/delete available in every mode (session-only in demo)
}

/* ---------------------------------------------------------- indexes/util -- */
let contactsByCo={}, projectsByCo={}, shipsByCo={}, invoicesByCo={}, companyById={}, vendorById={};
function reindex(){
  // Object.create(null), not {}: a company_id of 'constructor' or
  // '__proto__' otherwise short-circuits onto an inherited member and
  // .push throws. reindex() runs at top level, so that blanked the ENTIRE
  // app, and _slug('Constructor') reaches it with no hostile input.
  const byCo = (arr)=>{const m=Object.create(null);(arr||[]).forEach(x=>{(m[x.company_id]=m[x.company_id]||[]).push(x)});return m;};
  contactsByCo = byCo(DATA.contacts);
  projectsByCo = byCo(DATA.projects);
  shipsByCo    = byCo(DATA.shipments);
  invoicesByCo = byCo(DATA.invoices);
  companyById  = Object.fromEntries(DATA.companies.map(c=>[c.company_id,c]));
  vendorById   = Object.fromEntries((DATA.vendors||[]).map(v=>[v.company_id,v]));
}
const money = (n)=> (n==null||isNaN(n))?'—':'$'+Number(n).toLocaleString(undefined,{maximumFractionDigits:0});
const pct = (n)=> (n==null||isNaN(n))?'—':(Number(n)*100).toFixed(0)+'%';
// Due date for an invoice: the live server computes and sends
// effective_due_on (due_on override, else invoice_date + Net 30). The fallback
// below only runs for embedded/demo mode, where the bootstrap data is the raw
// stored record with no server-side enrichment.
//
// It deliberately mirrors the server's _parse_date_loose rather than using
// `new Date(...)`, which is far more permissive: it accepted "March 14, 2026"
// and "2026/03/14" (which the server refuses to guess at, returning null) and
// turned the Excel serial 45731 into 1970-01-31. The app then showed four
// invoices in the Overdue bucket, one dated 1970, while "who owes us money" in
// chat answered one -- the same store, two different answers about money.
const NET_TERMS_DAYS = 30;
function dueOn(inv){
  if (inv.effective_due_on) return inv.effective_due_on;
  if (inv.due_on) return inv.due_on;
  const iso = isoDate(inv.invoice_date);      // null unless a real calendar date
  if (!iso) return null;
  const d = new Date(iso + 'T00:00:00Z');
  if (isNaN(d)) return null;
  d.setUTCDate(d.getUTCDate() + NET_TERMS_DAYS);
  return d.toISOString().slice(0,10);
}
const esc = (s)=> (s==null?'':String(s)).replace(/[&<>"'`/]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;','/':'&#47;'}[c]));
// JS-string-literal escaper for values placed inside an inline handler arg,
// e.g. onclick="fn('${jesc(x)}')". HTML-entity escaping is WRONG there: the
// browser HTML-decodes the attribute before the JS parser runs, so &#39;
// becomes ' and breaks out. Hex-escape every non-alphanumeric to \xHH, which
// is inert through both the HTML-attribute decode and the JS string parse.
const jesc = (s)=> (s==null?'':String(s)).replace(/[^a-zA-Z0-9_]/g,c=>{
  const h=c.charCodeAt(0); return h<256?'\\x'+h.toString(16).padStart(2,'0'):'\\u'+h.toString(16).padStart(4,'0'); });
// Only allow http(s)/mailto hrefs; neutralize javascript:, data:, etc.
const safeUrl = (u)=>{ const s=String(u||'').trim(); return /^(https?:|mailto:)/i.test(s) ? s : '#'; };

// 'live' is the landing screen: the daily what-is-moving view, not the
// company list. Every other tab is still one click away.
let filter='live', selected=null, query='';
// Projects view (own tab): sub-filter + sort state, independent of the
// company list's own filter/query so switching tabs doesn't lose either.
let projStatus='all', projYear='all', projColl='all';
let projSortKey='project_no', projSortDir=1;

function kpis(){
  // Won/pending/receivables are current-year-only -- a KPI bar showing
  // last year's closed revenue alongside this year's live pipeline reads
  // as one inflated number, not two useful ones. Open shipments and the
  // company count stay all-time: those are current-state counts, not
  // revenue that should reset at year boundary.
  const thisYear = new Date().getFullYear();
  // st()/num(): nothing validates the TYPE of year or revenue, so a project
  // written through chat can hold "2026" and "12000" as strings. `===` then
  // excluded it from every KPI (reading $0 for the year) while the Projects
  // tab, which already coerces, totalled it correctly -- two numbers on the
  // same screen disagreeing by a whole year. And `a + (p.revenue||0)` on a
  // string CONCATENATES: one string revenue turned $17,000 into $120,005,000.
  const num = (v)=>{ const n = Number(v); return isNaN(n) ? 0 : n; };
  const sameYear = (v)=> st(v) === String(thisYear);
  const curProjects = DATA.projects.filter(p=>sameYear(p.year));
  const openShip = DATA.shipments.filter(s=>['Ordered','Shipped','On Hold'].includes(st(s.stage))).length;
  const won = curProjects.filter(p=>st(p.status)==='won').reduce((a,p)=>a+num(p.revenue),0);
  const pend = curProjects.filter(p=>st(p.status)==='pending').reduce((a,p)=>a+num(p.revenue),0);
  const recv = curProjects.filter(p=>{const c=st(p.collection_status);return c && c!=='paid';})
                          .reduce((a,p)=>a+num(p.revenue),0);
  // The receivables tile is the one he opens the app for, so it is the one
  // that goes somewhere. Left as invoiced value, NOT net of deposits, so this
  // number does not silently change meaning -- the Receivables view states the
  // difference in its own summary line.
  document.getElementById('kpis').innerHTML = [
    ['Companies', DATA.companies.length, null],
    ['Open shipments', openShip, null],
    [`Won revenue (${thisYear})`, money(won), null],
    [`Pending pipeline (${thisYear})`, money(pend), null],
    [`Open receivables (${thisYear})`, money(recv), 'receivable'],
  ].map(([l,n,go])=>go
    ? `<div class="kpi go" role="button" tabindex="0" onclick="setFilter('${jesc(go)}')"
         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();setFilter('${jesc(go)}')}"
       ><div class="n">${n}</div><div class="l">${l}</div></div>`
    : `<div class="kpi"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}

// Search fields can hold numbers as well as strings (a project or invoice number
// created via the MCP tools is stored with whatever type the caller sent). Always
// coerce before matching: calling .includes on a number throws and would take the
// whole company list down with it, not just the search.
function sv(v){ return v===null||v===undefined ? '' : String(v).toLowerCase(); }
// Case-preserving sibling of sv(). Use it anywhere a stored field is about to
// be compared, sorted, or .slice()'d as a string. Same reason: the field may
// hold a number if it was created through the MCP tools with a numeric value,
// and .localeCompare / !== against a trimmed input string both misbehave then.
function st(v){ return v===null||v===undefined ? '' : String(v); }
// Module-scope numeric coercion. kpis() has a local `num` for the same job
// and another function shadows that name with an unrelated predicate, so a
// distinct name here rather than relying on whichever is in scope. Stored
// revenue may be a STRING (anything written through the MCP tools keeps the
// caller's type) and `a + (p.revenue||0)` on a string concatenates -- one
// such row once turned $17,000 into $120,005,000.
function numv(v){ const n = Number(v); return isNaN(n) ? 0 : n; }
// Sibling of st() for the list-shaped fields. owner/annotations are arrays in
// every record the importer and the tools write, but nothing validates their
// type, and a string there makes .join/.some throw inside renderMain -- which
// doSave re-runs after every save, so one such record blanks the whole pane.
function arr(v){ return Array.isArray(v) ? v : (v===null||v===undefined||v==='' ? [] : [v]); }
// Options for a <select>, ALWAYS including whatever is actually stored.
// A stored value absent from the preset list selects nothing, so the browser
// reports the FIRST option and the save handler sends it unconditionally:
// normalize.py writes payment_status as "partial:{n}%" for any n, so opening a
// `partial:30%` invoice and pressing Save wrote the partial payment off as
// "open". Same shape silently wiped collection_status and fabricated a project
// status of "won" on a project stored with none.
/* The bucket choices, named from the sheet's own legend. Only keys the legend
   knows are offered: the server validates this field, so offering a stored
   value it would reject makes the WHOLE save fail on an unrelated edit. An
   unrecognised stored value is therefore called out in words beside the
   control instead, and clearing or correcting it is one click. */
function knownBucket(key){
  return !st(key) || trackerBuckets().some(b=>b.key===st(key));
}
function trackerOpts(current){
  const cur = st(current);
  let h = `<option value=""${cur ? '' : ' selected'}>— none —</option>`;
  trackerBuckets().forEach(b=>{
    h += `<option value="${esc(b.key)}"${b.key===cur ? ' selected' : ''}>`
       + `${esc(bucketLabel(b.key))}</option>`;
  });
  return h;
}
function opts(list, current){
  const cur = st(current);
  const all = list.map(st).includes(cur) ? list.map(st) : [cur, ...list.map(st)];
  return all.map(o=>`<option value="${esc(o)}" ${o===cur?'selected':''}>${esc(o||'—')}</option>`).join('');
}

function companyMatches(c){
  if(filter!=='all' && c.role!==filter) return false;
  if(!query) return true;
  const q=query.toLowerCase();
  if(sv(c.display_name).includes(q)) return true;
  if((contactsByCo[c.company_id]||[]).some(x=>sv(x.name).includes(q)||sv(x.email).includes(q))) return true;
  if((projectsByCo[c.company_id]||[]).some(p=>sv(p.project_no).includes(q)||sv(p.description).includes(q))) return true;
  if((invoicesByCo[c.company_id]||[]).some(v=>sv(v.invoice_no).includes(q))) return true;
  if((shipsByCo[c.company_id]||[]).some(s=>sv(s.vendor_po_raw).includes(q))) return true;
  return false;
}

// ---- Projects view ---------------------------------------------------------
// Every stored field is run through sv()/st() before compare or sort: a
// project_no or year created through the MCP tools can be a JSON number, and
// .includes()/.localeCompare() on a number throws (the 0.1.24 lesson).
function projCollBucket(p){
  const c = sv(p.collection_status);
  if(!c) return 'none';
  if(c === 'paid') return 'paid';
  if(c.startsWith('partial')) return 'partial';
  return 'open';
}
function projectMatches(p){
  if(projStatus !== 'all' && sv(p.status) !== projStatus) return false;
  if(projYear !== 'all' && st(p.year) !== projYear) return false;
  if(projColl !== 'all' && projCollBucket(p) !== projColl) return false;
  if(!query) return true;
  const q = query.toLowerCase();
  if(sv(p.project_no).includes(q)) return true;
  if(sv(p.description).includes(q)) return true;
  if(sv(p.client_po_no).includes(q)) return true;
  if(sv(p.invoice_no).includes(q)) return true;
  const co = companyById[p.company_id];
  if(co && sv(co.display_name).includes(q)) return true;
  if(arr(p.owner).some(o=>sv(o).includes(q))) return true;
  return false;
}
function projCompanyName(p){
  const co = companyById[p.company_id];
  return co ? (co.display_name || co.company_id) : (p.company_name || '');
}
function filteredProjects(){
  const rows = (DATA.projects||[]).filter(projectMatches);
  const num = k => (k==='revenue'||k==='margin'||k==='year');
  rows.sort((a,b)=>{
    let r;
    if(projSortKey === 'company'){
      r = st(projCompanyName(a)).localeCompare(st(projCompanyName(b)), undefined, {sensitivity:'base'});
    } else if(num(projSortKey)){
      const av = a[projSortKey], bv = b[projSortKey];
      const an = (av==null||isNaN(av)) ? -Infinity : Number(av);
      const bn = (bv==null||isNaN(bv)) ? -Infinity : Number(bv);
      r = an - bn;
    } else {
      r = st(a[projSortKey]).localeCompare(st(b[projSortKey]), undefined,
            {numeric:true, sensitivity:'base'});
    }
    return r * projSortDir;
  });
  return rows;
}
function projYears(){
  const ys = new Set();
  (DATA.projects||[]).forEach(p=>{ const y = st(p.year); if(y) ys.add(y); });
  return [...ys].sort((a,b)=>Number(b)-Number(a));
}
function sfButtons(rowId, opts, cur, fn){
  const el = document.getElementById(rowId); if(!el) return;
  const label = el.querySelector('.sfl');
  el.innerHTML = '';
  if(label) el.appendChild(label);
  opts.forEach(o=>{
    const b = document.createElement('button');
    b.textContent = o.label;
    if(o.value === cur) b.classList.add('on');
    b.addEventListener('click', ()=>fn(o.value));
    el.appendChild(b);
  });
}
function renderSubfilters(){
  const sf2 = document.getElementById('sf_year'), sf3 = document.getElementById('sf_coll');
  if(filter === 'receivable'){
    // Receivables reuses the first sub-filter row for the due bucket and hides
    // the other two, which are project-shaped (year, collection status).
    const lab = document.getElementById('sf_status').querySelector('.sfl');
    if(lab) lab.textContent = 'Show';
    if(sf2) sf2.style.display = 'none';
    if(sf3) sf3.style.display = 'none';
    sfButtons('sf_status',
      BUCKET_ORDER.map(b=>({value:b, label:`${b} (${recvCount(b)})`})),
      recvBucket, v=>setRecvBucket(v));
    return;
  }
  const lab = document.getElementById('sf_status').querySelector('.sfl');
  if(lab) lab.textContent = 'Status';
  if(sf2) sf2.style.display = '';
  if(sf3) sf3.style.display = '';
  sfButtons('sf_status', [{value:'all',label:'All'},{value:'won',label:'Won'},
      {value:'pending',label:'Pending'},{value:'lost',label:'Lost'}],
    projStatus, v=>{ projStatus=v; renderSubfilters(); renderList(); renderMain(); });
  sfButtons('sf_year', [{value:'all',label:'All'}].concat(
      projYears().map(y=>({value:y,label:y}))),
    projYear, v=>{ projYear=v; renderSubfilters(); renderList(); renderMain(); });
  sfButtons('sf_coll', [{value:'all',label:'All'},{value:'open',label:'Open'},
      {value:'partial',label:'Partial'},{value:'paid',label:'Paid'},
      {value:'none',label:'—'}],
    projColl, v=>{ projColl=v; renderSubfilters(); renderList(); renderMain(); });
}
function sortProjects(key){
  if(projSortKey === key) projSortDir = -projSortDir;
  else { projSortKey = key; projSortDir = 1; }
  renderMain();
}
function renderProjectsMain(){
  const rows = filteredProjects();
  const arrow = k => projSortKey===k ? (projSortDir===1?' ▲':' ▼') : '';
  const th = (k,label,cls) =>
    `<th class="sortable ${cls||''}" onclick="sortProjects('${jesc(k)}')">${esc(label)}${arrow(k)}</th>`;
  const totalRev = rows.reduce((a,p)=>a+(Number(p.revenue)||0),0);
  let h = `<div class="co-head"><h1>Projects</h1>
    <span class="muted">${rows.length} of ${(DATA.projects||[]).length}</span>
    <span class="muted">· ${money(totalRev)} revenue</span></div>`;
  if(!rows.length){
    return h + '<div class="empty">No projects match these filters.</div>';
  }
  h += `<div class="section"><table><thead><tr>
    ${th('project_no','Project #')}${th('company','Company')}${th('description','Description')}
    ${th('status','Status')}${th('owner','Owner')}${th('year','Year')}
    ${th('revenue','Revenue','num')}${th('margin','Margin','num')}
    ${th('collection_status','Collection')}</tr></thead><tbody>` +
    rows.map(p=>`<tr class="click" onclick="openProject('${jesc(st(p.project_no))}')">
      <td><b>${esc(st(p.project_no)||'—')}</b></td>
      <td>${p.company_id?`<a href="#" onclick="event.stopPropagation();select('${jesc(p.company_id)}');return false">${esc(projCompanyName(p))}</a>`:'<span class="muted">—</span>'}</td>
      <td>${esc(p.description||'')}</td>
      <td>${statusBadge(p.status)}</td>
      <td>${esc(arr(p.owner).join(', '))||'—'}</td>
      <td class="muted">${esc(st(p.year))}</td>
      <td class="num">${money(p.revenue)}</td>
      <td class="num">${pct(p.margin)}</td>
      <td class="muted">${esc(p.collection_status||'')}</td></tr>`).join('') +
    `</tbody></table></div>`;
  return h;
}
/* ------------------------------------------------------- receivables view --
   Every open invoice across every customer, oldest debt first. Before this the
   only way to answer "who owes me money" was to open each company in turn and
   read its invoice table; the header's own receivables figure was not even
   clickable.

   Deliberately shows OUTSTANDING (net of anything already collected) rather
   than the invoiced total: on a part-paid invoice those are different numbers
   and the one worth chasing is the remainder. See the note in the summary
   line -- the header KPI still totals invoiced value and is left alone. */
let recvBucket = 'Overdue';
function setRecvBucket(b){ recvBucket = b; renderSubfilters(); renderMain(); }

function allInvoices(){
  const today = todayISO(), soon = soonISO();
  return (DATA.invoices||[]).map(v=>({
    v, bucket: invoiceBucket(v, today, soon),
    due: dueOn(v), late: daysLate(v, today), owed: outstanding(v),
  }));
}
function recvRows(){
  const rows = allInvoices().filter(r => r.bucket === recvBucket);
  // oldest debt first; within the same day, largest first
  rows.sort((a,b)=>{
    const ad=st(a.due)||'9999-99-99', bd=st(b.due)||'9999-99-99';
    if(ad!==bd) return ad.localeCompare(bd);
    return (b.owed||0)-(a.owed||0);
  });
  return rows;
}
function recvCount(bucket){
  const today = todayISO(), soon = soonISO();
  return (DATA.invoices||[]).filter(v => invoiceBucket(v, today, soon) === bucket).length;
}

function renderReceivables(){
  const rows = recvRows();
  // an unlinked invoice has no amount anywhere in the store; it must not be
  // silently counted as zero, and the total has to say so
  const known = rows.filter(r => r.owed != null);
  const unknown = rows.length - known.length;
  const total = known.reduce((a,r)=>a+r.owed,0);

  let h = `<div class="co-head"><h1>Receivables</h1>
    <span class="muted">${rows.length} ${esc(recvBucket.toLowerCase())}</span>
    <span class="muted">· ${money(total)} outstanding</span></div>`;
  h += `<p class="muted" style="margin:2px 0 16px;font-size:12px">
    Outstanding is what is left to collect — a part-paid invoice counts only its
    remainder. The header total counts full invoiced value.</p>`;

  if(!rows.length){
    return h + `<div class="empty">Nothing ${esc(recvBucket.toLowerCase())}.</div>`;
  }

  h += `<div class="section"><table><thead><tr>
    <th>Invoice</th><th>Customer</th><th>Project</th>
    <th class="num">Outstanding</th><th class="num">Due</th><th class="num">Late</th>
    <th>Status</th><th>Last note</th><th></th></tr></thead><tbody>`;

  h += rows.map(r=>{
    const v = r.v;
    const co = companyById[v.company_id];
    const coName = co ? (co.display_name||v.company_id) : st(v.company_id);
    const pno = st(v.project_no);
    const proj = pno
      ? `<a href="#" onclick="event.stopPropagation();openProject('${jesc(pno)}');return false">${esc(pno)}</a>`
      : '<span class="badge b-stage">Not linked</span>';
    const lateCell = r.late == null ? '<span class="muted">—</span>'
      : (r.late > 30 ? `<b style="color:var(--red)">${r.late}d</b>`
        : r.late > 0 ? `<b style="color:var(--amber)">${r.late}d</b>`
        : '<span class="muted">—</span>');
    const owedCell = r.owed == null
      ? '<span class="muted" title="no project linked, so no amount on file">—</span>'
      : `<b>${money(r.owed)}</b>`;
    return `<tr class="click" onclick="select('${jesc(v.company_id)}')">
      <td><b>${esc(st(v.invoice_no)||'—')}</b></td>
      <td>${esc(coName)}</td>
      <td>${proj}</td>
      <td class="num">${owedCell}</td>
      <td class="num">${esc(fmtDate(r.due)||'—')}</td>
      <td class="num">${lateCell}</td>
      <td>${statusPill(v.payment_status)}</td>
      <td class="muted" style="max-width:240px">${esc(st(v.payment_notes).slice(0,80))}</td>
      <td><button class="pill-btn" style="padding:2px 8px;font-size:11px"
          onclick="event.stopPropagation();select('${jesc(v.company_id)}');openEditInvoice('${jesc(v.company_id)}','${jesc(st(v.invoice_no))}')">Open</button></td>
    </tr>`;
  }).join('');

  h += `</tbody><tfoot><tr>
    <td colspan="3">Outstanding</td>
    <td class="num">${money(total)}</td>
    <td colspan="5" class="muted" style="font-weight:400">${
      unknown ? esc(`excludes ${unknown} invoice${unknown>1?'s':''} with no amount on file`) : ''
    }</td></tr></tfoot></table></div>`;
  return h;
}

function renderReceivablesList(){
  document.getElementById('clist').innerHTML = recvRows().slice(0,400).map(r=>{
    const v=r.v, co=companyById[v.company_id];
    return `<div class="citem" onclick="select('${jesc(v.company_id)}')">
      <div class="cn">${esc(st(v.invoice_no)||'—')} <span class="muted">${esc(co?(co.display_name||''):'')}</span></div>
      <div class="cm"><span>${r.owed==null?'no amount':money(r.owed)}</span>${
        r.late?`<span>· ${r.late}d late</span>`:''}</div>
    </div>`;
  }).join('') || '<div class="muted" style="padding:14px">Nothing here.</div>';
}

/* ------------------------------------------------------- live tracker --
   The daily "whose court is the ball in" screen, and the landing screen.

   Status is the sheet's fill colour, decoded at import into a neutral key; the
   LABEL is whatever he wrote in the legend, read from the workbook and stored,
   never hardcoded here. A bucket with no legend row still groups correctly and
   falls back to its key rather than showing nothing. */
function trackerBuckets(){
  const seen = (DATA.tracker_buckets||[]).filter(b=>b && b.key);
  if(seen.length) return seen;
  // no legend was found at all: still group, using the keys themselves
  return [{key:'action_admin'},{key:'action_owner'},{key:'awaiting_materials'}];
}
function bucketLabel(key){
  const b = (DATA.tracker_buckets||[]).find(x=>x && x.key===key);
  if(b && b.label) return b.label;
  return st(key).replace(/_/g,' ').replace(/^\w/, c=>c.toUpperCase());
}
function bucketClass(key){
  return {action_admin:'b-admin', action_owner:'b-owner',
          awaiting_materials:'b-await'}[key] || 'b-stage';
}

/* A ship-date cell is a date about half the time. The rest are "EST 8/03/26",
   "US Pickup", or empty. Never invent one: parse what is parseable, show the
   rest exactly as stored, and say plainly which it is -- an unknown date is
   the thing he most needs to see. */
function legDate(raw){
  const t = st(raw).trim();
  if(!t) return {kind:'none', text:'no date'};
  const est = /^\s*est\.?\s+/i.test(t);
  const iso = isoDate(t.replace(/^\s*est\.?\s+/i, ''));
  if(!iso) return {kind:'text', text:t};
  const late = iso < todayISO();
  return {kind: late ? (est?'est-passed':'passed') : 'ok', text: fmtDate(iso),
          est: est, iso: iso};
}
function legPaid(po){
  const m = st(po).match(/\((\s*\d+%\s*)?\s*paid\s*\)/i);
  if(!m) return null;
  return m[1] ? m[1].trim() + ' paid' : 'paid';
}
/* Everything on this row that needs a person: a ship date already past, an EST
   that has come and gone, a leg with no date at all, a start date of TBD. */
/* A leg that has ARRIVED is not late, whatever its date says. list_shipments
   (overdue=True) has always excluded these three stages, and without the same
   rule here the same store answered the same question two ways: chat said
   nothing was overdue while the daily screen kept a red "ship date passed"
   badge on a delivered leg -- and, because rows sort by flag count, kept that
   project pinned to the top of the screen permanently. */
const LEG_DONE = new Set(['delivered', 'installed', 'cancelled']);
function legSettled(l){ return LEG_DONE.has(sv(l && l.stage).trim()); }
function liveFlags(p, legs){
  const out = [];
  const start = st(p.date || p.start_date).trim();
  if(/^tbd$/i.test(start)) out.push('start TBD');
  legs.forEach(l=>{
    if(legSettled(l)) return;
    const d = legDate(l.ship_date);
    if(d.kind==='passed') out.push('ship date passed');
    else if(d.kind==='est-passed') out.push('EST passed');
    else if(d.kind==='none') out.push('leg with no date');
  });
  return [...new Set(out)];
}

/* The search box is the most prominent control on the screen the app now opens
   on, and it did nothing here -- it filtered the company list, so typing on the
   landing tab changed nothing and then silently filtered a list he had not
   asked for the moment he clicked "All". Matches the fields this screen
   actually shows: the number, the customer, and the note. */
function liveMatches(p, q){
  if(!q) return true;
  const co = companyById[p.company_id];
  return sv(p.project_no).includes(q)
      || sv(co && co.display_name).includes(q)
      || sv(p.description).includes(q)
      || sv(p.open_orders_notes).includes(q);
}
function unlinkedMatches(u, q){
  if(!q) return true;
  return sv(u.client).includes(q) || sv(u.raw_key).includes(q)
      || sv(u.open_orders_notes).includes(q) || sv(u.client_po).includes(q);
}
function liveRows(){
  const q = sv(query).trim();
  const rows = (DATA.projects||[])
    .filter(p=>p && !p.archived && st(p.tracker_status) && liveMatches(p, q))
    .map(p=>{
      const legs = (DATA.shipments||[]).filter(s=>
        st(s.company_id)===st(p.company_id) &&
        _shipmentProjectNos(s).has(st(p.project_no)));
      return {p, legs, flags: liveFlags(p, legs)};
    });
  rows.sort((a,b)=>{
    if(a.flags.length !== b.flags.length) return b.flags.length - a.flags.length;
    return st(a.p.project_no).localeCompare(st(b.p.project_no));
  });
  return rows;
}

// Same bound the company, Projects and Receivables lists use. Bounded today
// (status comes off a fill colour on ~9 rows), but it is the operator's own
// sheet: a week where he colours the whole table renders unbounded cards, each
// with every leg, from an O(projects x shipments) scan run twice per repaint.
const LIVE_CAP = 400;
function renderLiveMain(){
  const rows = liveRows();
  // Carry each row's index in the RAW array, not its position after filtering.
  // openAdoptTrackerRow/saveAdoptTrackerRow both index DATA.tracker_unlinked
  // directly, so a filtered-out entry shifted every card's number: the first
  // button went dead (its handler bailed on `if(!u) return` with no message)
  // and every later one opened the PREVIOUS row's client, note, status and
  // dates under the number typed for the row that was clicked.
  const q = sv(query).trim();
  const unlinked = arr(DATA.tracker_unlinked)
    .map((u, i)=>({u, i}))
    .filter(x=>x.u && typeof x.u === 'object' && unlinkedMatches(x.u, q));
  const flagged = rows.filter(r=>r.flags.length).length;

  let h = `<div class="co-head"><h1>Live projects</h1>
    <span class="muted">${rows.length} active</span>
    ${flagged?`<span class="badge b-lost">${flagged} need a look</span>`:''}</div>`;
  h += `<p class="muted" style="margin:2px 0 16px;font-size:12px">
    Grouped by the status colours from your tracker. Anything late, estimated
    and passed, or missing a date is called out on the row.</p>`;

  // Every row must land in exactly one section. A status no bucket knows about
  // -- set through chat, or a bucket key that drifted from the importer's --
  // used to be counted in "N active" above and then rendered nowhere at all,
  // so a live job left the board while the sidebar still listed it. The
  // leftovers get their own section rather than disappearing.
  const known = new Set(trackerBuckets().map(b=>b.key));
  const orphans = rows.filter(r=>!known.has(st(r.p.tracker_status)));
  trackerBuckets().forEach(b=>{
    const mine = rows.filter(r=>st(r.p.tracker_status)===b.key);
    if(!mine.length) return;
    h += `<div class="section"><div class="lt-head">
      <span class="swatch ${bucketClass(b.key)}"></span>
      <h2 style="border:0;padding:0;margin:0">${esc(bucketLabel(b.key))}</h2>
      <span class="muted">${mine.length}</span></div>`;
    h += mine.slice(0, LIVE_CAP).map(r=>liveCard(r)).join('');
    if(mine.length > LIVE_CAP){
      // Never a silent truncation. Every sibling list caps at 400 and this one
      // did not; capping it without saying so would read as "that is all the
      // work there is", which on the daily screen is the worse failure.
      h += `<div class="muted" style="font-size:12px;padding:4px 2px">Showing
        the first ${LIVE_CAP} of ${mine.length} — search to narrow this
        down.</div>`;
    }
    h += `</div>`;
  });

  if(orphans.length){
    h += `<div class="section"><div class="lt-head">
      <span class="swatch b-stage"></span>
      <h2 style="border:0;padding:0;margin:0">Status not recognised</h2>
      <span class="muted">${orphans.length}</span></div>
      <p class="muted" style="font-size:12px;margin:0 0 10px">
        These carry a status the tracker legend does not name, so they could
        not be grouped. They are live work — they are here rather than
        hidden.</p>`;
    h += orphans.map(r=>liveCard(r)).join('');
    h += `</div>`;
  }

  if(unlinked.length){
    h += `<div class="section"><div class="lt-head">
      <span class="swatch b-stage"></span>
      <h2 style="border:0;padding:0;margin:0">Not in the CRM yet</h2>
      <span class="muted">${unlinked.length}</span></div>
      <p class="muted" style="font-size:12px;margin:0 0 10px">
        These are live rows from your tracker that have no project number the
        CRM can match. Give one a number and it becomes a normal project you
        can edit here.</p>`;
    h += unlinked.slice(0, LIVE_CAP).map(x=>unlinkedCard(x.u, x.i)).join('');
    if(unlinked.length > LIVE_CAP){
      h += `<div class="muted" style="font-size:12px;padding:4px 2px">Showing
        the first ${LIVE_CAP} of ${unlinked.length}.</div>`;
    }
    h += `</div>`;
  }
  if(!rows.length && !unlinked.length){
    h += `<div class="empty">No live projects yet.</div>`;
  }
  return h;
}

function liveCard(r){
  const p = r.p, co = companyById[p.company_id];
  const legs = r.legs.map(l=>{
    const d = legDate(l.ship_date), paid = legPaid(l.vendor_po_raw);
    // legSettled here too, not only in liveFlags: dropping the row's badge
    // while leaving the leg itself bold red says the same wrong thing in a
    // quieter voice, and this is the line he actually reads.
    const cls = legSettled(l) ? 'muted'
              : (d.kind==='passed'||d.kind==='none') ? 'lt-bad'
              : (d.kind==='est-passed' ? 'lt-warn' : 'muted');
    return `<div class="lt-leg">
      <span class="lt-po">${esc(st(l.vendor_po_raw)||'—')}</span>
      <span class="${cls} nw">${esc(d.text)}${d.est&&d.kind!=='est-passed'?' (est)':''}</span>
      ${paid?`<span class="badge b-won">${esc(paid)}</span>`:''}
    </div>`;
  }).join('') || '<div class="muted" style="font-size:12px">No vendor legs.</div>';

  return `<div class="lt-card">
    <div class="lt-top">
      <b class="nw">${esc(st(p.project_no)||'—')}</b>
      <a href="#" class="lnk" onclick="event.preventDefault();select('${jesc(p.company_id)}')">${esc(co?(co.display_name||p.company_id):st(p.company_id))}</a>
      ${p.invoice_no?`<span class="muted nw">inv ${esc(st(p.invoice_no))}</span>`:''}
      <span class="muted nw">${esc(fmtDate(p.date||p.start_date)||st(p.date||p.start_date)||'no start date')}</span>
      ${r.flags.map(f=>`<span class="badge b-lost">${esc(f)}</span>`).join('')}
      <span style="margin-left:auto"><button class="pill-btn" onclick="openProject('${jesc(st(p.project_no))}')">Edit</button></span>
    </div>
    <div class="lt-note">${esc(st(p.open_orders_notes)||'')||'<span class="muted">no note</span>'}</div>
    <div class="lt-legs">${legs}</div>
  </div>`;
}

function unlinkedCard(u, i){
  // arr(), not `||[]`: a legs value that is a string or an object makes .map
  // throw inside renderMain, which doSave re-runs after EVERY save -- so one
  // malformed row blanks the whole pane. Same rule as owner/annotations.
  const legs = arr(u.legs).map(l=>{
    const d = legDate(l.ship_date), paid = legPaid(l.vendor_po_raw);
    return `<div class="lt-leg"><span class="lt-po">${esc(st(l.vendor_po_raw)||'—')}</span>
      <span class="muted nw">${esc(d.text)}</span>
      ${paid?`<span class="badge b-won">${esc(paid)}</span>`:''}</div>`;
  }).join('') || '<div class="muted" style="font-size:12px">No vendor legs.</div>';
  return `<div class="lt-card lt-unlinked">
    <div class="lt-top">
      <span class="badge b-stage nw">tracker row ${esc(st(u.sheet_row))}</span>
      <b>${esc(st(u.client)||'unknown client')}</b>
      ${u.raw_key?`<span class="muted nw">keyed ${esc(st(u.raw_key))}</span>`:''}
      <span class="muted nw">${esc(fmtDate(u.start_date)||st(u.start_date)||'no start date')}</span>
      <span style="margin-left:auto"><button class="pill-btn pri" onclick="openAdoptTrackerRow(${i})">Add to CRM</button></span>
    </div>
    <div class="lt-note">${esc(st(u.open_orders_notes)||'')||'<span class="muted">no note</span>'}</div>
    <div class="lt-legs">${legs}</div>
  </div>`;
}

/* Adopt a tracker row into the CRM.

   The row came off the sheet with no project number the CRM could match, so it
   has no key and cannot be edited. Rather than mint one -- a synthetic key
   would silently mis-attach a later edit if two such rows ever shuffled -- he
   supplies the number here, and the row becomes an ordinary project. That is
   the migration direction: the fix lives in the CRM, not back in Excel.

   Writes go through create_project like every other project. Nothing new. */
function openAdoptTrackerRow(i){
  const u = arr(DATA.tracker_unlinked)[i];
  if(!u || typeof u !== 'object') return;
  const cid = u.client ? _slugGuess(u.client) : '';
  document.getElementById('dtitle').textContent =
    'Add tracker row ' + st(u.sheet_row) + ' to the CRM';
  document.getElementById('dbody').innerHTML = `
    <p class="muted" style="margin-top:0;font-size:12px">From your Project
      Tracker, row ${esc(st(u.sheet_row))}. Give it a project number and it
      becomes a normal project you can edit here.</p>
    <div class="field"><label>Project # <span class="muted"
      style="text-transform:none;font-weight:400">(required)</span></label>
      <input id="a_pno" placeholder="e.g. 1500"/></div>
    <div class="field"><label>Customer</label>
      <select id="a_cid">${
        // No blind default. With no name match the browser selects the FIRST
        // option, which silently files the row under an arbitrary company --
        // and one of his is an address string the importer read as a customer.
        // An empty selection is refused on save, so he has to choose.
        cid ? '' : '<option value="">— choose a customer —</option>'}${
        (DATA.companies||[]).filter(c=>st(c.role)!=='vendor')
          .sort((a,b)=>st(a.display_name).localeCompare(st(b.display_name)))
          .map(c=>`<option value="${esc(c.company_id)}" ${
            c.company_id===cid?'selected':''}>${esc(c.display_name||c.company_id)}</option>`)
          .join('')}</select></div>
    <div class="field"><label>Description</label>
      <input id="a_desc" value="${esc(st(u.client_po))}"/></div>
    <div class="field"><label>Open orders note</label>
      <textarea id="a_note" style="min-height:96px">${esc(st(u.open_orders_notes))}</textarea></div>
    <div class="row2">
      <div class="field"><label>Status</label><select id="a_status">
        ${opts(['won','pending','lost'], 'won')}</select></div>
      <div class="field"><label>Year</label>
        <input id="a_year" type="number" value="${esc(_adoptYear(u))}"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveAdoptTrackerRow(${i})">Add to CRM</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:14px;font-size:12px">${
      // The two kinds of unlinked row differ in whether their legs were
      // imported, and one sentence cannot be true of both. A numberless row
      // returns from the importer BEFORE the vendor loop, so its legs exist
      // nowhere; a keyed row's legs were imported, but under the sheet's own
      // key and client, so they will not follow the number chosen here.
      // Telling him not to re-add legs that do not exist is the worse error of
      // the two: it suppresses the only action that would recover them.
      arr(u.legs).length === 0 ? 'No vendor legs on this row.'
      : st(u.raw_key)
        ? `Its ${arr(u.legs).length} vendor leg(s) were imported under the
           tracker's own number (${esc(st(u.raw_key))}), so they will not follow
           this project. Check them against the new number afterwards.`
        : `Its ${arr(u.legs).length} vendor leg(s) were NOT imported — a row
           with no project number has nowhere to file them. Add them from the
           project once it exists.`}</p>`;
  openDrawer();
}
/* Best-effort match of a tracker client name to an existing company. Only ever
   preselects a dropdown -- a wrong guess costs one click, never a mis-filed
   record, and the operator confirms before anything is written. */
/* The year the WORK is in, taken from the tracker row's own start date. The
   adoption date is not the deal date: a job started in December and adopted in
   January was filed under the wrong year on every annual figure. */
function _adoptYear(u){
  const iso = isoDate(st(u && u.start_date));
  return iso ? Number(iso.slice(0, 4)) : new Date().getFullYear();
}
function _slugGuess(name){
  const n = sv(name).replace(/[^a-z0-9]+/g, '');
  if(!n) return '';
  // Vendors are excluded HERE as well as from the dropdown. They used only to
  // be filtered out of the option list, so a tracker row whose client name
  // matched a VENDOR produced a truthy cid -- which suppressed the "choose a
  // customer" placeholder -- while the matched company was absent from the
  // options, so nothing carried `selected` and the browser fell back to the
  // first customer. The !cid guard then passed on that fallback and filed the
  // job under a company nobody chose. A guess that cannot be offered must not
  // count as a guess.
  const hit = (DATA.companies||[]).find(c=>
    st(c.role)!=='vendor' &&
    sv(c.display_name).replace(/[^a-z0-9]+/g, '') === n);
  return hit ? hit.company_id : '';
}
async function saveAdoptTrackerRow(i){
  const u = arr(DATA.tracker_unlinked)[i];
  const msg = document.getElementById('savedMsg');
  // The opener bails on a missing row; this did not, and would have written a
  // project with no status, no start date and no location -- so it would not
  // have appeared on the screen it was adopted into, while the card it came
  // from stayed put.
  if(!u || typeof u !== 'object'){
    msg.textContent='✗ that tracker row is no longer on the list — reload';
    msg.className='saved show errc'; return false;
  }
  const pno = document.getElementById('a_pno').value.trim();
  if(!pno){ msg.textContent='✗ project # is required';
            msg.className='saved show errc'; return false; }
  const cid = document.getElementById('a_cid').value;
  if(!cid){ msg.textContent='✗ pick a customer';
            msg.className='saved show errc'; return false; }
  const fields = {
    project_no: pno, company_id: cid,
    company_name: (companyById[cid]||{}).display_name,
    description: document.getElementById('a_desc').value.trim() || null,
    open_orders_notes: document.getElementById('a_note').value.trim() || null,
    tracker_status: u.tracker_status || null,
    // The sheet row it was adopted FROM. A numberless row has no key to match
    // on, so this plus the note is how the next import knows the row is
    // already a project and stops re-offering it for adoption.
    tracker_row: u.sheet_row == null ? null : u.sheet_row,
    // The key the SHEET carries for this row, verbatim, so the next import
    // knows the row already became a project. Not the same as project_no --
    // he chooses that, and a tracker row need not be keyed with a number at
    // all: on the real workbook one is keyed with a phrase, which parses to
    // nothing, so without this that card returned every import forever no
    // matter what number he gave it.
    tracker_key: st(u.raw_key) || null,
    date: u.start_date || null,
    location: u.location || null,
    // Neither is invented any more. Both were hardcoded -- status 'won' and
    // whatever year the adoption happened to be done in -- so a job started in
    // December and adopted in January landed in the wrong year's revenue
    // reporting, and every adopted row counted as a $0 win in the "Won
    // revenue" KPI whether it was won or not. Now: he picks the status, and
    // the year defaults to the one the sheet's own start date is in.
    status: document.getElementById('a_status').value || null,
    year: numOrNull('a_year'),
  };
  const ok = await doSave('create_project', {fields}, (r)=>{
    DATA.projects.push(r.project || fields);
    // it is a project now, so it must stop appearing as an unadopted row
    DATA.tracker_unlinked = (DATA.tracker_unlinked||[])
      .filter(x=>x !== u);
    reindex(); renderList(); renderMain(); closeDrawer();
  });
  return ok;
}

/* The sidebar must not present an unrecognised status as if it were one of
   the legend's own buckets. bucketLabel's fallback title-cases the key, so a
   status of 'done' read as "Done" beside a main pane saying the tracker cannot
   name it -- the sidebar and the main pane disagreeing is the whole symptom. */
function _liveListLabel(key){
  const known = new Set(trackerBuckets().map(b=>b.key));
  return known.has(st(key)) ? bucketLabel(key) : 'status not recognised';
}
function renderLiveList(){
  const rows = liveRows();
  document.getElementById('clist').innerHTML = rows.slice(0,400).map(r=>{
    const co = companyById[r.p.company_id];
    return `<div class="citem" onclick="openProject('${jesc(st(r.p.project_no))}')">
      <div class="cn">${esc(st(r.p.project_no)||'—')} <span class="muted">${esc(co?(co.display_name||''):'')}</span></div>
      <div class="cm">${r.flags.length?`<span class="owed">${r.flags.length} flag${r.flags.length>1?'s':''}</span>`:`<span>${esc(st(_liveListLabel(r.p.tracker_status)).slice(0,28))}</span>`}</div>
    </div>`;
  }).join('') || '<div class="muted" style="padding:14px">No live projects.</div>';
}

function renderProjectsList(){
  const rows = filteredProjects();
  document.getElementById('clist').innerHTML = rows.slice(0,400).map(p=>`
    <div class="citem" onclick="openProject('${jesc(st(p.project_no))}')">
      <div class="cn">${esc(st(p.project_no)||'—')} ${esc(st(p.description).slice(0,40))}</div>
      <div class="cm"><span>${esc(projCompanyName(p))}</span>${p.status?`<span>· ${esc(p.status)}</span>`:''}</div>
    </div>`).join('') || '<div class="muted" style="padding:14px">No matches.</div>';
}

function renderList(){
  if(filter === 'live'){ renderLiveList(); return; }
  if(filter === 'receivable'){ renderReceivablesList(); return; }
  if(filter === 'project'){ renderProjectsList(); return; }
  const today = todayISO(), soon = soonISO();
  const items = DATA.companies.filter(companyMatches)
    .sort((a,b)=>st(a.display_name).localeCompare(st(b.display_name)));
  document.getElementById('clist').innerHTML = items.slice(0,400).map(c=>{
    const np=(projectsByCo[c.company_id]||[]).length, ns=(shipsByCo[c.company_id]||[]).length;
    // What they owe, in the list. "customer · 2 projects · 2 shipments" is true
    // and answers nothing he opens this app to ask.
    const invs=(invoicesByCo[c.company_id]||[]).filter(v=>invoiceBucket(v,today,soon)!=='Paid');
    const owed=invs.map(outstanding).filter(x=>x!=null).reduce((a,b)=>a+b,0);
    const lates=invs.map(v=>daysLate(v,today)).filter(x=>x!=null&&x>0);
    const late=lates.length?Math.max.apply(null,lates):0;
    return `<div class="citem ${c.company_id===selected?'sel':''}" onclick="select('${jesc(c.company_id)}')">
      <div class="cn">${esc(c.display_name||c.company_id)}</div>
      <div class="cm">${owed?`<span class="owed">${money(owed)} owed</span>`:`<span>${esc(c.role)}</span>`}${
        late?`<span class="owed">· ${late}d late</span>`:''}${
        !owed&&np?`<span>· ${np} project${np>1?'s':''}</span>`:''}${
        !owed&&ns?`<span>· ${ns} shipment${ns>1?'s':''}</span>`:''}</div>
    </div>`;
  }).join('') || '<div class="muted" style="padding:14px">No matches.</div>';
}

function select(id){
  selected=id;
  if(filter === 'project' || filter === 'receivable' || filter === 'live'){ setFilter('all'); fetchEnrichment(id); return; }
  renderList(); renderMain(); fetchEnrichment(id);
}

/* Outlook read-signal overlay (Phase 4) — fetched per company when live */
const ENRICH = {};
async function fetchEnrichment(id){
  if (CRM.mode === 'embedded' || ENRICH[id] !== undefined) return;
  try{
    const r = await CRM.call('get_company', {ref: id});
    ENRICH[id] = (r.ok && r.enrichment) || null;
  }catch(e){ ENRICH[id] = null; }
  if (selected === id) renderMain();
}

function enrichmentSection(id){
  if (CRM.mode === 'embedded') return '';
  const e = ENRICH[id];
  if (e === undefined) return `<div class="section"><h2>Outlook activity</h2><div class="muted">Checking Outlook…</div></div>`;
  if (e === null) return `<div class="section"><h2>Outlook activity</h2><div class="muted">No Outlook signal on file — refresh enrichment to pull last contact, threads, and meetings.</div></div>`;
  let h = `<div class="section"><h2>Outlook activity</h2>`;
  h += `<div class="kv"><span class="k">Last contact</span><span>${e.last_contact ? esc(String(e.last_contact).slice(0,10)) : '<span class="muted">none found</span>'}</span></div>`;
  // arr(): set_enrichment validates field NAMES but never types, so a
  // string here made th.slice(...).map throw inside renderMain -- which
  // doSave re-runs after every save, blanking the whole detail pane.
  // .filter(Boolean): set_enrichment validates field NAMES, never types, so
  // a null member is storable. It threw inside renderMain, which left the
  // previously-selected company's pane on screen under the new company's
  // name, and made doSave report a save that had actually persisted as a
  // failure.
  const th = arr(e.threads).filter(Boolean);
  if (th.length){
    h += `<table><thead><tr><th>Recent thread</th><th>With</th><th>Date</th><th></th></tr></thead><tbody>` +
      th.slice(0,5).map(t=>`<tr><td>${t.webLink?`<a href="${esc(safeUrl(t.webLink))}" target="_blank" rel="noopener">${esc(t.subject||'(no subject)')}</a>`:esc(t.subject||'(no subject)')}</td>
        <td class="muted">${esc(t.with||'')}</td><td class="muted">${esc(String(t.date||'').slice(0,10))}</td>
        <td>${t.message_id?`<button class="pill-btn" style="padding:2px 8px;font-size:11px" onclick="replyToThread('${jesc(id)}','${jesc(t.message_id)}')">Reply</button>`:''}</td></tr>`).join('') + `</tbody></table>`;
  } else {
    h += `<div class="muted">No recent email threads.</div>`;
  }
  const mt = arr(e.meetings).filter(Boolean);
  if (mt.length){
    h += `<div style="margin-top:8px"><b style="font-size:12px">Meetings:</b> ` +
      mt.slice(0,3).map(m=>`${esc(m.subject||'meeting')} (${esc(String(m.date||'').slice(0,10))})`).join(' · ') + `</div>`;
  }
  if (e.refreshed_at) h += `<div class="muted" style="font-size:11px;margin-top:6px">Refreshed ${esc(String(e.refreshed_at).slice(0,16).replace('T',' '))} UTC</div>`;
  return h + `</div>`;
}

/* Date controls, and why they are not plain <input type="date">.
   normalize.py stores an invoice/pay date as str() of whatever the tracker
   cell held, so real stores contain "3/14/2026" as well as ISO -- server.py's
   _parse_date_loose exists precisely because both shapes occur. Per the HTML
   value-sanitization algorithm an <input type="date"> DISCARDS any value that
   is not exactly yyyy-mm-dd: the box renders blank and .value reads "". A save
   handler that then sends that value unconditionally overwrites the real date
   with null, in the only copy that exists. So: parse what we can, fall back to
   a text box for what we cannot, and never send a date the user did not
   actually touch. */
function isoDate(v){
  const t = st(v).trim();
  if(!t) return '';
  let y, mo, d;
  const iso = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if(iso){ y=+iso[1]; mo=+iso[2]; d=+iso[3]; }
  else {
    const us = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);   // M/D/YYYY, M/D/YY
    if(!us) return null;
    // pivot at 70: a 2-digit year is only ever a recent tracker date or a
    // legacy 19xx one. Mapping every one to the 2000s displayed '12/31/99'
    // as 2099 -- a century out, and it sorts to the wrong end.
    mo=+us[1]; d=+us[2];
    y = us[3].length===2 ? (+us[3] >= 70 ? 1900 + +us[3] : 2000 + +us[3]) : +us[3];
  }
  // Shape is not validity. "9/31/2025", "2/30/2026" and "2026-02-29" (2026 is
  // not a leap year) all match the patterns above and all produce a string an
  // <input type="date"> refuses to hold -- which is the wipe this whole
  // mechanism exists to stop. Round-trip through Date to confirm the calendar
  // actually contains the day.
  const dt = new Date(Date.UTC(y, mo-1, d));
  if(!(y>0 && mo>=1 && mo<=12 && d>=1)) return null;
  if(dt.getUTCFullYear()!==y || dt.getUTCMonth()!==mo-1 || dt.getUTCDate()!==d) return null;
  return String(y).padStart(4,'0')+'-'+String(mo).padStart(2,'0')+'-'+String(d).padStart(2,'0');
}
/* Display-only date formatting. Storage is NEVER touched by this -- the stored
   form is load-bearing for the date-preservation work, and dateInput() below
   still hands the raw string to a text box when it cannot be parsed.

   Exists because the same column showed "2026-07-09" and "3/14/2026" side by
   side: one shipment stored ISO, its neighbour stored the tracker's own
   format, and both rendered raw. A date it cannot parse comes back unchanged
   rather than blank or invented -- an unreadable date is information. */
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fmtDate(v){
  const t = st(v).trim();
  if(!t) return '';
  const iso = isoDate(t);
  if(!iso) return t;                       // unparseable: show what is stored
  const [y,m,d] = iso.split('-').map(Number);
  return d + ' ' + MONTHS[m-1] + ' ' + y;
}

/* ---------------------------------------------------- receivables model --
   ONE definition of which bucket an invoice is in, what it is worth, and how
   late it is. The company page and the Receivables view both read these: a
   cross-company total that disagreed with the per-company page about the same
   invoice would be worse than having no total at all. */
function todayISO(){ return new Date().toISOString().slice(0,10); }
function soonISO(){ const d=new Date(); d.setDate(d.getDate()+7); return d.toISOString().slice(0,10); }

const BUCKET_ORDER = ['Overdue','Due this week','Due later','No due date','Paid'];
function invoiceBucket(v, today, soon){
  today = today || todayISO(); soon = soon || soonISO();
  if(st(v.payment_status).startsWith('paid')) return 'Paid';
  const d = dueOn(v);
  if(!d) return 'No due date';
  if(d < today) return 'Overdue';
  if(d <= soon) return 'Due this week';
  return 'Due later';
}

/* Whole days past due; null when there is no usable due date. */
function daysLate(v, today){
  const d = dueOn(v); if(!d) return null;
  const a = Date.parse(d + 'T00:00:00Z'), b = Date.parse((today||todayISO()) + 'T00:00:00Z');
  if(isNaN(a) || isNaN(b)) return null;
  const n = Math.round((b - a) / 86400000);
  return n > 0 ? n : 0;
}

/* The invoice's value, which lives on the linked PROJECT -- invoices carry no
   amount of their own. Returns null when there is no link or no revenue, and
   callers must show that as "no amount on file" rather than as zero: an
   unlinked invoice is a real thing in this store (one is 116 days late) and
   silently counting it as $0 would hide it from the total. */
function invoiceAmount(v){
  const pno = st(v.project_no); if(!pno) return null;
  const p = DATA.projects.find(x => String(x.project_no) === String(pno)
                                 && st(x.company_id) === st(v.company_id));
  if(!p || p.revenue == null || isNaN(Number(p.revenue))) return null;
  return Number(p.revenue);
}

/* What is still to collect. "partial:30%" means 30% has been RECEIVED, so the
   outstanding share is the remainder -- reading it the other way round would
   understate every part-paid receivable. */
function outstanding(v){
  const amt = invoiceAmount(v); if(amt == null) return null;
  const ps = st(v.payment_status).toLowerCase();
  if(ps.startsWith('paid')) return 0;
  const m = ps.match(/(\d+(?:\.\d+)?)\s*%/);
  if(m){
    const paidPct = Number(m[1]);
    if(paidPct >= 0 && paidPct <= 100) return Math.round(amt * (1 - paidPct/100));
  }
  return amt;
}

function statusPill(ps){
  const s = st(ps).trim();
  if(!s) return '<span class="badge b-stage">—</span>';
  const low = s.toLowerCase();
  if(low.startsWith('paid')) return '<span class="badge b-won">Paid</span>';
  const m = low.match(/(\d+(?:\.\d+)?)\s*%/);
  if(low.startsWith('partial')) return `<span class="badge b-pending">Part paid${m?' '+m[1]+'%':''}</span>`;
  if(low === 'open') return '<span class="badge b-open">Open</span>';
  return `<span class="badge b-stage">${esc(s)}</span>`;
}

function dateInput(id, stored){
  const iso = isoDate(stored);
  if(iso === null){
    const raw = esc(st(stored));
    return `<input id="${esc(id)}" type="text" value="${raw}"/>`
         + `<p class="muted" style="margin:4px 0 0;font-size:11px">Kept exactly as it came from the tracker.</p>`;
  }
  return `<input id="${esc(id)}" type="date" value="${esc(iso)}"/>`;
}
// Baseline is read from the control AFTER the browser has parsed and
// sanitized it -- never from the string we intended to put there. That makes a
// value/attribute mismatch impossible by construction, which is what the first
// attempt at this got wrong: it compared against the intended value, so any
// input the sanitizer rejected read as "changed" and got written back as null.
function snapDates(ids){
  ids.forEach(id=>{
    const el = document.getElementById(id);
    if(el) el.setAttribute('data-orig', el.value || '');
  });
}
function dateIfChanged(id, fields, key){
  const el = document.getElementById(id);
  if(!el) return;
  const before = el.getAttribute('data-orig');
  if(before === null) return;             // never snapshotted -> never send
  const now = el.value || '';
  if(now !== before) fields[key] = now || null;
}

function statusBadge(s){ s=st(s).toLowerCase(); const cls={won:'b-won',pending:'b-pending',lost:'b-lost'}[s]||'b-stage';
  return s?`<span class="badge ${cls}">${esc(s)}</span>`:''; }

function renderMain(){
  if(filter === 'live'){
    document.getElementById('main').innerHTML = renderLiveMain();
    return;
  }
  if(filter === 'receivable'){
    document.getElementById('main').innerHTML = renderReceivables();
    return;
  }
  if(filter === 'project'){
    document.getElementById('main').innerHTML = renderProjectsMain();
    return;
  }
  const c=companyById[selected]; if(!c){return;}
  const cts=contactsByCo[selected]||[], prs=projectsByCo[selected]||[], sps=shipsByCo[selected]||[];
  const draftAll = cts.filter(x=>x.email)[0];
  // A vendor is someone we BUY from -- offering "+ New invoice" there invited
  // a receivable against a supplier. Invoices and projects belong to the
  // people who owe us money.
  const sells = (c.role==='customer' || c.role==='lead');
  let h=`<div class="co-head"><h1>${esc(c.display_name||c.company_id)}</h1>
    <span class="badge b-${esc(c.role)}">${esc(c.role)}</span>
    ${c.primary_location?`<span class="muted">${esc(c.primary_location)}</span>`:''}
    <span style="margin-left:auto;display:flex;gap:8px;align-items:center">
      ${sells?`<button class="pill-btn pri" onclick="openNewInvoice('${jesc(c.company_id)}')">+ New invoice</button>`:''}
      ${sells?`<button class="pill-btn" onclick="openNewProject('${jesc(c.company_id)}')">+ New project</button>`:''}
      <button class="pill-btn" onclick="openNewContact('${jesc(c.company_id)}')">+ Add contact</button>
      ${c.role==='lead'?`<button class="pill-btn" style="background:var(--green-soft);color:var(--green)" onclick="convertLead('${jesc(c.company_id)}')">Convert to customer</button>`:''}
      ${draftAll?`<button class="pill-btn" onclick="draft('${jesc(draftAll.email)}','${jesc(draftAll.name||'')}')">✉ Draft email</button>`:''}
      <span class="more">
        <button class="pill-btn ghost" aria-haspopup="true" aria-expanded="false"
                title="More actions" onclick="toggleMore(event)">⋯</button>
        <span class="more-menu" role="menu">
          <button role="menuitem" onclick="closeMore();openEditCompany('${jesc(c.company_id)}')">Edit company</button>
          ${c.role==='vendor'?`<button role="menuitem" onclick="closeMore();openEditVendor('${jesc(c.company_id)}')">Edit vendor details</button>`:''}
          <button role="menuitem" class="danger" onclick="closeMore();deleteCompany('${jesc(c.company_id)}')">Delete ${esc(c.role)}…</button>
        </span>
      </span>
    </span>
  </div>`;

  // What this customer owes, before any table. Reading it off the invoice list
  // and doing the arithmetic was the operator's job until now.
  h += companySummary(c);

  if(c.role==='vendor'){
    const v=vendorById[selected]||{};
    h+=`<div class="section"><h2>Vendor details</h2>
      <div class="kv"><span class="k">Rep</span><span>${esc(v.rep||'—')}</span></div>
      <div class="kv"><span class="k">Email</span><span>${v.email?`<a href="#" onclick="draft('${jesc(v.email)}','${jesc(v.rep||'')}');return false">${esc(v.email)}</a>`:'—'}</span></div>
      <div class="kv"><span class="k">Phone</span><span>${esc(v.phone||'—')}</span></div>
      <div class="kv"><span class="k">Offerings</span><span>${esc(v.offerings||'—')}</span></div>
      <div class="kv"><span class="k">Send POs to</span><span>${esc(v.po_routing||'—')}</span></div>
      <div class="kv"><span class="k">Send invoices to</span><span>${esc(v.invoice_routing||'—')}</span></div>
      ${v.notes?`<div class="kv"><span class="k">Notes</span><span>${esc(v.notes)}</span></div>`:''}
    </div>`;
  }

  if(c.notes){
    h+=`<div class="section"><h2>Notes</h2><div style="white-space:pre-wrap">${esc(c.notes)}</div></div>`;
  }

  h+=`<div class="section"><h2>Contacts (${cts.length})</h2>`;
  h+= cts.length?`<table><thead><tr><th>Name</th><th>Title</th><th>Email</th><th>Phone</th><th>Last action</th><th></th></tr></thead><tbody>`+
    cts.map(x=>`<tr><td>${esc(x.name||'—')}</td><td class="muted">${esc(x.title||'')}</td>
      <td class="contact">${x.email?`<a href="#" onclick="draft('${jesc(x.email)}','${jesc(x.name||'')}');return false">${esc(x.email)}</a>`:'—'}</td>
      <td class="muted nw">${esc(x.phone||'')}</td><td class="muted num">${esc(fmtDate(x.last_action))}</td>
      <td><button class="pill-btn" style="padding:2px 8px;font-size:11px" onclick="openEditContact('${jesc(selected)}','${jesc(x.email||'')}','${jesc(x.name||'')}')">Edit</button></td></tr>`).join('')+
    `</tbody></table>`:emptyState('No contacts yet.',
      `<button class="pill-btn" onclick="openNewContact('${jesc(selected)}')">+ Add contact</button>`);
  h+=`</div>`;

  h+=`<div class="section"><h2>Projects (${prs.length})</h2>`;
  h+= prs.length?`<table><thead><tr><th>Project #</th><th>Description</th><th>Status</th><th>Owner</th>
      <th class="num">Revenue</th><th class="num">Margin</th><th>Collection</th></tr></thead><tbody>`+
    prs.map(p=>`<tr class="click" onclick="openProject('${jesc(p.project_no||'')}')">
      <td><b>${esc(p.project_no||'—')}</b></td><td>${esc(p.description||'')}</td>
      <td>${statusBadge(p.status)}</td><td>${esc(arr(p.owner).join(', '))||'—'}</td>
      <td class="num">${money(p.revenue)}</td><td class="num">${pct(p.margin)}</td>
      <td>${statusPill(p.collection_status)}</td></tr>`).join('')+
    `</tbody><tfoot><tr><td colspan="4">Total</td>
      <td class="num">${money(prs.reduce((a,p)=>a+numv(p.revenue),0))}</td>
      <td class="num"></td><td></td></tr></tfoot></table>`
    :emptyState('No projects yet.', sells
      ? `<button class="pill-btn" onclick="openNewProject('${jesc(selected)}')">+ New project</button>`
      : '<span class="muted">Projects belong to customers, not suppliers.</span>');
  h+=`</div>`;

  const invs=invoicesByCo[selected]||[];
  if(invs.length){
    // shared with the Receivables view -- see invoiceBucket(). Two definitions
    // of "is this overdue" is two different answers about the same money.
    const todayStr = todayISO(), soonStr = soonISO();
    const bucketOf = (v)=> invoiceBucket(v, todayStr, soonStr);
    const grouped={}; invs.forEach(v=>{(grouped[bucketOf(v)]=grouped[bucketOf(v)]||[]).push(v);});
    Object.values(grouped).forEach(list=>list.sort((a,b)=>(st(dueOn(a))||'9999').localeCompare(st(dueOn(b))||'9999')));
    let invRows='';
    BUCKET_ORDER.forEach(bk=>{
      const list=grouped[bk]; if(!list||!list.length) return;
      invRows+=`<tr><td colspan="8" class="due-group${bk==='Overdue'?' od':''}">${esc(bk)} (${list.length})</td></tr>`;
      invRows+=list.map(v=>{const ps=st(v.payment_status);const cls=ps==='paid'?'b-won':(ps.startsWith('partial')?'b-pending':'b-lost');
        const due=dueOn(v); const overdue = bk==='Overdue';
        const owed = outstanding(v); const late = daysLate(v);
        return `<tr><td><b class="nw">${esc(v.invoice_no||'—')}</b></td><td class="muted nw">${esc(v.client_po_raw||'')}</td>
        <td class="muted num">${esc(fmtDate(v.invoice_date))}</td>
        <td class="num">${owed==null?'<span class="muted">—</span>':(owed?`<b>${money(owed)}</b>`:'<span class="muted">—</span>')}</td>
        <td>${statusPill(ps)}</td>
        <td class="num ${overdue?'':'muted'}" ${overdue?'style="color:var(--red);font-weight:600"':''}>${esc(fmtDate(due)||'—')}${
          overdue&&late?`<div style="font-size:11px;font-weight:400">${late} days late</div>`:''}</td>
        <td class="muted" style="max-width:280px">${esc(st(v.payment_notes).slice(0,90))}</td>
        <td><button class="pill-btn" style="padding:2px 8px;font-size:11px" onclick="openEditInvoice('${jesc(selected)}','${jesc(v.invoice_no||'')}')">Edit</button></td></tr>`;}).join('');
    });
    h+=`<div class="section"><h2>Invoices / customer orders (${invs.length})</h2>
      <table><thead><tr><th>Invoice #</th><th>Client PO / order</th><th class="num">Invoiced</th><th class="num">Outstanding</th><th>Status</th><th class="num">Due on</th><th>Notes</th><th></th></tr></thead><tbody>`+
      invRows+
      `</tbody></table></div>`;
  }

  h+=`<div class="section"><h2>Shipments (${sps.length})</h2>`;
  h+= sps.length?`<table><thead><tr><th>Project #</th><th>Vendor PO</th><th>Stage</th><th>Ship date</th></tr></thead><tbody>`+
    sps.map(s=>`<tr class="click" onclick="openShipment('${jesc(s.shipment_id||'')}')">
      <td>${esc(s.project_no||'—')}</td><td>${esc(s.vendor_po_raw||'')}</td>
      <td><span class="badge b-stage">${esc(s.stage||'—')}</span></td>
      <td class="muted num">${esc(fmtDate(s.ship_date))}</td></tr>`).join('')+
    `</tbody></table>`:emptyState('No shipments yet.', prs.length
      ? `<button class="pill-btn" onclick="navFromDrawer(()=>openNewShipment('${jesc(st(prs[0].project_no))}'))">+ Add shipment</button>`
      : '<span class="muted">Add a project first — shipments hang off one.</span>');
  h+=`</div>`;

  // Outlook LAST. It used to open every company page with "No Outlook signal
  // on file", putting an empty section above the money on the screen he opens
  // to look at the money.
  h+=enrichmentSection(selected);
  document.getElementById('main').innerHTML=h;
}

/* One line under the customer's name: what they owe and how late it is.
   Uses the same outstanding()/invoiceBucket() the Receivables screen does, so
   the two cannot disagree about the same customer. */
function companySummary(c){
  const invs = invoicesByCo[c.company_id]||[];
  if(!invs.length) return '';
  const today = todayISO(), soon = soonISO();
  const open = invs.filter(v=>invoiceBucket(v,today,soon)!=='Paid');
  if(!open.length) return `<p class="co-sum"><span class="ok">All settled</span>
    <span class="muted">· nothing outstanding</span></p>`;
  const known = open.map(outstanding).filter(x=>x!=null);
  const owed = known.reduce((a,b)=>a+b,0);
  const lates = open.map(v=>daysLate(v,today)).filter(x=>x!=null && x>0);
  const oldest = lates.length ? Math.max.apply(null, lates) : 0;
  const missing = open.length - known.length;
  return `<p class="co-sum">
    <b class="${oldest?'late':''}">${money(owed)} outstanding</b>
    ${oldest?`<span class="late">· oldest ${oldest} days late</span>`:'<span class="muted">· none overdue</span>'}
    ${missing?`<span class="muted">· ${missing} with no amount on file</span>`:''}
    <a href="#" class="muted" onclick="setFilter('receivable');return false">see all receivables</a>
  </p>`;
}

function emptyState(text, action){
  return `<div class="empty-row"><span class="muted">${esc(text)}</span>${action||''}</div>`;
}

/* Overflow menu for the destructive/rare actions. Delete used to sit in the
   main row as a peer of "Draft email", last in line, which is exactly where
   the cursor ends up. */
function closeMore(){
  document.querySelectorAll('.more.show').forEach(el=>{
    el.classList.remove('show');
    const b = el.querySelector('button[aria-haspopup]');
    if(b) b.setAttribute('aria-expanded','false');
  });
}
function toggleMore(ev){
  ev.stopPropagation();
  const wrap = ev.currentTarget.parentNode;
  const wasOpen = wrap.classList.contains('show');
  closeMore();
  if(!wasOpen){
    wrap.classList.add('show');
    ev.currentTarget.setAttribute('aria-expanded','true');
  }
}
document.addEventListener('click', closeMore);
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeMore(); });

/* ------------------------------------------------------- project drawer -- */
function openProject(pno){
  const p=DATA.projects.find(x=>String(x.project_no)===String(pno)); if(!p) return;
  document.getElementById('dtitle').textContent='Project '+(pno||'');
  // revenue/total_cost/gross_profit/margin are independent stored values
  // (each read from its own tracker column, never computed from the
  // others) -- see pipeline/normalize.py -- so all four are safe to edit
  // as plain fields, same as everything else here. margin is stored as a
  // fraction (0.33 == 33%); the field shows/accepts a whole percent and
  // converts on save.
  const marginPct = (p.margin==null||isNaN(p.margin)) ? '' : Math.round(p.margin*10000)/100;
  document.getElementById('dbody').innerHTML=`
    <div class="kv"><span class="k">Company</span><span>${esc((companyById[p.company_id]||{}).display_name||p.company_name||'—')}</span></div>
    <div class="field"><label>Project #</label><input id="f_pno" value="${esc(p.project_no||'')}"/>
      <p class="muted" style="margin:4px 0 0;font-size:11px">Changing this updates every shipment and invoice linked to it — safe, but not instant to undo.</p></div>
    <div class="field"><label>Description</label><input id="f_desc" value="${esc(p.description||'')}"/></div>
    <div class="row2">
      <div class="field"><label>Location</label><input id="f_loc" value="${esc(p.location||'')}"/></div>
      <div class="field"><label>Deal date</label><input id="f_date" value="${esc(p.date||'')}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Client PO #</label><input id="f_cpo" value="${esc(p.client_po_no||'')}"/></div>
      <div class="field"><label>Invoice #</label><input id="f_inv" value="${esc(p.invoice_no||'')}"/></div>
    </div>
    <div class="field"><label><input type="checkbox" id="f_poflag" ${p.po_flag?'checked':''} style="width:auto;margin-right:6px;vertical-align:middle"/>PO on file</label></div>
    <hr style="border:none;border-top:1px solid var(--line);margin:14px 0"/>
    <div class="row2">
      <div class="field"><label>Status</label><select id="f_status">
        ${opts(['won','pending','lost'], p.status)}</select></div>
      <div class="field"><label>Collection</label><select id="f_coll">
        ${opts(['','open','partial:50%','paid'], p.collection_status)}</select></div>
    </div>
    <div class="field"><label>Live Tracker bucket</label>
      <select id="f_tracker" data-orig="${esc(st(p.tracker_status))}">
        ${trackerOpts(p.tracker_status)}</select>
      ${knownBucket(p.tracker_status) ? '' : (st(p.tracker_status)
        ? `<p class="muted" style="margin:4px 0 0;font-size:11px">This job is
             stored as <b>${esc(st(p.tracker_status))}</b>, which your tracker's
             legend does not name — it shows under "Status not recognised" on
             the Live screen. Pick a bucket here to correct it.</p>`
        : `<p class="muted" style="margin:4px 0 0;font-size:11px">Not on the
             Live screen. The import sets this from the colour of the row's
             notes cell in your tracker.</p>`)}</div>
    <div class="row2">
      <div class="field"><label>Revenue ($)</label><input id="f_revenue" type="number" step="0.01" value="${p.revenue==null?'':esc(p.revenue)}"/></div>
      <div class="field"><label>Total cost ($)</label><input id="f_cost" type="number" step="0.01" value="${p.total_cost==null?'':esc(p.total_cost)}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Gross profit ($)</label><input id="f_gp" type="number" step="0.01" value="${p.gross_profit==null?'':esc(p.gross_profit)}"/></div>
      <div class="field"><label>Margin (%)</label><input id="f_margin" type="number" step="0.1" value="${esc(marginPct)}"/></div>
    </div>
    <div class="field"><label>Owner (reps, comma-separated)</label><input id="f_owner" value="${esc(arr(p.owner).join(', '))}"/></div>
    <div class="field"><label>Open orders note <span class="muted"
      style="text-transform:none;font-weight:400">(the note shown on the Live
      screen)</span></label>
      <textarea id="f_oon" style="min-height:88px">${esc(p.open_orders_notes||'')}</textarea>
      <p class="muted" style="margin:4px 0 0;font-size:11px">This is the job's
        own note. Each vendor leg has a separate "Order notes" box of its
        own — editing one of those does not change this.</p></div>
    <div class="field"><label>Notes</label><textarea id="f_notes">${esc(p.notes||'')}</textarea></div>
    <div class="field"><label>Annotations (one per line)</label><textarea id="f_annos">${esc(arr(p.annotations).join('\n'))}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveProject('${jesc(pno)}')">Save changes</button>
    <button class="btn ghost" onclick="navFromDrawer(()=>openNewShipment('${jesc(pno)}'))" style="margin-left:8px">+ Add shipment</button>
    <button class="pill-btn" style="background:var(--red-soft);color:var(--red);margin-left:8px" onclick="deleteProject('${jesc(pno)}')">Delete project</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px" id="drawerNote"></p>`;
  document.getElementById('drawerNote').textContent = CRM.mode==='embedded'
    ? 'Demo mode: this save lasts only for this browser session.'
    : 'Saves persist to your CRM records through the validated write interface.';
  openDrawer();
}

function numOrNull(id){
  const v=document.getElementById(id).value;
  return v===''?null:parseFloat(v);
}

async function saveProject(pnoArg){
  // The number the STORE currently holds, which after a rename that already
  // landed is NOT the one baked into this button's onclick. Renaming is two
  // calls: if rename_project succeeds and update_project is then refused, the
  // drawer stays up (so the error and the typed values survive) but its
  // handlers still carry the old number. Comparing against that stale number
  // made a second Save re-fire the rename with an old_project_no the store no
  // longer had, reporting "rename failed" for a rename that had succeeded --
  // and the field save could never be retried. saveShipment already avoids
  // this by comparing against its live record; data-orig is the same idea for
  // a value that has no object to hang off.
  const pnoEl = document.getElementById('f_pno');
  let pno = pnoEl.getAttribute('data-orig');
  if(pno === null) pno = pnoArg;
  const newPno = pnoEl.value.trim();
  const marginRaw = numOrNull('f_margin');
  const fields = {
    description: document.getElementById('f_desc').value.trim() || null,
    location: document.getElementById('f_loc').value.trim() || null,
    date: document.getElementById('f_date').value.trim() || null,
    client_po_no: document.getElementById('f_cpo').value.trim() || null,
    invoice_no: document.getElementById('f_inv').value.trim() || null,
    po_flag: document.getElementById('f_poflag').checked,
    // || null: a project the tracker left without a status renders a blank
    // option (opts() no longer fabricates 'won'), and "" is refused by the
    // server for the WHOLE save. null is accepted and means 'still unset'.
    status: document.getElementById('f_status').value || null,
    collection_status: document.getElementById('f_coll').value || null,
    notes: document.getElementById('f_notes').value,
    // The note the Live screen shows. It had no editor anywhere: the only
    // writable copy was the shipment drawer's, which is a DIFFERENT field on a
    // different record -- so he would edit "Order notes" on a leg, see "Saved",
    // and watch the Live card not change. Sent as '' rather than null when
    // cleared, so emptying it is a real edit the changelog records and the next
    // re-import preserves; null would read as "never set".
    open_orders_notes: document.getElementById('f_oon').value,
    owner: document.getElementById('f_owner').value.split(',').map(s=>s.trim()).filter(Boolean),
    annotations: document.getElementById('f_annos').value.split('\n').map(s=>s.trim()).filter(Boolean),
    revenue: numOrNull('f_revenue'),
    total_cost: numOrNull('f_cost'),
    gross_profit: numOrNull('f_gp'),
    margin: marginRaw==null ? null : marginRaw/100,
  };
  // Sent ONLY when he actually changed it. Every other field here is sent
  // unconditionally, which is fine for fields the form always shows correctly
  // -- but this one can hold a value the server now refuses, and resending
  // that on an unrelated edit would fail the whole save with no way out from
  // inside the app. Same rule the date fields already follow: never send a
  // value the user did not touch.
  // `|| ''` on BOTH sides. A select showing no selection reads as '' while a
  // data-orig that was never written reads as null, and `'' !== null` is true
  // -- so an untouched control looked edited and every unrelated save cleared
  // the bucket. Comparing the normalised strings is right in the browser too:
  // "empty" and "absent" mean the same thing here and must compare equal.
  const trk = document.getElementById('f_tracker');
  if(trk && (trk.value || '') !== (trk.getAttribute('data-orig') || '')){
    fields.tracker_status = trk.value || null;
  }
  let renamed = false;
  if(newPno && newPno !== pno){
    const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
    btn.disabled=true; msg.className='saved';
    const rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno});
    if(!rr || !rr.ok){
      msg.textContent='✗ '+((rr&&rr.error)||'rename failed'); msg.className='saved show errc';
      btn.disabled=false;
      return;
    }
    // Mirror the rename across local state before the follow-up field save,
    // so update_project below targets the record under its new key and the
    // shipments/invoices sections re-render pointing at the right project.
    const p=DATA.projects.find(x=>String(x.project_no)===String(pno));
    if(p) p.project_no = newPno;
    DATA.shipments.forEach(s=>{
      if(String(s.project_no)===String(pno)) s.project_no=newPno;
      if(Array.isArray(s.all_project_nos))
        s.all_project_nos = s.all_project_nos.map(n=>String(n)===String(pno)?newPno:n);
    });
    DATA.invoices.forEach(i=>{ if(String(i.project_no)===String(pno)) i.project_no=newPno; });
    reindex();
    // The rename is committed, so record it on the control: a retry after a
    // refused field save must not fire it a second time.
    pnoEl.setAttribute('data-orig', newPno);
    pno = newPno;
    renamed = true;
    // Repaint now rather than only in doSave's ok branch. The store and DATA
    // both say the new number at this point; leaving the sidebar and main pane
    // on the old one for the duration of a FAILED field save showed the
    // operator a number that no longer existed anywhere.
    renderList(); renderMain();
  }
  const ok = await doSave('update_project', {project_no: pno, fields}, (r)=>{
    const p=DATA.projects.find(x=>String(x.project_no)===String(pno));
    Object.assign(p, r.project || fields);
  });
  // A rename changes the project_no baked into this drawer's own button
  // handlers (Delete, + Add shipment) -- reopen so they point at the new
  // number. Only done on rename: reopening on every ordinary save would
  // wipe the "Saved" flash (it replaces the #savedMsg node doSave just set).
  //
  // ONLY when the field save also succeeded. The rename and the field update
  // are two calls: the rename can land and the update be refused. Reopening
  // then replaced #dbody, which destroyed BOTH the error message doSave had
  // just written and every typed value -- redrawing from DATA the failed save
  // never updated. The operator saw the new project number with the old
  // figures, no error and no prompt, and would reasonably conclude it saved.
  if(renamed && ok) openProject(pno);
}

async function deleteProject(pno){
  const p=DATA.projects.find(x=>String(x.project_no)===String(pno));
  if(!confirm(`Delete project ${pno}${p&&p.description?' ('+p.description+')':''}? It and its shipments/invoices will be archived (hidden from the CRM) and can be restored later — nothing is permanently destroyed.`)) return;
  const r=await CRM.call('archive_project', {project_no:pno});
  if(r&&r.ok){
    DATA.projects=DATA.projects.filter(x=>String(x.project_no)!==String(pno));
    DATA.shipments=DATA.shipments.filter(x=>!(_shipmentProjectNos(x).has(String(pno))));
    DATA.invoices=DATA.invoices.filter(x=>String(x.project_no)!==String(pno));
    reindex(); kpis(); renderList(); closeDrawer();
    if(selected) renderMain();
  } else {
    alert('Delete failed: '+((r&&r.error)||'unknown error'));
  }
}

function _shipmentProjectNos(s){
  // arr(): all_project_nos stored as a string made .map throw here, and this
  // runs from deleteProject AFTER archive_project has already succeeded -- so
  // the project was archived server-side while the app kept listing it, with
  // no error and the drawer left open.
  const nos = arr(s.all_project_nos).length ? arr(s.all_project_nos)
    : (s.project_no ? [s.project_no] : []);
  return new Set(nos.map(st));
}

/* -------------------------------------------------------- create drawers -- */
function openNewProject(cid){
  const c=companyById[cid]; if(!c) return;
  document.getElementById('dtitle').textContent='New project — '+(c.display_name||cid);
  document.getElementById('dbody').innerHTML=`
    <div class="row2">
      <div class="field"><label>Project # (required)</label><input id="n_pno" placeholder="e.g. 1421"/></div>
      <div class="field"><label>Status</label><select id="n_status">
        ${['pending','won','lost'].map(s=>`<option>${s}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label>Description</label><input id="n_desc" placeholder="e.g. Pallet racking install"/></div>
    <div class="row2">
      <div class="field"><label>Revenue ($)</label><input id="n_rev" type="number" step="0.01"/></div>
      <div class="field"><label>Owner (reps)</label><input id="n_owner" placeholder="D, G"/></div>
    </div>
    <div class="field"><label>Notes</label><textarea id="n_notes"></textarea></div>
    <button class="btn" id="saveBtn" onclick="saveNewProject('${jesc(cid)}')">Create project</button>
    <span class="saved" id="savedMsg"></span>`;
  openDrawer();
}

async function saveNewProject(cid){
  const pno=document.getElementById('n_pno').value.trim();
  const msg=document.getElementById('savedMsg');
  if(!pno){ msg.textContent='✗ project # is required'; msg.className='saved show errc'; return; }
  const rev=parseFloat(document.getElementById('n_rev').value);
  const fields={project_no:pno, company_id:cid,
    company_name:(companyById[cid]||{}).display_name,
    status:document.getElementById('n_status').value,
    description:document.getElementById('n_desc').value||null,
    revenue:isNaN(rev)?null:rev,
    owner:document.getElementById('n_owner').value.split(',').map(s=>s.trim()).filter(Boolean),
    notes:document.getElementById('n_notes').value||null,
    year:new Date().getFullYear()};
  await doSave('create_project', {fields}, (r)=>{
    DATA.projects.push(r.project||fields); reindex(); renderList();
    closeDrawer();
  });
}

function openNewContact(cid){
  const c=companyById[cid]; if(!c) return;
  document.getElementById('dtitle').textContent='Add contact — '+(c.display_name||cid);
  document.getElementById('dbody').innerHTML=`
    <div class="row2">
      <div class="field"><label>Name (required)</label><input id="n_name"/></div>
      <div class="field"><label>Title</label><input id="n_title"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Email</label><input id="n_email" type="email"/></div>
      <div class="field"><label>Phone</label><input id="n_phone"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveNewContact('${jesc(cid)}')">Add contact</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">Matched by email if one already exists — no duplicates.</p>`;
  openDrawer();
}

async function saveNewContact(cid){
  const name=document.getElementById('n_name').value.trim();
  const msg=document.getElementById('savedMsg');
  if(!name){ msg.textContent='✗ name is required'; msg.className='saved show errc'; return; }
  const fields={company_id:cid, company_name:(companyById[cid]||{}).display_name,
    name, email:document.getElementById('n_email').value.trim()||null,
    title:document.getElementById('n_title').value.trim()||null,
    phone:document.getElementById('n_phone').value.trim()||null};
  await doSave('upsert_contact', {fields}, (r)=>{
    const rec=r.contact||fields;
    const i=DATA.contacts.findIndex(x=>x.company_id===cid &&
      ((rec.email && x.email===rec.email) || x.name===rec.name));
    if(i>=0) DATA.contacts[i]=rec; else DATA.contacts.push(rec);
    reindex(); renderList(); closeDrawer();
  });
}

/* Edit an existing contact. Identified by (company_id, email) when the
   contact has an email, else (company_id, name) -- the same match key
   upsert_contact itself uses, so re-submitting updates in place rather
   than creating a duplicate as long as at least one of the two is kept
   the same as the version this drawer was opened with. */
function openEditContact(cid, email, name){
  const list = contactsByCo[cid]||[];
  const c = (email ? list.find(x=>x.email===email) : null) || list.find(x=>x.name===name);
  if(!c) return;
  document.getElementById('dtitle').textContent='Edit contact — '+(c.name||'');
  document.getElementById('dbody').innerHTML=`
    <div class="row2">
      <div class="field"><label>Name (required)</label><input id="e_c_name" value="${esc(c.name||'')}"/></div>
      <div class="field"><label>Title</label><input id="e_c_title" value="${esc(c.title||'')}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Email</label><input id="e_c_email" type="email" value="${esc(c.email||'')}"/></div>
      <div class="field"><label>Phone</label><input id="e_c_phone" value="${esc(c.phone||'')}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Location</label><input id="e_c_loc" value="${esc(c.location||'')}"/></div>
      <div class="field"><label>Last action date (manual)</label>${dateInput('e_c_lastact', c.last_action)}</div>
    </div>
    <div class="field"><label>Action notes</label><textarea id="e_c_notes">${esc(c.action_notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveEditContact('${jesc(cid)}','${jesc(c.email||'')}','${jesc(c.name||'')}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">Matched by email (or by name if there's no email) — changing both at once can create a second contact instead of updating this one.</p>`;
  openDrawer();
  snapDates(['e_c_lastact']);
}

async function saveEditContact(cid, origEmail, origName){
  const name=document.getElementById('e_c_name').value.trim();
  const msg=document.getElementById('savedMsg');
  if(!name){ msg.textContent='✗ name is required'; msg.className='saved show errc'; return; }
  const fields={company_id:cid, company_name:(companyById[cid]||{}).display_name,
    name, email:document.getElementById('e_c_email').value.trim()||null,
    title:document.getElementById('e_c_title').value.trim()||null,
    phone:document.getElementById('e_c_phone').value.trim()||null,
    location:document.getElementById('e_c_loc').value.trim()||null,

    action_notes:document.getElementById('e_c_notes').value.trim()||null};
  // dateIfChanged is right for an UPDATE: it stops a save that only meant to
  // edit a phone number from rewriting a tracker-format date. But it is wrong
  // for a CREATE, where there is no stored value to protect and an unsent
  // field is simply lost -- every other field above is already sent
  // unconditionally for exactly that reason.
  //
  // upsert_contact matches on email (when one is supplied), else on
  // (company_id, name). So it can only fall through to create when the name
  // changed AND there is no unchanged email left to match on -- which is the
  // "changing both at once can create a second contact" case the drawer warns
  // about. Snapshot the control in that case: its value is faithful either
  // way, since dateInput falls back to a text box holding the raw string
  // whenever isoDate cannot parse it.
  const emailNow=document.getElementById('e_c_email').value.trim();
  if(name!==origName && (!emailNow || emailNow!==origEmail)){
    const el=document.getElementById('e_c_lastact');
    if(el) fields.last_action = el.value || null;
  } else {
    dateIfChanged('e_c_lastact', fields, 'last_action');
  }
  let splitOff = false;
  await doSave('upsert_contact', {fields}, (r)=>{
    const rec=r.contact||fields;
    const i=DATA.contacts.findIndex(x=>x.company_id===cid &&
      ((origEmail && x.email===origEmail) || (!origEmail && x.name===origName)));
    // Honour the server's own verdict. upsert_contact matches on email, else on
    // (company_id, name) -- change BOTH and it creates a second contact and
    // leaves the original untouched. Overwriting the original locally showed a
    // clean rename while the store held two people, and the duplicate only
    // surfaced on the next full refresh.
    if(r.op === 'create'){
      DATA.contacts.push(rec);
      splitOff = i >= 0;              // an edit that became a second record
    } else if(i>=0){ DATA.contacts[i]=rec; } else { DATA.contacts.push(rec); }
    reindex(); renderList();
    // ALWAYS close. Leaving it open kept the Save button bound to the original
    // (origEmail, origName), so a second press matched the NEW email
    // server-side and overwrote the original row in the local cache -- the
    // store stayed right while the app showed the same person twice.
    closeDrawer();
  });
  if(splitOff) noticeToast('Saved as a NEW contact — the original is still '
                         + 'there, because the name and the email both changed.');
}

function openNewShipment(pno){
  document.getElementById('dtitle').textContent='Add shipment — project '+pno;
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>Vendor PO</label><input id="n_po" placeholder="e.g. PO# 4521 Acme Freight"/></div>
    <div class="row2">
      <div class="field"><label>Stage</label><select id="n_stage">
        ${STAGES.map(x=>`<option ${x==='Ordered'?'selected':''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>Ship date</label><input id="n_sdate" type="date"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveNewShipment('${jesc(pno)}')">Add shipment</button>
    <span class="saved" id="savedMsg"></span>`;
  openDrawer();
}

async function saveNewShipment(pno){
  const fields={vendor_po_raw:document.getElementById('n_po').value||null,
    stage:document.getElementById('n_stage').value,
    ship_date:document.getElementById('n_sdate').value||null};
  await doSave('create_shipment', {project_no:pno, fields}, (r)=>{
    if(r.shipment){ DATA.shipments.push(r.shipment); reindex(); renderList(); }
    closeDrawer();
  });
}

/* ------------------------------------------- company / vendor create+delete */
function openNewCompany(role){
  const isV = role==='vendor';
  const label = isV ? 'vendor' : (role==='lead' ? 'lead' : 'customer');
  document.getElementById('dtitle').textContent = 'Add ' + label;
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>${label[0].toUpperCase()+label.slice(1)} name (required)</label><input id="c_name"/></div>
    ${isV?`
      <div class="row2">
        <div class="field"><label>Rep / contact</label><input id="c_rep"/></div>
        <div class="field"><label>HQ location</label><input id="c_hq"/></div>
      </div>
      <div class="row2">
        <div class="field"><label>Email</label><input id="c_email" type="email"/></div>
        <div class="field"><label>Phone</label><input id="c_phone"/></div>
      </div>
      <div class="field"><label>Offerings</label><input id="c_offer" placeholder="e.g. Pallet racking, shelving"/></div>
      <div class="row2">
        <div class="field"><label>Send POs to</label><input id="c_po"/></div>
        <div class="field"><label>Send invoices to</label><input id="c_inv"/></div>
      </div>`
    :`<div class="field"><label>Primary location</label><input id="c_loc" placeholder="e.g. Louisville, KY"/></div>
      <div class="field"><label>Notes</label><textarea id="c_notes" placeholder="${role==='lead'?'Where this lead came from, what they need, next step…':'Anything worth remembering'}"></textarea></div>`}
    <button class="btn" id="saveBtn" onclick="saveNewCompany('${jesc(role)}')">Add ${label}</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">Saved to your CRM records; the name must be unique.</p>`;
  openDrawer();
}

async function saveNewCompany(role){
  const name=document.getElementById('c_name').value.trim();
  const msg=document.getElementById('savedMsg');
  if(!name){ msg.textContent='✗ name is required'; msg.className='saved show errc'; return; }
  const val=(id)=>{const el=document.getElementById(id);return el&&el.value.trim()?el.value.trim():null;};
  if(role==='vendor'){
    const fields={display_name:name, rep:val('c_rep'), hq_location:val('c_hq'),
      email:val('c_email'), phone:val('c_phone'), offerings:val('c_offer'),
      po_routing:val('c_po'), invoice_routing:val('c_inv')};
    await doSave('create_vendor', {fields}, (r)=>{
      const v=r.vendor||fields; (DATA.vendors=DATA.vendors||[]).push(v);
      if(!DATA.companies.find(x=>x.company_id===v.company_id))
        DATA.companies.push({company_id:v.company_id,display_name:name,role:'vendor',domains:[],locations:[]});
      reindex(); renderList(); closeDrawer(); if(v.company_id) select(v.company_id);
    });
  } else {
    const loc=val('c_loc'), notes=val('c_notes');
    const fields={display_name:name, role:(role==='lead'?'lead':'customer'),
      locations:loc?[loc]:[], primary_location:loc, notes};
    await doSave('create_company', {fields}, (r)=>{
      const c=r.company||fields; DATA.companies.push(c);
      reindex(); renderList(); closeDrawer(); if(c.company_id) select(c.company_id);
    });
  }
}

/* Edit the company record itself (name, primary location) -- distinct
   from "Edit vendor", which only touches the separate vendor-detail
   record (rep/email/phone/offerings/routing). Role is deliberately not
   editable here: reclassifying customer<->vendor also needs a matching
   vendor-detail record created/removed, which this simple form can't
   safely do -- leave that as a chat-driven change. */
function openEditCompany(cid){
  const c=companyById[cid]; if(!c) return;
  document.getElementById('dtitle').textContent='Edit company — '+(c.display_name||cid);
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>Company name (required)</label><input id="e_co_name" value="${esc(c.display_name||'')}"/></div>
    <div class="field"><label>Primary location</label><input id="e_co_loc" value="${esc(c.primary_location||'')}" placeholder="e.g. Louisville, KY"/></div>
    <div class="field"><label>Notes</label><textarea id="e_co_notes" placeholder="Anything worth remembering about this company">${esc(c.notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveEditCompany('${jesc(cid)}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">Customer/vendor type isn't editable here — ask Claude in chat if a company needs to be reclassified.</p>`;
  openDrawer();
}

async function saveEditCompany(cid){
  const name=document.getElementById('e_co_name').value.trim();
  const msg=document.getElementById('savedMsg');
  if(!name){ msg.textContent='✗ company name is required'; msg.className='saved show errc'; return; }
  const loc=document.getElementById('e_co_loc').value.trim()||null;
  const notes=document.getElementById('e_co_notes').value.trim()||null;
  const fields={display_name:name, primary_location:loc, locations:loc?[loc]:[], notes};
  await doSave('update_company', {company_id:cid, fields}, (r)=>{
    const c=r.company||Object.assign(companyById[cid]||{company_id:cid}, fields);
    const i=DATA.companies.findIndex(x=>x.company_id===cid);
    if(i>=0) DATA.companies[i]=c;
    reindex(); renderList(); closeDrawer();
  });
}

async function convertLead(cid){
  const c=companyById[cid]; if(!c) return;
  if(!confirm(`Convert ${c.display_name||cid} from a lead to a customer?`)) return;
  const r=await CRM.call('convert_lead', {company_id:cid});
  if(r&&r.ok){
    const updated=r.company||Object.assign(c,{role:'customer'});
    const i=DATA.companies.findIndex(x=>x.company_id===cid);
    if(i>=0) DATA.companies[i]=updated;
    reindex(); renderList(); renderMain();
  } else {
    alert('Convert failed: '+((r&&r.error)||'unknown error'));
  }
}

function openEditVendor(cid){
  const v=vendorById[cid]||{company_id:cid,display_name:(companyById[cid]||{}).display_name};
  document.getElementById('dtitle').textContent='Edit vendor — '+(v.display_name||cid);
  document.getElementById('dbody').innerHTML=`
    <div class="row2">
      <div class="field"><label>Rep / contact</label><input id="e_rep" value="${esc(v.rep||'')}"/></div>
      <div class="field"><label>HQ location</label><input id="e_hq" value="${esc(v.hq_location||'')}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Email</label><input id="e_email" value="${esc(v.email||'')}"/></div>
      <div class="field"><label>Phone</label><input id="e_phone" value="${esc(v.phone||'')}"/></div>
    </div>
    <div class="field"><label>Offerings <span class="muted" style="text-transform:none;font-weight:400">(products/services this vendor provides)</span></label><input id="e_offer" value="${esc(v.offerings||'')}"/></div>
    <div class="row2">
      <div class="field"><label>Send POs to</label><input id="e_po" value="${esc(v.po_routing||'')}"/></div>
      <div class="field"><label>Send invoices to</label><input id="e_inv" value="${esc(v.invoice_routing||'')}"/></div>
    </div>
    <div class="field"><label>Notes</label><textarea id="e_notes" placeholder="Anything else worth remembering about this vendor">${esc(v.notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveEditVendor('${jesc(cid)}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>`;
  openDrawer();
}

async function saveEditVendor(cid){
  const val=(id)=>{const el=document.getElementById(id);return el&&el.value.trim()?el.value.trim():null;};
  const fields={rep:val('e_rep'),hq_location:val('e_hq'),email:val('e_email'),
    phone:val('e_phone'),offerings:val('e_offer'),notes:val('e_notes'),
    po_routing:val('e_po'),invoice_routing:val('e_inv')};
  await doSave('update_vendor', {company_id:cid, fields}, (r)=>{
    const v=r.vendor||Object.assign(vendorById[cid]||{company_id:cid},fields);
    const i=(DATA.vendors||[]).findIndex(x=>x.company_id===cid);
    if(i>=0) DATA.vendors[i]=v; else (DATA.vendors=DATA.vendors||[]).push(v);
    reindex(); closeDrawer();
  });
}

/* Create and edit a client invoice / customer order. As of v0.1.26
   invoice_date and the linked project_no are editable too; invoice_no is not
   (rename_invoice owns that, because it also moves any shipment leg carrying
   the number), and payment_status_raw/sheet_row stay server-side only --
   they record what the source workbook literally said. Matched by
   (company_id, invoice_no), the same key server-side. */
function openNewInvoice(cid){
  const co = companyById[cid] || {};
  document.getElementById('dtitle').textContent = 'New invoice — ' + (co.display_name || cid);
  document.getElementById('dbody').innerHTML = `
    <div class="row2">
      <div class="field"><label>Invoice #</label><input id="n_iv_no" placeholder="required"/></div>
      <div class="field"><label>Invoice date</label><input id="n_iv_date" type="date"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Project # <span class="muted" style="text-transform:none;font-weight:400">(optional)</span></label><input id="n_iv_proj"/></div>
      <div class="field"><label>Client PO / order</label><input id="n_iv_po"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Status</label><select id="n_iv_status">
        ${['open','partial:50%','paid'].map(x=>`<option value="${x}">${x}</option>`).join('')}</select></div>
      <div class="field"><label>Due on <span class="muted" style="text-transform:none;font-weight:400">(blank = auto Net 30)</span></label><input id="n_iv_due" type="date"/></div>
    </div>
    <div class="field"><label>Notes</label><textarea id="n_iv_notes"></textarea></div>
    <button class="btn" id="saveBtn" onclick="saveNewInvoice('${jesc(cid)}')">Create invoice</button>
    <span class="saved" id="savedMsg"></span>`;
  openDrawer();
}

async function saveNewInvoice(cid){
  const fields = {
    invoice_no: document.getElementById('n_iv_no').value.trim(),
    invoice_date: document.getElementById('n_iv_date').value || null,
    project_no: document.getElementById('n_iv_proj').value.trim() || null,
    client_po_raw: document.getElementById('n_iv_po').value.trim() || null,
    payment_status: document.getElementById('n_iv_status').value,
    due_on: document.getElementById('n_iv_due').value || null,
    payment_notes: document.getElementById('n_iv_notes').value.trim() || null,
  };
  if(!fields.invoice_no){
    const m = document.getElementById('savedMsg');
    m.textContent = '✗ Invoice # is required'; m.className = 'saved show errc';
    return;
  }
  await doSave('create_invoice', {company_id: cid, fields}, (r)=>{
    DATA.invoices.push(r.invoice || Object.assign({company_id: cid}, fields));
    reindex(); kpis(); renderList(); renderMain(); closeDrawer();
  });
}

function openEditInvoice(cid, invoiceNo){
  const v=(invoicesByCo[cid]||[]).find(x=>String(x.invoice_no)===String(invoiceNo));
  if(!v) return;
  document.getElementById('dtitle').textContent='Edit invoice — '+(v.invoice_no||'');
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>Invoice #</label><input id="e_iv_no" value="${esc(st(v.invoice_no))}"/>
      <p class="muted" style="margin:4px 0 0;font-size:11px">Changing this also updates any shipment leg logged under this invoice number.</p></div>
    <div class="row2">
      <div class="field"><label>Invoice date</label>${dateInput('e_iv_date', v.invoice_date)}</div>
      <div class="field"><label>Project # <span class="muted" style="text-transform:none;font-weight:400">(blank = unlinked)</span></label><input id="e_iv_proj" value="${esc(st(v.project_no))}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Status</label><select id="e_iv_status">
        ${opts(['open','partial:50%','paid'], v.payment_status)}</select></div>
      <div class="field"><label>Paid on</label>${dateInput('e_iv_paydate', v.pay_date)}</div>
    </div>
    <div class="row2">
      <div class="field"><label>Client PO / order</label><input id="e_iv_po" value="${esc(v.client_po_raw||'')}"/></div>
      <div class="field"><label>Due on <span class="muted" style="text-transform:none;font-weight:400">(blank = auto Net 30 from invoice date)</span></label>${dateInput('e_iv_due', v.due_on)}</div>
    </div>
    <div class="field"><label>Notes</label><textarea id="e_iv_notes">${esc(v.payment_notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveEditInvoice('${jesc(cid)}','${jesc(v.invoice_no||'')}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>`;
  openDrawer();
  snapDates(['e_iv_date','e_iv_paydate','e_iv_due']);
}

async function saveEditInvoice(cid, invoiceNo){
  const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
  // data-orig, not the closure argument -- same two-call rename trap as
  // saveProject: once rename_invoice has landed, this button still carries the
  // OLD number, and comparing against it re-fired the rename on every retry.
  const noEl = document.getElementById('e_iv_no');
  const storedNo = noEl.getAttribute('data-orig') === null
    ? invoiceNo : noEl.getAttribute('data-orig');
  let invoiceNoNow = storedNo;
  const newNo = noEl.value.trim();
  if(newNo && newNo !== storedNo){
    btn.disabled=true; msg.className='saved';
    const rr = await CRM.call('rename_invoice', {company_id:cid, old_invoice_no:storedNo, new_invoice_no:newNo});
    if(!rr || !rr.ok){
      msg.textContent='✗ '+((rr&&rr.error)||'rename failed'); msg.className='saved show errc';
      btn.disabled=false;
      return;
    }
    const p=(invoicesByCo[cid]||[]).find(x=>String(x.invoice_no)===String(storedNo));
    if(p) p.invoice_no=newNo;
    DATA.shipments.forEach(s=>{ if(s.company_id===cid && String(s.invoice_no)===String(storedNo)) s.invoice_no=newNo; });
    reindex();
    noEl.setAttribute('data-orig', newNo);   // committed; do not rename twice
    invoiceNoNow = newNo;
    renderList(); renderMain();
  }
  const fields={
    payment_status: document.getElementById('e_iv_status').value || null,
    client_po_raw: document.getElementById('e_iv_po').value.trim() || null,
    payment_notes: document.getElementById('e_iv_notes').value.trim() || null,
  };
  // Dates contribute only when the control actually changed -- see
  // dateInput()/dateIfChanged(). Sending them unconditionally is what wiped a
  // non-ISO invoice_date on a save that only meant to flip the status.
  dateIfChanged('e_iv_date', fields, 'invoice_date');
  dateIfChanged('e_iv_paydate', fields, 'pay_date');
  dateIfChanged('e_iv_due', fields, 'due_on');
  // project_no is sent even when blank: an empty box is a deliberate unlink,
  // which the server normalizes to null.
  fields.project_no = document.getElementById('e_iv_proj').value.trim() || null;
  await doSave('update_invoice', {company_id:cid, invoice_no:invoiceNoNow, fields}, (r)=>{
    const rec=r.invoice||Object.assign({}, (invoicesByCo[cid]||[]).find(x=>String(x.invoice_no)===String(invoiceNoNow)), fields);
    const i=DATA.invoices.findIndex(x=>x.company_id===cid && String(x.invoice_no)===String(invoiceNoNow));
    if(i>=0) DATA.invoices[i]=rec;
    reindex(); closeDrawer();
  });
}

async function deleteCompany(cid){
  const c=companyById[cid]||{};
  if(!confirm(`Delete ${c.display_name||cid}? It will be archived (hidden from the CRM) and can be restored later — nothing is permanently destroyed.`)) return;
  const r=await CRM.call('archive_company', {company_id:cid});
  if(r&&r.ok){
    DATA.companies=DATA.companies.filter(x=>x.company_id!==cid);
    DATA.vendors=(DATA.vendors||[]).filter(x=>x.company_id!==cid);
    if(selected===cid){ selected=null; document.getElementById('main').innerHTML='<div class="empty">Deleted. Select a company to continue.</div>'; }
    reindex(); kpis(); renderList();
  } else {
    alert('Delete failed: '+((r&&r.error)||'unknown error'));
  }
}

/* ------------------------------------------------------ shipment drawer -- */
const STAGES=['Ordered','Shipped','Delivered','Installed','On Hold','Cancelled'];
function openShipment(sid){
  const s=DATA.shipments.find(x=>x.shipment_id===sid); if(!s) return;
  document.getElementById('dtitle').textContent='Shipment '+sid;
  document.getElementById('dbody').innerHTML=`
    <div class="kv"><span class="k">Client</span><span>${esc(s.client_name||'—')}</span></div>
    <div class="field"><label>Project #</label><input id="s_pno" value="${esc(s.project_no||'')}" placeholder="leave blank to unlink"/>
      <p class="muted" style="margin:4px 0 0;font-size:11px">${s.linked_to_project?'':'Currently unlinked — vendor-PO keyed. '}Changing this moves the shipment to a different project; the new project # must already exist.</p></div>
    <div class="field"><label>Vendor PO</label><input id="s_po" value="${esc(s.vendor_po_raw||'')}"/></div>
    <hr style="border:none;border-top:1px solid var(--line);margin:14px 0"/>
    <div class="row2">
      <div class="field"><label>Stage</label><select id="s_stage">
        ${opts(STAGES, s.stage)}</select></div>
      <div class="field"><label>Ship date</label>${dateInput('s_date', s.ship_date)}</div>
    </div>
    <div class="row2">
      <div class="field"><label>Start date</label>${dateInput('s_start', s.start_date)}</div>
      <div class="field"><label>ETA</label>${dateInput('s_eta', s.eta)}</div>
    </div>
    <div class="field"><label>Order notes</label><textarea id="s_notes">${esc(s.open_orders_notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveShipment('${jesc(sid)}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">${CRM.mode==='embedded'
      ? 'Demo mode: this save lasts only for this browser session.'
      : 'Stage changes persist to your CRM records (Ordered → Shipped → Delivered → Installed).'}</p>`;
  openDrawer();
  snapDates(['s_date','s_start','s_eta']);
}

async function saveShipment(sid){
  const s=DATA.shipments.find(x=>x.shipment_id===sid);
  const newPno = document.getElementById('s_pno').value.trim();
  const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
  // st(), not (s.project_no||''): newPno is a trimmed input string, so a
  // numerically-stored project_no would never compare equal and every save
  // would fire a pointless reassign_shipment.
  if(s && newPno !== st(s.project_no)){
    btn.disabled=true; msg.className='saved';
    const rr = await CRM.call('reassign_shipment', {shipment_id: sid, new_project_no: newPno || null});
    if(!rr || !rr.ok){
      msg.textContent='✗ '+((rr&&rr.error)||'reassign failed'); msg.className='saved show errc';
      btn.disabled=false;
      return;
    }
    Object.assign(s, rr.shipment);
    reindex(); renderList();
  }
  const fields = {
    vendor_po_raw: document.getElementById('s_po').value.trim() || null,
    // dates contributed only when actually changed -- advancing a stage must
    // not null a tracker-format ship_date. Same mechanism as the invoice drawer.
    open_orders_notes: document.getElementById('s_notes').value.trim() || null,
  };
  // stage is OMITTED when blank rather than sent as "". A leg stored with no
  // stage renders a blank option, and the server rejects both "" and null for
  // stage -- which would refuse the whole save (vendor PO, notes, dates) over
  // a field the operator never touched.
  const stageNow = document.getElementById('s_stage').value;
  if(stageNow) fields.stage = stageNow;
  dateIfChanged('s_date', fields, 'ship_date');
  dateIfChanged('s_start', fields, 'start_date');
  dateIfChanged('s_eta', fields, 'eta');
  await doSave('update_shipment', {shipment_id: sid, fields}, (r)=>{
    Object.assign(s, r.shipment || fields);
    if(selected) renderMain();
    // closeDrawer, as the invoice drawer does. The date controls' data-orig
    // baseline is snapshotted by openShipment AFTER the inputs are populated,
    // so it is only correct for as long as the drawer's contents match what
    // was saved. Leaving it open let a change-save-revert-save sequence send
    // {} on the second save: the store kept the first value while the drawer
    // showed the second. Reopening re-snaps against the saved record.
    closeDrawer();
  });
}

/* ------------------------------------------------------------ save core -- */
/* Returns TRUE only when the store actually took the write. Callers that do
   something irreversible afterwards -- saveProject's reopen-after-rename --
   must branch on this: doSave reports failure by writing into #savedMsg and
   never throws, so `await doSave(...)` alone cannot tell the two apart. */
async function doSave(tool, args, applyLocal){
  const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
  btn.disabled=true; msg.className='saved';
  // Lock the WHOLE form, not just the button.
  //
  // Every caller reads its fields into `args` before calling doSave, so
  // anything typed while the call is in flight is not in the payload. Ten of
  // the eleven callers close the drawer from inside applyLocal, and
  // closeDrawer clears drawerDirty -- so those keystrokes were dropped with no
  // prompt and no beforeunload warning. An earlier attempt at this used a
  // sequence counter checked after applyLocal, which could never fire on those
  // ten paths because the flag had already been zeroed by then.
  //
  // Not solvable by accounting after the fact: make the window not exist.
  // `disabled` rather than `inert` because it has no support question, and the
  // finally below restores exactly what was changed.
  const locked = [];
  const body = document.getElementById('dbody');
  if(body.querySelectorAll){
    body.querySelectorAll('input,select,textarea').forEach(el=>{
      if(!el.disabled){ el.disabled = true; locked.push(el); }
    });
  }
  try{
    const r = await CRM.call(tool, args);
    if (r && r.ok){
      applyLocal(r);
      // The work is on disk, so the drawer is no longer dirty. The form was
      // locked for the whole round trip, so there is nothing newer to lose.
      // Not every save path closes -- saveProject deliberately stays open so
      // the "Saved" flash survives -- and without this the flag stayed TRUE
      // over a written record, so the next Escape asked "discard your unsaved
      // changes?" about changes that were already saved. The danger is not the
      // wrong prompt, it is that it trains the operator to dismiss the prompt
      // that is real.
      drawerDirty = false;
      msg.textContent='✓ Saved'; msg.className='saved show okc';
      kpis(); renderMain();
      return true;
    }
    msg.textContent='✗ ' + ((r && r.error) || 'save failed'); msg.className='saved show errc';
    return false;
  }catch(e){
    msg.textContent='✗ ' + e.message; msg.className='saved show errc';
    return false;
  }finally{
    locked.forEach(el=>{ el.disabled = false; });
    btn.disabled=false;
    setTimeout(()=>msg.classList.remove('show'), 2500);
  }
}

function noticeToast(text){
  // NOT #savedMsg: doSave's finally schedules a 2.5s class removal on that same
  // element, so a message written after doSave returns was silently faded out.
  // This is the same surface draftReady uses, and it persists until dismissed.
  const el = document.getElementById('noticeToast') || (()=>{
    const d = document.createElement('div');
    d.id = 'noticeToast'; d.className = 'mvp live';
    d.style.cssText = 'bottom:52px;left:12px;max-width:420px;line-height:1.5';
    document.body.appendChild(d); return d;
  })();
  el.textContent = '⚠ ' + text + '  (click to dismiss)';
  el.onclick = ()=>{ el.remove(); };
}
/* ---------------------------------------------------- drawer open/close --
   One #drawer serves all eleven editors, so this lives in one place.

   There are deliberately TWO closes:

     closeDrawer()         unconditional. Every save path calls this, and a
                           save that already succeeded must never be
                           interrupted by a prompt.
     requestCloseDrawer()  user-initiated (scrim, Esc, the X). Asks first if
                           the form has been touched.

   The prompt exists because this change makes closing EASY. The X was a
   deliberate act; clicking beside a drawer is not, and the store is the only
   copy of these receivables -- so a stray click must not silently discard
   something that was typed and not yet saved.

   Dirtiness is tracked by listening for input/change on #dbody rather than by
   diffing a snapshot of the field values. #dbody survives every innerHTML
   replacement, so ONE delegated listener covers all eleven drawers and there
   is no ordering hazard with the snapDates() calls that run after three of
   them open. Typing a value then manually restoring it still counts as dirty;
   that costs one extra confirm and never loses an edit. */
let drawerDirty = false;
let drawerReturnFocus = null;

/* The scrim stops the MOUSE reaching the page. It does not stop the keyboard:
   without this, Tab out of a drawer lands in the search box and the filter
   buttons underneath, and Enter there repaints the main pane to a different
   company while the drawer is still editing the previous one -- saving then
   writes to a record the screen is no longer showing. `inert` removes the
   whole page from focus and hit-testing for as long as a drawer is open.
   #modePill is left alone: it is a status label with no handler. */
function pageInert(on){
  ['apphdr','appwrap'].forEach(id=>{
    const el = document.getElementById(id);
    if(el) el.inert = !!on;
  });
}

function drawerTitle(){
  const t = document.getElementById('dtitle');
  return (t && t.textContent || '').trim();
}

/* Named after the record, and explicit that the loss is permanent -- the other
   confirms in this file all name what they act on and all say the outcome is
   reversible. This one is the exception, so it has to say so. */
function confirmDiscard(){
  const what = drawerTitle();
  return confirm('Discard your unsaved changes to '
    + (what ? '"' + what + '"' : 'this record')
    + "?\n\nWhat you typed has not been saved and cannot be recovered.");
}

/* True when it is safe to replace or close the drawer's contents. */
function leaveDrawerOk(){
  return !drawerDirty || confirmDiscard();
}

/* Navigation from a button INSIDE the drawer to another drawer.
   The openers replace #dbody before calling openDrawer(), so by then the typed
   values are already gone and openDrawer's reset would hide the loss. The ask
   has to happen before the swap, which is why this wraps the opener rather
   than living inside openDrawer(). Today "+ Add shipment" on the project
   drawer is the only such button; any future one must use this too. */
function navFromDrawer(open){
  if(!leaveDrawerOk()) return;
  // Deliberately does NOT clear the flag. openDrawer() resets it, and the
  // openers only reach openDrawer() once they have actually swapped the form;
  // several bail first on a missing record (`if(!x) return;`). Clearing here
  // -- before OR after open(), since a bail is an ordinary return -- would
  // leave the untouched form on screen with its edits intact but marked
  // clean, to be discarded later without asking.
  open();
}

function openDrawer(){
  drawerDirty = false;
  const d = document.getElementById('drawer');
  if(!d.classList.contains('open')){
    drawerReturnFocus = document.activeElement || null;
  }
  d.inert = false;                       // must precede focus()
  d.classList.add('open');
  document.getElementById('scrim').classList.add('open');
  pageInert(true);
  if(d.focus) d.focus();
}
function closeDrawer(){
  drawerDirty = false;
  const d = document.getElementById('drawer');
  d.classList.remove('open');
  document.getElementById('scrim').classList.remove('open');
  pageInert(false);
  // A closed drawer is only translated off-screen (transform:translateX(100%)),
  // not hidden -- so its fields stayed in the tab order. Tabbing into that
  // off-screen form and typing set drawerDirty with nothing on screen, which
  // then made beforeunload block every reload with no visible cause.
  d.inert = true;
  // restore focus AFTER clearing inert -- focusing an inert element is a no-op
  if(drawerReturnFocus && drawerReturnFocus.focus) drawerReturnFocus.focus();
  drawerReturnFocus = null;
}
function requestCloseDrawer(){
  if(!leaveDrawerOk()) return;
  closeDrawer();
}

function draftReady(draft, headline){
  const el = document.getElementById('draftToast') || (()=>{
    const d = document.createElement('div');
    d.id = 'draftToast'; d.className = 'mvp live';
    d.style.cssText = 'bottom:52px;left:12px;max-width:420px;line-height:1.5;'
                    + 'pointer-events:none';
    document.body.appendChild(d); return d;
  })();
  const u = draft && draft.webLink ? safeUrl(draft.webLink) : '#';
  const link = (u && u !== '#') ? u : null;
  el.innerHTML = esc(headline) + ' — it\u2019s in your <b>Outlook Drafts</b>. '
    + 'Switch to Outlook to finish and send.'
    + (link ? ' <a href="' + esc(link) + '" target="_blank" rel="noopener" '
              + 'style="color:#9ecbff;pointer-events:auto">Open in browser instead</a>' : '');
  el.style.display = 'block';
  clearTimeout(window.__draftToastT);
  window.__draftToastT = setTimeout(()=>{ el.style.display = 'none'; }, 12000);
}

async function draft(email,name){
  // Phase 5 live: clicking a contact creates a REAL Outlook draft via the
  // MCP's draft_email and opens it (never sends). Falls back to a compose
  // link when Outlook writes aren't configured/signed-in, or in demo mode.
  if (CRM.mode !== 'embedded'){
    try{
      const r = await CRM.call('draft_email', {contact_email: email});
      if (r && r.ok && r.draft){
        draftReady(r.draft, 'Draft created for ' + (name || email));
        return;
      }
      console.warn('draft_email unavailable; compose-link fallback:', r && r.error);
    }catch(e){ console.warn('draft_email failed; compose-link fallback:', e); }
  }
  const first=(name||'').split(' ')[0]||'there';
  const subject=encodeURIComponent('Following up — Unrivaled Solutions');
  const body=encodeURIComponent(`Hi ${first},\n\n`);
  window.open(`mailto:${encodeURIComponent(email)}?subject=${subject}&body=${body}`,'_blank');
}

async function replyToThread(companyId, messageId){
  // Creates a REAL Outlook draft reply via draft_reply and opens it (never
  // sends) -- Graph fills in the correct recipient(s) and quotes the
  // original message, so this is a genuine reply, not a blank new email.
  // The Reply button only ever renders when a thread carries a message_id
  // (see enrichmentSection), and enrichmentSection itself is skipped
  // entirely in demo mode, so this never fires there in normal use --
  // the mode check below is just defensive.
  if (CRM.mode === 'embedded'){
    alert('Reply drafts need the live app, not demo mode.');
    return;
  }
  try{
    const r = await CRM.call('draft_reply', {company_id: companyId, message_id: messageId});
    if (r && r.ok && r.draft){
      draftReady(r.draft, 'Reply draft created');
      return;
    }
    alert('Could not create reply draft: ' + ((r && r.error) || 'unknown error'));
  }catch(e){
    alert('Could not create reply draft: ' + e.message);
  }
}

document.getElementById('q').addEventListener('input',e=>{
  query=e.target.value.trim(); renderList();
  // The Projects tab and the Live tab both own the main pane, so search has to
  // repaint it too -- renderList() alone only updates the sidebar.
  if(filter === 'project' || filter === 'live') renderMain();
});
// Single owner of tab state. select() also routes through it, so clicking a
// company from the Projects table actually lands on that company's page
// instead of leaving the main pane stuck on the project list.
function setFilter(f){
  filter = f;
  document.querySelectorAll('#filters button').forEach(x=>
    x.classList.toggle('on', x.dataset.f === f));
  const sf = document.getElementById('subfilters');
  const add = document.getElementById('addrow');
  const isProj = (f === 'project');
  const isRecv = (f === 'receivable');
  const isLive = (f === 'live');
  // both cross-company views own the sub-filter row and neither wants the
  // "+ Add customer/vendor/lead" buttons, which act on the company list
  if(sf) sf.style.display = (isProj || isRecv) ? 'flex' : 'none';
  if(add) add.style.display = (isProj || isRecv || isLive) ? 'none' : 'flex';
  if(isProj || isRecv) renderSubfilters();
  renderList();
  if(isProj || isRecv || isLive) renderMain();
  else if(selected) renderMain();
  else document.getElementById('main').innerHTML =
    '<div class="empty">Select a company to begin.</div>';
}
document.querySelectorAll('#filters button').forEach(b=>
  b.addEventListener('click', ()=>setFilter(b.dataset.f)));

/* Drawer close affordances. Bound once -- #dbody and #scrim are in the static
   template and are never themselves replaced, only #dbody's contents are. */
['input','change'].forEach(ev=>
  document.getElementById('dbody').addEventListener(ev, ()=>{
    drawerDirty = true;
  }));

/* Fallback for `inert`. It is Chrome/Edge 102+, so the operator's browser has
   it -- but an engine without it takes `el.inert = true` as a meaningless
   expando: no error, no effect, and the keyboard route back to the page
   silently returns. This costs four lines and makes the guarantee hold either
   way: focus that lands outside an open drawer is sent straight back. */
document.addEventListener('focusin', e=>{
  const d = document.getElementById('drawer');
  if(!d.classList.contains('open')) return;
  if(!d.contains || d.contains(e.target)) return;
  if(d.focus) d.focus();
});

/* `detail` is the click count of the sequence. The scrim becomes clickable the
   instant the drawer opens while the dim is still fading in over .18s, so the
   SECOND click of a double-click on a project/shipment/invoice row lands on
   the scrim and shuts the drawer the first click just opened -- it looks like
   the record refuses to open. Ignoring detail>1 fixes that without a timing
   window: a genuine double-click on the scrim still closes on its first click. */
document.getElementById('scrim').addEventListener('click', e=>{
  if(e && e.detail > 1) return;
  requestCloseDrawer();
});

document.addEventListener('keydown', e=>{
  if(e.key === 'Escape' && document.getElementById('drawer').classList.contains('open')){
    requestCloseDrawer();
  }
});

/* Same loss, different exit: Cmd-W or a reload discards typed edits with no
   prompt. Modern engines show their own generic wording and ignore this text,
   but it must be NON-EMPTY: per the unload algorithm the dialog appears when
   the event is canceled OR returnValue is not the empty string, so assigning
   '' is the value that means "do not prompt" on any engine still relying on
   the legacy path. */
window.addEventListener('beforeunload', e=>{
  if(!drawerDirty) return;
  e.preventDefault();
  e.returnValue = 'You have unsaved changes in the open record.';
  return e.returnValue;
});

// the drawer starts closed and off-screen; keep it out of the tab order until
// something opens it (openDrawer clears this)
document.getElementById('drawer').inert = true;

reindex(); kpis(); renderList();
// The landing screen is a cross-company view, so it has to paint itself: the
// template ships "Select a company to begin." in #main, and renderMain() is
// otherwise only reached by selecting a company or switching tabs.
if(filter === 'live') renderMain();
CRM.detect();
</script>
</body>
</html>
"""

def render_html(store_dir, token=""):
    """Build the self-contained HTML app for the given store, embedding
    `token` as the bridge auth secret (empty string if none -- the app will
    then fail bridge auth and fall back to demo/cowork detection, never
    silently talk to an unauthenticated bridge). Returns (html, counts)."""
    data = {}
    problems = []
    # tracker_buckets/tracker_unlinked are Live Tracker inputs. Their absence is
    # normal on any store seeded before the tracker shipped, so they are loaded
    # with the same per-file degradation and never treated as a broken store.
    for name in ["companies", "contacts", "projects", "shipments", "invoices",
                 "vendors", "tracker_buckets", "tracker_unlinked"]:
        path = os.path.join(store_dir, f"{name}.json")
        # Degrade per-file: a missing or corrupt store file (OneDrive
        # conflicted copy, half-written temp) must not kill the whole build.
        try:
            with open(path, encoding="utf-8-sig") as f:
                data[name] = json.load(f)
        except FileNotFoundError:
            data[name] = []
            if name not in ("invoices", "tracker_buckets", "tracker_unlinked"):
                problems.append(f"{name}.json missing -- built with 0 {name}")
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as ex:
            data[name] = []
            problems.append(f"{name}.json unreadable ({type(ex).__name__}) -- built with 0 {name}")
        # Valid JSON of the WRONG SHAPE is the case this missed. The archived
        # scrub below iterates four of these files and would raise on a dict,
        # which fails the build safely -- but the two tracker files are not in
        # that loop, so a `{}` sailed into the page and threw at the very first
        # statement of the bundle. The operator got an empty sidebar, "Select a
        # company to begin.", and a mode pill stuck on "Connecting..." forever:
        # no error, no clue, and every edit in the whole app impossible.
        if not isinstance(data.get(name), list):
            data[name] = []
            problems.append(f"{name}.json is not a list -- built with 0 {name}")
    # A validly-empty companies.json (brand-new store, everything archived)
    # is fine -- only refuse to build over an actually missing/corrupt file.
    if any(p.startswith("companies.json") for p in problems):
        raise SystemExit(
            "companies.json missing or unreadable -- refusing to build an empty "
            "view over a broken store. Fix the store file and rebuild.\n"
            + "\n".join(problems))
    for p in problems:
        print(f"WARNING: {p}", file=sys.stderr)
    # archived companies never ship into the demo bootstrap
    _all_companies = list(data["companies"])      # before the filter below
    arch = {c["company_id"] for c in data["companies"] if c.get("archived")}
    data["companies"] = [c for c in data["companies"] if not c.get("archived")]
    for k in ["contacts", "projects", "shipments", "invoices"]:
        data[k] = [x for x in data[k] if x.get("company_id") not in arch]
    data["vendors"] = [v for v in data["vendors"] if not v.get("archived")]
    # tracker_unlinked could not be caught by the loop above: its rows carry the
    # sheet's raw client NAME, not a company_id -- that is precisely why they
    # are unlinked. So an archived customer's tracker row kept rendering its
    # name and its full note on the Live screen, with an "Add to CRM" button,
    # after the operator had archived them. Archiving is this product's delete.
    #
    # Matched on a squashed name rather than a slug: build_view must not import
    # the pipeline, and the comparison only ever HIDES a card, so a near-miss
    # costs a visible row, never a wrong record.
    def _squash(v):
        return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())

    arch_names = {_squash(c.get("display_name")) for c in _all_companies
                  if c.get("archived")}
    arch_names.discard("")
    data["tracker_unlinked"] = [
        u for u in data["tracker_unlinked"]
        if not (isinstance(u, dict) and _squash(u.get("client")) in arch_names)]
    # Embed as a JSON literal in an inline <script>. json.dumps does NOT
    # escape "</script>" or U+2028/2029, so a store value containing those
    # would break out of the script element. Neutralize them.
    blob = (json.dumps(data)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    # Substitute the token FIRST (its only marker is in the template's own JS at
    # `const BRIDGE_TOKEN = '__BRIDGE_TOKEN__'`), THEN splice the data blob. If the
    # order were reversed, a stored value literally equal to "__BRIDGE_TOKEN__"
    # (e.g. a hostile email subject) would get rewritten to the live token. (v0.1.14)
    html = TEMPLATE.replace("__BRIDGE_TOKEN__", token).replace("__DATA__", blob)
    counts = {"companies": len(data["companies"]), "projects": len(data["projects"]),
              "shipments": len(data["shipments"])}
    return html, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="../store")
    ap.add_argument("--out", default="./unrivaled-crm.html")
    a = ap.parse_args()
    html, counts = render_html(a.store)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    kb = round(len(html) / 1024)
    print(f"Wrote {a.out} ({kb} KB) -- {counts['companies']} companies, "
          f"{counts['projects']} projects, {counts['shipments']} shipments")

if __name__ == "__main__":
    main()

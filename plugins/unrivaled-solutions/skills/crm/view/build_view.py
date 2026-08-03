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
import argparse, json, os, sys

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
    --bg:#f6f7f9; --panel:#ffffff; --ink:#1a2230; --muted:#697588; --line:#e4e8ee;
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
  .kpi .n{font-weight:700;font-size:16px}
  .kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .wrap{display:grid;grid-template-columns:320px 1fr;gap:0;height:calc(100vh - 59px)}
  .sidebar{border-right:1px solid var(--line);background:var(--panel);overflow-y:auto}
  .search{padding:12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
  .search input{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font-size:13px}
  .filters{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
  .filters button{min-width:56px}
  .subfilters{margin-top:8px;display:none;flex-direction:column;gap:6px}
  .sfrow{display:flex;gap:5px;align-items:center}
  .sfrow .sfl{color:var(--muted);font-size:11px;min-width:64px}
  .sfrow button{flex:1;padding:4px 6px;border:1px solid var(--line);background:#fff;
                border-radius:6px;font-size:11px;cursor:pointer;color:var(--muted)}
  .sfrow button.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:600}
  th.sortable{cursor:pointer;user-select:none}
  th.sortable:hover{color:var(--accent)}
  .filters button{flex:1;padding:6px;border:1px solid var(--line);background:#fff;border-radius:7px;
                  font-size:12px;cursor:pointer;color:var(--muted)}
  .filters button.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:600}
  .clist{padding:6px}
  .citem{padding:9px 11px;border-radius:8px;cursor:pointer}
  .citem:hover{background:var(--bg)}
  .citem.sel{background:var(--accent-soft)}
  .citem .cn{font-weight:600}
  .citem .cm{color:var(--muted);font-size:12px;display:flex;gap:8px;margin-top:2px}
  .main{overflow-y:auto;padding:22px 26px}
  .muted{color:var(--muted)}
  .empty{color:var(--muted);text-align:center;margin-top:16vh}
  .co-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .co-head h1{font-size:22px;margin:0}
  .badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;text-transform:capitalize}
  .b-customer{background:var(--accent-soft);color:var(--accent)}
  .b-vendor{background:#eef0f3;color:var(--slate)}
  .b-lead{background:var(--amber-soft);color:var(--amber)}
  .due-group{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);
             padding:10px 8px 4px;border-bottom:1px solid var(--line)}
  .due-group.od{color:var(--red)}
  .b-won{background:var(--green-soft);color:var(--green)}
  .b-pending{background:var(--amber-soft);color:var(--amber)}
  .b-lost{background:var(--red-soft);color:var(--red)}
  .b-stage{background:#eef0f3;color:var(--slate)}
  .section{margin-top:22px}
  .section h2{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);
              margin:0 0 8px;border-bottom:1px solid var(--line);padding-bottom:6px}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);
     padding:6px 8px;border-bottom:1px solid var(--line)}
  td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
  tr.click{cursor:pointer}
  tr.click:hover{background:var(--bg)}
  .contact a{color:var(--accent);text-decoration:none}
  .contact a:hover{text-decoration:underline}
  .num{font-variant-numeric:tabular-nums;text-align:right}
  .drawer{position:fixed;top:0;right:0;width:440px;max-width:92vw;height:100vh;background:var(--panel);
          border-left:1px solid var(--line);box-shadow:-8px 0 24px rgba(20,30,50,.08);
          transform:translateX(100%);transition:transform .18s ease;z-index:20;overflow-y:auto}
  .drawer.open{transform:none}
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
<header>
  <div class="brand">Unrivaled <span>CRM</span></div>
  <div class="kpis" id="kpis"></div>
</header>
<div class="wrap">
  <aside class="sidebar">
    <div class="search">
      <input id="q" placeholder="Search companies, contacts, projects, invoice #, vendor PO…" autocomplete="off"/>
      <div class="filters" id="filters">
        <button data-f="all" class="on">All</button>
        <button data-f="customer">Customers</button>
        <button data-f="vendor">Vendors</button>
        <button data-f="lead">Leads</button>
        <button data-f="project">Projects</button>
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
<div class="drawer" id="drawer"><div class="dh"><h3 id="dtitle"></h3><button class="x" onclick="closeDrawer()">&times;</button></div><div class="db" id="dbody"></div></div>
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
    const [co, ct, pr, sh, iv] = await Promise.all([
      CRM.call('list_companies', {}), CRM.call('find_contacts', {}),
      CRM.call('list_projects', {}),  CRM.call('list_shipments', {}),
      CRM.call('list_invoices', {})]);
    if (co.ok) DATA.companies = co.companies;
    if (ct.ok) DATA.contacts  = ct.contacts;
    if (pr.ok) DATA.projects  = pr.projects;
    if (sh.ok) DATA.shipments = sh.shipments;
    if (iv && iv.ok) DATA.invoices = iv.invoices;
    reindex(); kpis(); renderList();
    if (filter === 'project'){ renderSubfilters(); renderMain(); }
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

let filter='all', selected=null, query='';
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
  document.getElementById('kpis').innerHTML = [
    ['Companies', DATA.companies.length],
    ['Open shipments', openShip],
    [`Won revenue (${thisYear})`, money(won)],
    [`Pending pipeline (${thisYear})`, money(pend)],
    [`Open receivables (${thisYear})`, money(recv)],
  ].map(([l,n])=>`<div class="kpi"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
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
function renderProjectsList(){
  const rows = filteredProjects();
  document.getElementById('clist').innerHTML = rows.slice(0,400).map(p=>`
    <div class="citem" onclick="openProject('${jesc(st(p.project_no))}')">
      <div class="cn">${esc(st(p.project_no)||'—')} ${esc(st(p.description).slice(0,40))}</div>
      <div class="cm"><span>${esc(projCompanyName(p))}</span>${p.status?`<span>· ${esc(p.status)}</span>`:''}</div>
    </div>`).join('') || '<div class="muted" style="padding:14px">No matches.</div>';
}

function renderList(){
  if(filter === 'project'){ renderProjectsList(); return; }
  const items = DATA.companies.filter(companyMatches)
    .sort((a,b)=>st(a.display_name).localeCompare(st(b.display_name)));
  document.getElementById('clist').innerHTML = items.slice(0,400).map(c=>{
    const np=(projectsByCo[c.company_id]||[]).length, ns=(shipsByCo[c.company_id]||[]).length;
    return `<div class="citem ${c.company_id===selected?'sel':''}" onclick="select('${jesc(c.company_id)}')">
      <div class="cn">${esc(c.display_name||c.company_id)}</div>
      <div class="cm"><span>${esc(c.role)}</span>${np?`<span>· ${np} project${np>1?'s':''}</span>`:''}${ns?`<span>· ${ns} shipment${ns>1?'s':''}</span>`:''}</div>
    </div>`;
  }).join('') || '<div class="muted" style="padding:14px">No matches.</div>';
}

function select(id){
  selected=id;
  if(filter === 'project'){ setFilter('all'); fetchEnrichment(id); return; }
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
  if(filter === 'project'){
    document.getElementById('main').innerHTML = renderProjectsMain();
    return;
  }
  const c=companyById[selected]; if(!c){return;}
  const cts=contactsByCo[selected]||[], prs=projectsByCo[selected]||[], sps=shipsByCo[selected]||[];
  const draftAll = cts.filter(x=>x.email)[0];
  let h=`<div class="co-head"><h1>${esc(c.display_name||c.company_id)}</h1>
    <span class="badge b-${esc(c.role)}">${esc(c.role)}</span>
    ${c.primary_location?`<span class="muted">${esc(c.primary_location)}</span>`:''}
    <span style="margin-left:auto;display:flex;gap:8px">
      <button class="pill-btn" onclick="openEditCompany('${jesc(c.company_id)}')">Edit company</button>
      <button class="pill-btn" onclick="openNewProject('${jesc(c.company_id)}')">+ New project</button>
      <button class="pill-btn" onclick="openNewInvoice('${jesc(c.company_id)}')">+ New invoice</button>
      <button class="pill-btn" onclick="openNewContact('${jesc(c.company_id)}')">+ Add contact</button>
      ${c.role==='vendor'?`<button class="pill-btn" onclick="openEditVendor('${jesc(c.company_id)}')">Edit vendor</button>`:''}
      ${c.role==='lead'?`<button class="pill-btn" style="background:var(--green-soft);color:var(--green)" onclick="convertLead('${jesc(c.company_id)}')">Convert to customer</button>`:''}
      ${draftAll?`<button class="pill-btn" onclick="draft('${jesc(draftAll.email)}','${jesc(draftAll.name||'')}')">✉ Draft email</button>`:''}
      <button class="pill-btn" style="background:var(--red-soft);color:var(--red)" onclick="deleteCompany('${jesc(c.company_id)}')">Delete</button>
    </span>
  </div>`;

  h+=enrichmentSection(selected);

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
      <td class="muted">${esc(x.phone||'')}</td><td class="muted">${esc(st(x.last_action).slice(0,10))}</td>
      <td><button class="pill-btn" style="padding:2px 8px;font-size:11px" onclick="openEditContact('${jesc(selected)}','${jesc(x.email||'')}','${jesc(x.name||'')}')">Edit</button></td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No contacts.</div>';
  h+=`</div>`;

  h+=`<div class="section"><h2>Projects (${prs.length})</h2>`;
  h+= prs.length?`<table><thead><tr><th>Project #</th><th>Description</th><th>Status</th><th>Owner</th>
      <th class="num">Revenue</th><th class="num">Margin</th><th>Collection</th></tr></thead><tbody>`+
    prs.map(p=>`<tr class="click" onclick="openProject('${jesc(p.project_no||'')}')">
      <td><b>${esc(p.project_no||'—')}</b></td><td>${esc(p.description||'')}</td>
      <td>${statusBadge(p.status)}</td><td>${esc(arr(p.owner).join(', '))||'—'}</td>
      <td class="num">${money(p.revenue)}</td><td class="num">${pct(p.margin)}</td>
      <td class="muted">${esc(p.collection_status||'')}</td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No projects.</div>';
  h+=`</div>`;

  const invs=invoicesByCo[selected]||[];
  if(invs.length){
    const todayStr = new Date().toISOString().slice(0,10);
    const soonStr = (()=>{const d=new Date(); d.setDate(d.getDate()+7); return d.toISOString().slice(0,10);})();
    const bucketOf = (v)=>{
      const ps=st(v.payment_status);
      if(ps.startsWith('paid')) return 'Paid';
      const d=dueOn(v);
      if(!d) return 'No due date';
      if(d<todayStr) return 'Overdue';
      if(d<=soonStr) return 'Due this week';
      return 'Due later';
    };
    const BUCKET_ORDER=['Overdue','Due this week','Due later','No due date','Paid'];
    const grouped={}; invs.forEach(v=>{(grouped[bucketOf(v)]=grouped[bucketOf(v)]||[]).push(v);});
    Object.values(grouped).forEach(list=>list.sort((a,b)=>(st(dueOn(a))||'9999').localeCompare(st(dueOn(b))||'9999')));
    let invRows='';
    BUCKET_ORDER.forEach(bk=>{
      const list=grouped[bk]; if(!list||!list.length) return;
      invRows+=`<tr><td colspan="7" class="due-group${bk==='Overdue'?' od':''}">${esc(bk)} (${list.length})</td></tr>`;
      invRows+=list.map(v=>{const ps=st(v.payment_status);const cls=ps==='paid'?'b-won':(ps.startsWith('partial')?'b-pending':'b-lost');
        const due=dueOn(v); const overdue = bk==='Overdue';
        return `<tr><td><b>${esc(v.invoice_no||'—')}</b></td><td class="muted">${esc(v.client_po_raw||'')}</td>
        <td class="muted">${esc(st(v.invoice_date).slice(0,10))}</td>
        <td><span class="badge ${cls}">${esc(ps||'—')}</span></td>
        <td class="${overdue?'':'muted'}" ${overdue?'style="color:var(--red);font-weight:600"':''}>${esc(due||'—')}</td>
        <td class="muted" style="max-width:280px">${esc(st(v.payment_notes).slice(0,90))}</td>
        <td><button class="pill-btn" style="padding:2px 8px;font-size:11px" onclick="openEditInvoice('${jesc(selected)}','${jesc(v.invoice_no||'')}')">Edit</button></td></tr>`;}).join('');
    });
    h+=`<div class="section"><h2>Invoices / customer orders (${invs.length})</h2>
      <table><thead><tr><th>Invoice #</th><th>Client PO / order</th><th>Invoiced</th><th>Status</th><th>Due on</th><th>Notes</th><th></th></tr></thead><tbody>`+
      invRows+
      `</tbody></table></div>`;
  }

  h+=`<div class="section"><h2>Shipments (${sps.length})</h2>`;
  h+= sps.length?`<table><thead><tr><th>Project #</th><th>Vendor PO</th><th>Stage</th><th>Ship date</th></tr></thead><tbody>`+
    sps.map(s=>`<tr class="click" onclick="openShipment('${jesc(s.shipment_id||'')}')">
      <td>${esc(s.project_no||'—')}</td><td>${esc(s.vendor_po_raw||'')}</td>
      <td><span class="badge b-stage">${esc(s.stage||'—')}</span></td>
      <td class="muted">${esc(st(s.ship_date).slice(0,10))}</td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No shipments.</div>';
  h+=`</div>`;
  document.getElementById('main').innerHTML=h;
}

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
    <div class="row2">
      <div class="field"><label>Revenue ($)</label><input id="f_revenue" type="number" step="0.01" value="${p.revenue==null?'':esc(p.revenue)}"/></div>
      <div class="field"><label>Total cost ($)</label><input id="f_cost" type="number" step="0.01" value="${p.total_cost==null?'':esc(p.total_cost)}"/></div>
    </div>
    <div class="row2">
      <div class="field"><label>Gross profit ($)</label><input id="f_gp" type="number" step="0.01" value="${p.gross_profit==null?'':esc(p.gross_profit)}"/></div>
      <div class="field"><label>Margin (%)</label><input id="f_margin" type="number" step="0.1" value="${esc(marginPct)}"/></div>
    </div>
    <div class="field"><label>Owner (reps, comma-separated)</label><input id="f_owner" value="${esc(arr(p.owner).join(', '))}"/></div>
    <div class="field"><label>Notes</label><textarea id="f_notes">${esc(p.notes||'')}</textarea></div>
    <div class="field"><label>Annotations (one per line)</label><textarea id="f_annos">${esc(arr(p.annotations).join('\n'))}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveProject('${jesc(pno)}')">Save changes</button>
    <button class="btn ghost" onclick="openNewShipment('${jesc(pno)}')" style="margin-left:8px">+ Add shipment</button>
    <button class="pill-btn" style="background:var(--red-soft);color:var(--red);margin-left:8px" onclick="deleteProject('${jesc(pno)}')">Delete project</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px" id="drawerNote"></p>`;
  document.getElementById('drawerNote').textContent = CRM.mode==='embedded'
    ? 'Demo mode: this save lasts only for this browser session.'
    : 'Saves persist to your CRM records through the validated write interface.';
  document.getElementById('drawer').classList.add('open');
}

function numOrNull(id){
  const v=document.getElementById(id).value;
  return v===''?null:parseFloat(v);
}

async function saveProject(pno){
  const newPno = document.getElementById('f_pno').value.trim();
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
    owner: document.getElementById('f_owner').value.split(',').map(s=>s.trim()).filter(Boolean),
    annotations: document.getElementById('f_annos').value.split('\n').map(s=>s.trim()).filter(Boolean),
    revenue: numOrNull('f_revenue'),
    total_cost: numOrNull('f_cost'),
    gross_profit: numOrNull('f_gp'),
    margin: marginRaw==null ? null : marginRaw/100,
  };
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
    pno = newPno;
    renamed = true;
  }
  await doSave('update_project', {project_no: pno, fields}, (r)=>{
    const p=DATA.projects.find(x=>String(x.project_no)===String(pno));
    Object.assign(p, r.project || fields);
  });
  // A rename changes the project_no baked into this drawer's own button
  // handlers (Delete, + Add shipment) -- reopen so they point at the new
  // number. Only done on rename: reopening on every ordinary save would
  // wipe the "Saved" flash (it replaces the #savedMsg node doSave just set).
  if(renamed) openProject(pno);
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
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
  document.getElementById('drawer').classList.add('open');
  snapDates(['e_iv_date','e_iv_paydate','e_iv_due']);
}

async function saveEditInvoice(cid, invoiceNo){
  const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
  let invoiceNoNow = invoiceNo;
  const newNo = document.getElementById('e_iv_no').value.trim();
  if(newNo && newNo !== invoiceNo){
    btn.disabled=true; msg.className='saved';
    const rr = await CRM.call('rename_invoice', {company_id:cid, old_invoice_no:invoiceNo, new_invoice_no:newNo});
    if(!rr || !rr.ok){
      msg.textContent='✗ '+((rr&&rr.error)||'rename failed'); msg.className='saved show errc';
      btn.disabled=false;
      return;
    }
    const p=(invoicesByCo[cid]||[]).find(x=>String(x.invoice_no)===String(invoiceNo));
    if(p) p.invoice_no=newNo;
    DATA.shipments.forEach(s=>{ if(s.company_id===cid && String(s.invoice_no)===String(invoiceNo)) s.invoice_no=newNo; });
    reindex();
    invoiceNoNow = newNo;
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
  document.getElementById('drawer').classList.add('open');
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
async function doSave(tool, args, applyLocal){
  const btn=document.getElementById('saveBtn'), msg=document.getElementById('savedMsg');
  btn.disabled=true; msg.className='saved';
  try{
    const r = await CRM.call(tool, args);
    if (r && r.ok){
      applyLocal(r);
      msg.textContent='✓ Saved'; msg.className='saved show okc';
      kpis(); renderMain();
    } else {
      msg.textContent='✗ ' + ((r && r.error) || 'save failed'); msg.className='saved show errc';
    }
  }catch(e){
    msg.textContent='✗ ' + e.message; msg.className='saved show errc';
  }finally{
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
function closeDrawer(){document.getElementById('drawer').classList.remove('open');}

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
  // The Projects tab owns the main pane, so search has to repaint it too --
  // renderList() alone only updates the sidebar.
  if(filter === 'project') renderMain();
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
  if(sf) sf.style.display = isProj ? 'flex' : 'none';
  if(add) add.style.display = isProj ? 'none' : 'flex';
  if(isProj) renderSubfilters();
  renderList();
  if(isProj) renderMain();
  else if(selected) renderMain();
  else document.getElementById('main').innerHTML =
    '<div class="empty">Select a company to begin.</div>';
}
document.querySelectorAll('#filters button').forEach(b=>
  b.addEventListener('click', ()=>setFilter(b.dataset.f)));
reindex(); kpis(); renderList();
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
    for name in ["companies", "contacts", "projects", "shipments", "invoices", "vendors"]:
        path = os.path.join(store_dir, f"{name}.json")
        # Degrade per-file: a missing or corrupt store file (OneDrive
        # conflicted copy, half-written temp) must not kill the whole build.
        try:
            with open(path, encoding="utf-8-sig") as f:
                data[name] = json.load(f)
        except FileNotFoundError:
            data[name] = []
            if name != "invoices":  # invoices.json is server-created; absence is normal
                problems.append(f"{name}.json missing -- built with 0 {name}")
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as ex:
            data[name] = []
            problems.append(f"{name}.json unreadable ({type(ex).__name__}) -- built with 0 {name}")
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
    arch = {c["company_id"] for c in data["companies"] if c.get("archived")}
    data["companies"] = [c for c in data["companies"] if not c.get("archived")]
    for k in ["contacts", "projects", "shipments", "invoices"]:
        data[k] = [x for x in data[k] if x.get("company_id") not in arch]
    data["vendors"] = [v for v in data["vendors"] if not v.get("archived")]
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

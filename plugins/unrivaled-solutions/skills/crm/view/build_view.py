#!/usr/bin/env python3
"""Build the interactive CRM view — a single self-contained HTML file.

    python3 build_view.py --store ../store --out ./unrivaled-crm.html

Wired to the Unrivaled CRM MCP (interface v0.1). The app picks a backend at
startup, in order:

  1. cowork   — window.cowork.callMcpTool -> the plugin's CRM MCP (production)
  2. http     — the local dev bridge (mcp/dev_bridge.py) on 127.0.0.1:8765
  3. embedded — the data baked into this file; edits are session-only (demo)

In modes 1–2 every save persists through the MCP's validated write path and
the header pill shows "Live". Embedded data is always rendered instantly as
bootstrap, then replaced by a live refresh when a backend is present.
"""
import argparse, json, os

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
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
  .filters{display:flex;gap:6px;margin-top:8px}
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
      <input id="q" placeholder="Search companies, contacts, projects…" autocomplete="off"/>
      <div class="filters" id="filters">
        <button data-f="all" class="on">All</button>
        <button data-f="customer">Customers</button>
        <button data-f="vendor">Vendors</button>
      </div>
      <div class="addrow" id="addrow" style="display:none;gap:6px;margin-top:8px">
        <button class="pill-btn" style="flex:1" onclick="openNewCompany('customer')">+ Add customer</button>
        <button class="pill-btn" style="flex:1" onclick="openNewCompany('vendor')">+ Add vendor</button>
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
const TOOL_PREFIX = 'mcp__unrivaled-crm__';     // adjust if the connector id differs
const BRIDGE = 'http://127.0.0.1:8765';

const CRM = {
  mode: 'embedded',
  async detect(){
    if (window.cowork && window.cowork.callMcpTool){ this.mode = 'cowork'; }
    else {
      try{
        const c = new AbortController(); setTimeout(()=>c.abort(), 1200);
        const r = await fetch(BRIDGE + '/health', {signal: c.signal});
        if ((await r.json()).ok) this.mode = 'http';
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
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({tool, args: args || {}})});
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
    reindex(); kpis(); renderList(); if (selected) renderMain();
  }catch(e){ console.warn('live refresh failed; keeping embedded data', e); }
}

function setModePill(){
  const el = document.getElementById('modePill');
  el.textContent = {
    cowork:   'Live · edits persist (CRM MCP v0.1)',
    http:     'Live · edits persist (dev bridge)',
    embedded: 'Demo · edits last this browser session only',
  }[CRM.mode];
  el.classList.toggle('live', CRM.mode !== 'embedded');
  const add = document.getElementById('addrow');
  if (add) add.style.display = 'flex';   // add/delete available in every mode (session-only in demo)
}

/* ---------------------------------------------------------- indexes/util -- */
let contactsByCo={}, projectsByCo={}, shipsByCo={}, invoicesByCo={}, companyById={}, vendorById={};
function reindex(){
  const byCo = (arr)=>{const m={};(arr||[]).forEach(x=>{(m[x.company_id]=m[x.company_id]||[]).push(x)});return m;};
  contactsByCo = byCo(DATA.contacts);
  projectsByCo = byCo(DATA.projects);
  shipsByCo    = byCo(DATA.shipments);
  invoicesByCo = byCo(DATA.invoices);
  companyById  = Object.fromEntries(DATA.companies.map(c=>[c.company_id,c]));
  vendorById   = Object.fromEntries((DATA.vendors||[]).map(v=>[v.company_id,v]));
}
const money = (n)=> (n==null||isNaN(n))?'—':'$'+Number(n).toLocaleString(undefined,{maximumFractionDigits:0});
const pct = (n)=> (n==null||isNaN(n))?'—':(Number(n)*100).toFixed(0)+'%';
const esc = (s)=> (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

let filter='all', selected=null, query='';

function kpis(){
  const openShip = DATA.shipments.filter(s=>['Ordered','Shipped','On Hold'].includes(s.stage)).length;
  const won = DATA.projects.filter(p=>p.status==='won').reduce((a,p)=>a+(p.revenue||0),0);
  const pend = DATA.projects.filter(p=>p.status==='pending').reduce((a,p)=>a+(p.revenue||0),0);
  const recv = DATA.projects.filter(p=>{const c=p.collection_status;return c && c!=='paid';})
                            .reduce((a,p)=>a+(p.revenue||0),0);
  document.getElementById('kpis').innerHTML = [
    ['Companies', DATA.companies.length],
    ['Open shipments', openShip],
    ['Won revenue', money(won)],
    ['Pending pipeline', money(pend)],
    ['Open receivables', money(recv)],
  ].map(([l,n])=>`<div class="kpi"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}

function companyMatches(c){
  if(filter!=='all' && c.role!==filter) return false;
  if(!query) return true;
  const q=query.toLowerCase();
  if((c.display_name||'').toLowerCase().includes(q)) return true;
  if((contactsByCo[c.company_id]||[]).some(x=>(x.name||'').toLowerCase().includes(q)||(x.email||'').toLowerCase().includes(q))) return true;
  if((projectsByCo[c.company_id]||[]).some(p=>(p.project_no||'').includes(q)||(p.description||'').toLowerCase().includes(q))) return true;
  return false;
}

function renderList(){
  const items = DATA.companies.filter(companyMatches)
    .sort((a,b)=>(a.display_name||'').localeCompare(b.display_name||''));
  document.getElementById('clist').innerHTML = items.slice(0,400).map(c=>{
    const np=(projectsByCo[c.company_id]||[]).length, ns=(shipsByCo[c.company_id]||[]).length;
    return `<div class="citem ${c.company_id===selected?'sel':''}" onclick="select('${c.company_id}')">
      <div class="cn">${esc(c.display_name||c.company_id)}</div>
      <div class="cm"><span>${c.role}</span>${np?`<span>· ${np} project${np>1?'s':''}</span>`:''}${ns?`<span>· ${ns} shipment${ns>1?'s':''}</span>`:''}</div>
    </div>`;
  }).join('') || '<div class="muted" style="padding:14px">No matches.</div>';
}

function select(id){ selected=id; renderList(); renderMain(); fetchEnrichment(id); }

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
  const th = e.threads || [];
  if (th.length){
    h += `<table><thead><tr><th>Recent thread</th><th>With</th><th>Date</th></tr></thead><tbody>` +
      th.slice(0,5).map(t=>`<tr><td>${t.webLink?`<a href="${esc(t.webLink)}" target="_blank" rel="noopener">${esc(t.subject||'(no subject)')}</a>`:esc(t.subject||'(no subject)')}</td>
        <td class="muted">${esc(t.with||'')}</td><td class="muted">${esc(String(t.date||'').slice(0,10))}</td></tr>`).join('') + `</tbody></table>`;
  } else {
    h += `<div class="muted">No recent email threads.</div>`;
  }
  const mt = e.meetings || [];
  if (mt.length){
    h += `<div style="margin-top:8px"><b style="font-size:12px">Meetings:</b> ` +
      mt.slice(0,3).map(m=>`${esc(m.subject||'meeting')} (${esc(String(m.date||'').slice(0,10))})`).join(' · ') + `</div>`;
  }
  if (e.refreshed_at) h += `<div class="muted" style="font-size:11px;margin-top:6px">Refreshed ${esc(String(e.refreshed_at).slice(0,16).replace('T',' '))} UTC</div>`;
  return h + `</div>`;
}

function statusBadge(s){ s=(s||'').toLowerCase(); const cls={won:'b-won',pending:'b-pending',lost:'b-lost'}[s]||'b-stage';
  return s?`<span class="badge ${cls}">${s}</span>`:''; }

function renderMain(){
  const c=companyById[selected]; if(!c){return;}
  const cts=contactsByCo[selected]||[], prs=projectsByCo[selected]||[], sps=shipsByCo[selected]||[];
  const draftAll = cts.filter(x=>x.email)[0];
  let h=`<div class="co-head"><h1>${esc(c.display_name||c.company_id)}</h1>
    <span class="badge b-${c.role}">${c.role}</span>
    ${c.primary_location?`<span class="muted">${esc(c.primary_location)}</span>`:''}
    <span style="margin-left:auto;display:flex;gap:8px">
      <button class="pill-btn" onclick="openNewProject('${esc(c.company_id)}')">+ New project</button>
      <button class="pill-btn" onclick="openNewContact('${esc(c.company_id)}')">+ Add contact</button>
      ${c.role==='vendor'?`<button class="pill-btn" onclick="openEditVendor('${esc(c.company_id)}')">Edit vendor</button>`:''}
      ${draftAll?`<button class="pill-btn" onclick="draft('${esc(draftAll.email)}','${esc(draftAll.name||'')}')">✉ Draft email</button>`:''}
      <button class="pill-btn" style="background:var(--red-soft);color:var(--red)" onclick="deleteCompany('${esc(c.company_id)}')">Delete</button>
    </span>
  </div>`;

  h+=enrichmentSection(selected);

  if(c.role==='vendor'){
    const v=vendorById[selected]||{};
    h+=`<div class="section"><h2>Vendor details</h2>
      <div class="kv"><span class="k">Rep</span><span>${esc(v.rep||'—')}</span></div>
      <div class="kv"><span class="k">Email</span><span>${v.email?`<a href="#" onclick="draft('${esc(v.email)}','${esc(v.rep||'')}');return false">${esc(v.email)}</a>`:'—'}</span></div>
      <div class="kv"><span class="k">Phone</span><span>${esc(v.phone||'—')}</span></div>
      <div class="kv"><span class="k">Offerings</span><span>${esc(v.offerings||'—')}</span></div>
      <div class="kv"><span class="k">Send POs to</span><span>${esc(v.po_routing||'—')}</span></div>
      <div class="kv"><span class="k">Send invoices to</span><span>${esc(v.invoice_routing||'—')}</span></div>
    </div>`;
  }

  h+=`<div class="section"><h2>Contacts (${cts.length})</h2>`;
  h+= cts.length?`<table><thead><tr><th>Name</th><th>Title</th><th>Email</th><th>Phone</th><th>Last action</th></tr></thead><tbody>`+
    cts.map(x=>`<tr><td>${esc(x.name||'—')}</td><td class="muted">${esc(x.title||'')}</td>
      <td class="contact">${x.email?`<a href="#" onclick="draft('${esc(x.email)}','${esc(x.name||'')}');return false">${esc(x.email)}</a>`:'—'}</td>
      <td class="muted">${esc(x.phone||'')}</td><td class="muted">${esc((x.last_action||'').slice(0,10))}</td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No contacts.</div>';
  h+=`</div>`;

  h+=`<div class="section"><h2>Projects (${prs.length})</h2>`;
  h+= prs.length?`<table><thead><tr><th>Project #</th><th>Description</th><th>Status</th><th>Owner</th>
      <th class="num">Revenue</th><th class="num">Margin</th><th>Collection</th></tr></thead><tbody>`+
    prs.map(p=>`<tr class="click" onclick="openProject('${esc(p.project_no||'')}')">
      <td><b>${esc(p.project_no||'—')}</b></td><td>${esc(p.description||'')}</td>
      <td>${statusBadge(p.status)}</td><td>${(p.owner||[]).join(', ')||'—'}</td>
      <td class="num">${money(p.revenue)}</td><td class="num">${pct(p.margin)}</td>
      <td class="muted">${esc(p.collection_status||'')}</td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No projects.</div>';
  h+=`</div>`;

  const invs=invoicesByCo[selected]||[];
  if(invs.length){
    h+=`<div class="section"><h2>Invoices / customer orders (${invs.length})</h2>
      <table><thead><tr><th>Invoice #</th><th>Client PO / order</th><th>Invoiced</th><th>Status</th><th>Paid on</th><th>Notes</th></tr></thead><tbody>`+
      invs.map(v=>{const st=(v.payment_status||'');const cls=st==='paid'?'b-won':(st.startsWith('partial')?'b-pending':'b-lost');
        return `<tr><td><b>${esc(v.invoice_no||'—')}</b></td><td class="muted">${esc(v.client_po_raw||'')}</td>
        <td class="muted">${esc((v.invoice_date||'').slice(0,10))}</td>
        <td><span class="badge ${cls}">${esc(st||'—')}</span></td>
        <td class="muted">${esc((v.pay_date||'').slice(0,10))}</td>
        <td class="muted" style="max-width:340px">${esc((v.payment_notes||'').slice(0,90))}</td></tr>`;}).join('')+
      `</tbody></table></div>`;
  }

  h+=`<div class="section"><h2>Shipments (${sps.length})</h2>`;
  h+= sps.length?`<table><thead><tr><th>Project #</th><th>Vendor PO</th><th>Stage</th><th>Ship date</th></tr></thead><tbody>`+
    sps.map(s=>`<tr class="click" onclick="openShipment('${esc(s.shipment_id||'')}')">
      <td>${esc(s.project_no||'—')}</td><td>${esc(s.vendor_po_raw||'')}</td>
      <td><span class="badge b-stage">${esc(s.stage||'—')}</span></td>
      <td class="muted">${esc((s.ship_date||'').slice(0,10))}</td></tr>`).join('')+
    `</tbody></table>`:'<div class="muted">No shipments.</div>';
  h+=`</div>`;
  document.getElementById('main').innerHTML=h;
}

/* ------------------------------------------------------- project drawer -- */
function openProject(pno){
  const p=DATA.projects.find(x=>String(x.project_no)===String(pno)); if(!p) return;
  document.getElementById('dtitle').textContent='Project '+(pno||'');
  document.getElementById('dbody').innerHTML=`
    <div class="kv"><span class="k">Company</span><span>${esc((companyById[p.company_id]||{}).display_name||p.company_name||'—')}</span></div>
    <div class="kv"><span class="k">Description</span><span>${esc(p.description||'—')}</span></div>
    <div class="kv"><span class="k">Revenue / Cost</span><span>${money(p.revenue)} / ${money(p.total_cost)}</span></div>
    <div class="kv"><span class="k">Invoice #</span><span>${esc(p.invoice_no||'—')}</span></div>
    <hr style="border:none;border-top:1px solid var(--line);margin:14px 0"/>
    <div class="row2">
      <div class="field"><label>Status</label><select id="f_status">
        ${['won','pending','lost'].map(s=>`<option ${p.status===s?'selected':''}>${s}</option>`).join('')}</select></div>
      <div class="field"><label>Collection</label><select id="f_coll">
        ${['','open','partial:50%','paid'].map(s=>`<option value="${s}" ${(p.collection_status||'')===s?'selected':''}>${s||'—'}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label>Owner (reps, comma-separated)</label><input id="f_owner" value="${esc((p.owner||[]).join(', '))}"/></div>
    <div class="field"><label>Notes</label><textarea id="f_notes">${esc(p.notes||'')}</textarea></div>
    <button class="btn" id="saveBtn" onclick="saveProject('${esc(pno)}')">Save changes</button>
    <button class="btn ghost" onclick="openNewShipment('${esc(pno)}')" style="margin-left:8px">+ Add shipment</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px" id="drawerNote"></p>`;
  document.getElementById('drawerNote').textContent = CRM.mode==='embedded'
    ? 'Demo mode: this save lasts only for this browser session.'
    : 'Saves persist to your CRM records through the validated write interface.';
  document.getElementById('drawer').classList.add('open');
}

async function saveProject(pno){
  const fields = {
    status: document.getElementById('f_status').value,
    collection_status: document.getElementById('f_coll').value || null,
    notes: document.getElementById('f_notes').value,
    owner: document.getElementById('f_owner').value.split(',').map(s=>s.trim()).filter(Boolean),
  };
  await doSave('update_project', {project_no: pno, fields}, (r)=>{
    const p=DATA.projects.find(x=>String(x.project_no)===String(pno));
    Object.assign(p, r.project || fields);
  });
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
    <button class="btn" id="saveBtn" onclick="saveNewProject('${esc(cid)}')">Create project</button>
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
    <button class="btn" id="saveBtn" onclick="saveNewContact('${esc(cid)}')">Add contact</button>
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

function openNewShipment(pno){
  document.getElementById('dtitle').textContent='Add shipment — project '+pno;
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>Vendor PO</label><input id="n_po" placeholder="e.g. PO# 1142 Hallowell"/></div>
    <div class="row2">
      <div class="field"><label>Stage</label><select id="n_stage">
        ${STAGES.map(x=>`<option ${x==='Ordered'?'selected':''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>Ship date</label><input id="n_sdate" type="date"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveNewShipment('${esc(pno)}')">Add shipment</button>
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
  document.getElementById('dtitle').textContent = isV ? 'Add vendor' : 'Add customer';
  document.getElementById('dbody').innerHTML=`
    <div class="field"><label>${isV?'Vendor':'Customer'} name (required)</label><input id="c_name"/></div>
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
    :`<div class="field"><label>Primary location</label><input id="c_loc" placeholder="e.g. Louisville, KY"/></div>`}
    <button class="btn" id="saveBtn" onclick="saveNewCompany('${esc(role)}')">Add ${isV?'vendor':'customer'}</button>
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
    const loc=val('c_loc');
    const fields={display_name:name, role:'customer', locations:loc?[loc]:[], primary_location:loc};
    await doSave('create_company', {fields}, (r)=>{
      const c=r.company||fields; DATA.companies.push(c);
      reindex(); renderList(); closeDrawer(); if(c.company_id) select(c.company_id);
    });
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
    <div class="field"><label>Offerings</label><input id="e_offer" value="${esc(v.offerings||'')}"/></div>
    <div class="row2">
      <div class="field"><label>Send POs to</label><input id="e_po" value="${esc(v.po_routing||'')}"/></div>
      <div class="field"><label>Send invoices to</label><input id="e_inv" value="${esc(v.invoice_routing||'')}"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveEditVendor('${esc(cid)}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>`;
  document.getElementById('drawer').classList.add('open');
}

async function saveEditVendor(cid){
  const val=(id)=>{const el=document.getElementById(id);return el&&el.value.trim()?el.value.trim():null;};
  const fields={rep:val('e_rep'),hq_location:val('e_hq'),email:val('e_email'),
    phone:val('e_phone'),offerings:val('e_offer'),po_routing:val('e_po'),invoice_routing:val('e_inv')};
  await doSave('update_vendor', {company_id:cid, fields}, (r)=>{
    const v=r.vendor||Object.assign(vendorById[cid]||{company_id:cid},fields);
    const i=(DATA.vendors||[]).findIndex(x=>x.company_id===cid);
    if(i>=0) DATA.vendors[i]=v; else (DATA.vendors=DATA.vendors||[]).push(v);
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
    <div class="kv"><span class="k">Project #</span><span>${esc(s.project_no||'—')}${s.linked_to_project?'':' <span class="muted">(unlinked — vendor-PO keyed)</span>'}</span></div>
    <div class="kv"><span class="k">Vendor PO</span><span>${esc(s.vendor_po_raw||'—')}</span></div>
    ${s.open_orders_notes?`<div class="kv"><span class="k">Order notes</span><span>${esc(s.open_orders_notes)}</span></div>`:''}
    <hr style="border:none;border-top:1px solid var(--line);margin:14px 0"/>
    <div class="row2">
      <div class="field"><label>Stage</label><select id="s_stage">
        ${STAGES.map(x=>`<option ${s.stage===x?'selected':''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>Ship date</label><input id="s_date" type="date" value="${esc((s.ship_date||'').slice(0,10))}"/></div>
    </div>
    <button class="btn" id="saveBtn" onclick="saveShipment('${esc(sid)}')">Save changes</button>
    <span class="saved" id="savedMsg"></span>
    <p class="muted" style="margin-top:16px;font-size:12px">${CRM.mode==='embedded'
      ? 'Demo mode: this save lasts only for this browser session.'
      : 'Stage changes persist to your CRM records (Ordered → Shipped → Delivered → Installed).'}</p>`;
  document.getElementById('drawer').classList.add('open');
}

async function saveShipment(sid){
  const fields = {
    stage: document.getElementById('s_stage').value,
    ship_date: document.getElementById('s_date').value || null,
  };
  await doSave('update_shipment', {shipment_id: sid, fields}, (r)=>{
    const s=DATA.shipments.find(x=>x.shipment_id===sid);
    Object.assign(s, r.shipment || fields);
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

function closeDrawer(){document.getElementById('drawer').classList.remove('open');}

async function draft(email,name){
  // Phase 5 live: clicking a contact creates a REAL Outlook draft via the
  // MCP's draft_email and opens it (never sends). Falls back to a compose
  // link when Outlook writes aren't configured/signed-in, or in demo mode.
  if (CRM.mode !== 'embedded'){
    try{
      const r = await CRM.call('draft_email', {contact_email: email});
      if (r && r.ok && r.draft && r.draft.webLink){
        window.open(r.draft.webLink, '_blank');
        return;
      }
      console.warn('draft_email unavailable; compose-link fallback:', r && r.error);
    }catch(e){ console.warn('draft_email failed; compose-link fallback:', e); }
  }
  const first=(name||'').split(' ')[0]||'there';
  const subject=encodeURIComponent('Following up — Unrivaled Solutions');
  const body=encodeURIComponent(`Hi ${first},\n\n`);
  window.open(`mailto:${email}?subject=${subject}&body=${body}`,'_blank');
}

document.getElementById('q').addEventListener('input',e=>{query=e.target.value.trim();renderList();});
document.querySelectorAll('#filters button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#filters button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); filter=b.dataset.f; renderList();
}));
reindex(); kpis(); renderList();
CRM.detect();
</script>
</body>
</html>
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="../store")
    ap.add_argument("--out", default="./unrivaled-crm.html")
    a = ap.parse_args()
    data = {}
    for name in ["companies", "contacts", "projects", "shipments", "invoices", "vendors"]:
        with open(os.path.join(a.store, f"{name}.json")) as f:
            data[name] = json.load(f)
    # archived companies never ship into the demo bootstrap
    arch = {c["company_id"] for c in data["companies"] if c.get("archived")}
    data["companies"] = [c for c in data["companies"] if not c.get("archived")]
    for k in ["contacts", "projects", "shipments", "invoices"]:
        data[k] = [x for x in data[k] if x.get("company_id") not in arch]
    data["vendors"] = [v for v in data["vendors"] if not v.get("archived")]
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    with open(a.out, "w") as f:
        f.write(html)
    kb = round(len(html) / 1024)
    print(f"Wrote {a.out} ({kb} KB) — {len(data['companies'])} companies, "
          f"{len(data['projects'])} projects, {len(data['shipments'])} shipments")

if __name__ == "__main__":
    main()

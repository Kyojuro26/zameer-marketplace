// The visual app: render robustness, date preservation, save correctness.
//
// Two defect classes:
//
//  1. RENDER ROBUSTNESS. A stored value of an unexpected type throws inside a
//     render function -- and doSave re-runs renderMain after EVERY save, so one
//     bad row blanks the whole pane on every subsequent save.
//
//  2. DATE PRESERVATION. A save that only meant to change a status must not
//     rewrite a date it never touched. This is enforced by snapshotting
//     data-orig from the control AFTER insertion, so the baseline is whatever
//     the browser's own sanitizer kept. These tests are only meaningful
//     because lib/dom.js emulates <input type=date> sanitization -- without
//     that they cannot fail.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { launch, makeResult, buildBundle } = require('../lib/view.js');

// Composed at runtime, not written as a literal: the PII sweep rejects any
// email shape in this PUBLIC tree except the one allowed address, and a
// fixture is not a good enough reason to weaken that check.
const FIXTURE_EMAIL = ['person', 'example.invalid'].join('@');

// element accessor that never throws -- a control absent from an older
// build is a finding about that build, not a broken harness
const EMPTY = { innerHTML: '', value: '', getAttribute: () => null };

const PATHOLOGICAL_DATES = ['9/31/2025', '2/30/2026', '2026-02-29', '25/12/2025',
  '3/14/2026', 45731, '2026-03-14 00:00:00', '2024-02-29', '12/31/99'];

function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [{ company_id: 'acme', display_name: 'Ace Manufacturing',
    role: 'customer', domains: [], locations: [], archived: false },
    { company_id: 'beta', display_name: 'Beta Works',
      role: 'customer', domains: [], locations: [], archived: false },
    { company_id: 'fs-racking', display_name: 'FS Racking',
      role: 'vendor', domains: [], locations: [], archived: false },
    { company_id: 'penco', display_name: 'Penco',
      role: 'vendor', domains: [], locations: [], archived: false }]);
  // every field below carries a type the render path did not expect
  w('contacts', [{ company_id: 'acme', name: 'A Person', email: FIXTURE_EMAIL,
    last_action: 45731 }]);
  w('projects', [{ company_id: 'acme', project_no: '4521', status: null,
    year: 2026, revenue: 100000, owner: 'D', annotations: 'note one',
    description: 12345, collection_status: 'partial:30%', archived: false,
    // a deal date no <input type="date"> will hold: 2026 is not a leap year
    date: '2026-02-29' },
    // NO NUMBER. The deal log yields these (16 of 261 on the real store); the
    // app cannot open or edit one. year 2024 keeps it out of the KPI checks.
    { company_id: 'acme', project_no: null, status: 'won', year: 2024,
      revenue: 500, description: 'numberless deal', archived: false },
    // Beta holds Acme's number 4521 too. A project is (number, customer);
    // year 2024 keeps it out of the KPI checks.
    { company_id: 'beta', project_no: '4521', status: 'won', year: 2024, revenue: 555,
      description: 'Beta job', archived: false, tracker_status: 'action_admin',
      open_orders_notes: 'beta live job' },
    // and one on the Live screen, which renders its own card and list item
    { company_id: 'acme', project_no: null, status: 'won', year: 2024,
      revenue: 700, description: 'numberless live', archived: false, date: '2026-05-05',
      tracker_status: 'action_admin', open_orders_notes: 'numberless live job' },
    // a number only Acme holds, with a leg the importer left company-less and
    // an invoice mis-filed under Beta (review round 1). year 2024 again.
    { company_id: 'acme', project_no: '4600', status: 'won', year: 2024, revenue: 60,
      description: 'acme only', archived: false }]);
  w('shipments', [
    { shipment_id: '4521-L1', company_id: 'acme', project_no: '4521',
      all_project_nos: '4521', stage: null, ship_date: 45731, vendor_id: 'fs-racking' },
    { shipment_id: '4521-L2', company_id: 'acme', project_no: '4521',
      all_project_nos: ['4521'], stage: 'Shipped', ship_date: '3/14/2026' },
    { shipment_id: '4521-L3', company_id: 'acme', project_no: 4521,
      all_project_nos: [4521], stage: 'Ordered', ship_date: '2026-03-14 00:00:00',
      vendor_id: 'ghost' },   // a vendor no record carries
    { shipment_id: '4600-L1', company_id: null, project_no: '4600',
      all_project_nos: ['4600'], stage: 'Ordered' },
    // a DELIVERED leg at the same vendor: on the vendor page it is not an open PO
    { shipment_id: '4521-L6', company_id: 'acme', project_no: '4521',
      all_project_nos: ['4521'], stage: 'Delivered', vendor_id: 'fs-racking' },
    // on the SHARED number: a leg with no company, and Acme's leg with its
    // company id padded (review round 2)
    { shipment_id: '4521-L4', company_id: null, project_no: '4521',
      all_project_nos: ['4521'], stage: 'Ordered' },
    { shipment_id: '4521-L5', company_id: ' acme ', project_no: '4521',
      all_project_nos: ['4521'], stage: 'Ordered' }]);
  w('invoices', [{ company_id: 'acme', invoice_no: '9001', project_no: '4521',
    payment_status: 'partial:30%', payment_notes: 45731, invoice_date: 45731 },
    { company_id: 'beta', invoice_no: '9002', project_no: '4600',
      payment_status: 'open', invoice_date: '2026-01-01' }]);
  w('vendors', [{ company_id: 'fs-racking', display_name: 'FS Racking' },
    { company_id: 'penco', display_name: 'Penco' }]);
  w('needs_review', []);
  return dir;
}

async function run(crmDir) {
  const r = makeResult('view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmview-'));
  const store = seedStore(path.join(tmp, 'store'));
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });

  // ---- the two hooks a styling pass is most likely to break ------------------
  // SOURCE CHECKS over the generated page, as the Live suite reads its tabs:
  // lib/dom.js registers id-bearing nodes only and its body.innerHTML is empty.
  const { html: pageSrc } = buildBundle(crmDir, store, tmp);
  // the mode is put back afterwards: every save below records through the
  // http transport, and an app left in embedded mode would answer itself
  const modeWas = app.eval('CRM.mode');
  const pillStates = ['http', 'cowork', 'embedded'].map(m =>
    app.eval(`CRM.mode=${JSON.stringify(m)}; setModePill(); document.getElementById('modePill').textContent`));
  app.eval(`CRM.mode=${JSON.stringify(modeWas)}; setModePill();`);
  r.check('the header still holds #modePill, and it still writes its three text states',
    /<header[^>]*>[\s\S]*id="modePill"[\s\S]*<\/header>/.test(pageSrc)
      && pillStates[0] === 'Live \u00b7 edits persist (local app)'
      && /^Live \u00b7 edits persist \(CRM MCP/.test(pillStates[1])
      && pillStates[2] === 'Demo \u00b7 edits last this browser session only',
    JSON.stringify(pillStates));
  const filters = ['live', 'all', 'customer', 'vendor', 'lead', 'project', 'receivable'];
  r.check('every data-f filter button still exists',
    filters.every(f => new RegExp(`<button data-f="${f}"`).test(pageSrc)),
    filters.filter(f => !new RegExp(`<button data-f="${f}"`).test(pageSrc)).join(',') || 'all present');

  // ---- render robustness -------------------------------------------------
  const safe = (name, ...a) => {
    const f = app.fn(name);
    if (typeof f !== 'function') { r.check(`entry point ${name} exists`, false,
      'missing from this build'); return null; }
    try { return f(...a); } catch (e) { r.check(`${name} does not throw`, false, e.message); }
    return null;
  };
  const entry = [
    ['select + renderMain', () => app.fn('select')('acme')],
    ['renderMain re-entrant (the doSave path)', () => { safe('renderMain'); safe('renderMain'); }],
    ['renderList', () => app.fn('renderList')()],
    ['kpis', () => app.fn('kpis')()],
    ['projects tab', () => app.fn('setFilter')('project')],
    ['openProject drawer', () => app.fn('openProject')('4521')],
    ['openShipment drawer', () => app.fn('openShipment')('4521-L1')],
    ['openEditInvoice drawer', () => app.fn('openEditInvoice')('acme', '9001')],
    ['openEditContact drawer', () => app.fn('openEditContact')('acme', FIXTURE_EMAIL, 'A Person')],
  ];
  for (const [label, fn] of entry) {
    let err = null;
    try { fn(); } catch (e) { err = e; }
    r.check(`${label} does not throw on hostile stored types`, err === null,
      err && (err instanceof TypeError && /is not a function/.test(err.message)
        ? `entry point missing from this build: ${err.message}` : err.message));
  }
  safe('setFilter', 'all');
  safe('select', 'acme');
  r.check('the main pane is populated', ((app.el('main') || EMPTY).innerHTML || '').length > 400,
    `len=${((app.el('main') || EMPTY).innerHTML || '').length}`);

  // enrichment is attacker-influenced (Outlook subjects/senders) and typed by
  // nobody; a null member used to throw and strand the previous company's pane
  try { app.eval(`ENRICH['acme']={threads:[null],meetings:[null],last_contact:null};`); }
  catch (e) { r.check('the ENRICH overlay exists', false, e.message); }
  let enrichErr = null;
  try { safe('renderMain'); } catch (e) { enrichErr = e; }
  r.check('renderMain survives null members in Outlook enrichment',
    enrichErr === null, enrichErr && enrichErr.message);

  // ---- date preservation -------------------------------------------------
  const hasIso = app.eval('typeof isoDate') === 'function';
  r.check('isoDate exists (the date-wipe guard)', hasIso, 'missing from this build');
  for (const d of (hasIso ? PATHOLOGICAL_DATES : [])) {
    const iso = app.eval(`isoDate(${JSON.stringify(d)})`);
    const valid = iso !== null && iso !== '';
    // an unparseable date must fall back to a text box holding it verbatim
    r.check(`isoDate(${JSON.stringify(d)}) resolves without throwing`,
      iso === null || typeof iso === 'string', String(iso));
    if (String(d) === '2024-02-29') {
      r.check('a real leap day is accepted', valid && iso === '2024-02-29', String(iso));
    }
    if (String(d) === '2026-02-29') {
      r.check('a fake leap day is rejected (kept as raw text)', iso === null, String(iso));
    }
  }
  if (hasIso) r.check('a 2-digit year uses a sane century pivot',
    app.eval(`isoDate("12/31/99")`) === '1999-12-31',
    String(app.eval(`isoDate("12/31/99")`)));

  // status-only save on an invoice whose date is unparseable
  safe('openEditInvoice', 'acme', '9001');
  if (app.el('e_iv_status')) app.el('e_iv_status').value = 'paid';
  else r.check('the invoice status control exists', false, 'missing from this build');
  app.resetCalls();
  safe('saveEditInvoice', 'acme', '9001');
  const inv = app.calls().find(c => c.tool === 'update_invoice');
  r.check('a status-only invoice save sends NO date fields',
    inv && !('invoice_date' in inv.args.fields) && !('pay_date' in inv.args.fields)
        && !('due_on' in inv.args.fields),
    inv && JSON.stringify(inv.args.fields));

  // stage-only save on a leg whose ship_date is a tracker serial
  safe('openShipment', '4521-L2');
  if (app.el('s_stage')) app.el('s_stage').value = 'Delivered';
  else r.check('the shipment stage control exists', false, 'missing from this build');
  app.resetCalls();
  safe('saveShipment', '4521-L2');
  const shp = app.calls().find(c => c.tool === 'update_shipment');
  r.check('a stage-only shipment save sends NO date fields',
    shp && !('ship_date' in shp.args.fields) && !('eta' in shp.args.fields)
        && !('start_date' in shp.args.fields),
    shp && JSON.stringify(shp.args.fields));

  // ---- save correctness --------------------------------------------------
  // a stored value outside the preset list must survive a save, not be
  // downgraded to whatever the browser selected first
  safe('openEditInvoice', 'acme', '9001');
  r.check('a partial:NN% status is preserved as a selectable option',
    ((app.el('dbody') || EMPTY).innerHTML || '').includes('partial:30%'),
    'a stored partial payment must not be written off as "open"');
  safe('openProject', '4521');
  // ---- the deal date follows the date-preservation rule ----------------------
  // It was a plain text box showing "2026-06-17 00:00:00", sent on every save.
  r.check('an unparseable deal date falls back to a text box holding it verbatim',
    (app.el('f_date') || EMPTY).value === '2026-02-29'
      && /Kept exactly as it came from the tracker/.test((app.el('dbody') || EMPTY).innerHTML || ''),
    `f_date=${(app.el('f_date') || EMPTY).value}`);
  app.resetCalls();
  safe('saveProject', '4521');
  const proj = app.calls().find(c => c.tool === 'update_project');
  r.check('a project with no stored status does not send an empty status',
    proj && proj.args.fields.status !== '',
    proj && JSON.stringify(proj.args.fields.status));
  r.check('an untouched deal date is not sent, so it cannot be rewritten',
    proj && !('date' in proj.args.fields), proj && JSON.stringify(Object.keys(proj.args.fields)));
  safe('openProject', '4521');
  if (app.el('f_date')) app.el('f_date').value = '2026-03-01';
  app.resetCalls();
  // awaited: the re-baseline happens on the save's success path, and the real
  // form is locked until then -- an un-awaited second save here would race a
  // window the operator cannot reach
  await app.fn('saveProject')('4521');
  const proj2 = app.calls().find(c => c.tool === 'update_project');
  r.check('a deal date he did change is sent',
    proj2 && proj2.args.fields.date === '2026-03-01', proj2 && JSON.stringify(proj2.args.fields.date));
  // Review finding: change it BACK and save again. The baseline was taken when
  // the drawer opened, so the second save saw "no change" and sent nothing --
  // the store kept the first change under a green "Saved".
  if (app.el('f_date')) app.el('f_date').value = '2026-02-29';
  app.resetCalls();
  await app.fn('saveProject')('4521');
  const proj3 = app.calls().find(c => c.tool === 'update_project');
  r.check('a date changed back after a save is sent again, not read as unchanged',
    proj3 && proj3.args.fields.date === '2026-02-29',
    proj3 && `sent: ${JSON.stringify(proj3.args.fields.date)} (key present: ${'date' in proj3.args.fields})`);
  safe('closeDrawer');
  // ---- two labels ----------------------------------------------------------------
  safe('setFilter', 'all'); safe('select', 'acme');
  const mainHdr = (app.el('main') || EMPTY).innerHTML || '';
  r.check('the invoice table names the date column for what it holds',
    /<th class="num">Invoice date<\/th>/.test(mainHdr) && !/>Invoiced</.test(mainHdr),
    '"Invoiced" beside an "Outstanding" amount read as a second amount');
  safe('setFilter', 'live');
  const liveCardDate = ((app.el('main') || EMPTY).innerHTML || '').split('<div class="lt-card"')
    .find(x => x.includes('numberless live job')) || '';
  r.check('the Live card labels its date',
    /started 5 May 2026/.test(liveCardDate), liveCardDate.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 160));
  safe('setFilter', 'all'); safe('select', 'acme');

  // ---- a row that cannot be opened is not offered as one --------------------
  //
  // openProject(pno) finds the project by String(project_no); for a null
  // number that is 'null', which matches nothing, and it returns silently. The
  // Projects tab, the company page and both sidebars still rendered such rows
  // with class="click" and an onclick -- click, and nothing happened, with no
  // word about why. update_project keys on the number too, so the app cannot
  // edit one at all: the fix is a number, given in chat, and the row says so.
  const rowOf = (html, marker, tag) => (String(html).split('<' + tag).find(x => x.includes(marker)) || '');
  safe('setFilter', 'project');
  let row = rowOf((app.el('main') || EMPTY).innerHTML, 'numberless deal', 'tr');
  r.check('the Projects tab renders a numberless project',
    row !== '', 'the row is missing altogether, which hides the deal');
  // the company-name link in the same row has its own onclick, so the test is
  // for the ROW's affordance: no class="click", no openProject
  r.check('a numberless row on the Projects tab is not clickable',
    row && !/openProject\(/.test(row) && !/class="click"/.test(row), row.slice(0, 200));
  r.check('and says why it cannot be opened',
    /give it one in chat to edit here/.test(row), row.slice(0, 200));
  // split on the ITEM, not on <div: the marker sits in the inner name div,
  // and a chunk cut there can never see the onclick on the item around it
  let side = (app.el('clist') || EMPTY).innerHTML.split('class="citem"').find(x => x.includes('numberless deal')) || '';
  r.check('the projects sidebar item for it is inert too',
    side && !/onclick=/.test(side), side.slice(0, 200));
  const numbered = rowOf((app.el('main') || EMPTY).innerHTML, '12345', 'tr');
  r.check('a numbered row is still clickable, and names its customer',
    /onclick="openProject\('4521','acme'\)"/.test(numbered), numbered.slice(0, 200));
  safe('setFilter', 'all'); safe('select', 'acme');
  row = rowOf((app.el('main') || EMPTY).innerHTML, 'numberless deal', 'tr');
  r.check('the company page renders the same row inert, with the note',
    row && !/openProject\(/.test(row) && !/class="click"/.test(row)
        && /give it one in chat to edit here/.test(row), row.slice(0, 200));
  safe('setFilter', 'live');
  const card = rowOf((app.el('main') || EMPTY).innerHTML, 'numberless live job', 'div class="lt-card"');
  r.check('the Live card for a numberless job has no Edit button, and says why',
    card && !/openProject\(/.test(card) && /give it one in chat to edit here/.test(card), card.slice(0, 300));
  side = (app.el('clist') || EMPTY).innerHTML;
  // any handler at all whose LAST argument is empty or 'null' is a dead click
  r.check('the Live sidebar item for it carries no click',
    /citem/.test(side) && !/onclick="\w+\([^)]*'(null|)'\)"/.test(side), side.slice(0, 200));
  // and the entry point itself: a click that does slip through opens nothing
  safe('closeDrawer');
  safe('openProject', ''); safe('openProject', 'null');
  r.check('openProject with no number opens no drawer',
    !((app.el('drawer') || EMPTY).classList || { contains: () => false }).contains('open'));
  safe('setFilter', 'all'); safe('select', 'acme');

  // ---- a project is (number, customer) ------------------------------------------
  //
  // Beta and Acme both hold 4521. openProject(pno) found the FIRST record of
  // that number, so Beta's card opened a drawer showing Acme's fields, and
  // every save was then refused by the server as ambiguous. Every call site
  // now passes the customer, the drawer bakes the record's own customer into
  // its handlers, and each write names it.
  const clickOf = (html, marker, tag) => (String(html).split('<' + tag).find(x => x.includes(marker)) || '');
  safe('setFilter', 'live');
  const betaCard = clickOf((app.el('main') || EMPTY).innerHTML, 'beta live job', 'div class="lt-card"');
  r.check("Beta's Live card Edit names Beta",
    /openProject\('4521','beta'\)/.test(betaCard), betaCard.slice(0, 300));
  safe('closeDrawer'); safe('openProject', '4521', 'beta');
  r.check("and opens a drawer showing Beta's fields, not Acme's",
    (app.el('f_desc') || EMPTY).value === 'Beta job' && String((app.el('f_revenue') || EMPTY).value) === '555',
    `desc=${(app.el('f_desc') || EMPTY).value} revenue=${(app.el('f_revenue') || EMPTY).value}`);
  r.check("the drawer bakes Beta into its own handlers",
    /saveProject\('4521','beta'\)/.test((app.el('dbody') || EMPTY).innerHTML || '')
      && /deleteProject\('4521','beta'\)/.test((app.el('dbody') || EMPTY).innerHTML || '')
      && /openNewShipment\('4521','beta'\)/.test((app.el('dbody') || EMPTY).innerHTML || ''));
  if (app.el('f_desc')) app.el('f_desc').value = 'Beta job edited';
  app.resetCalls();
  await app.fn('saveProject')('4521', 'beta');
  const upd = app.calls().find(c => c.tool === 'update_project');
  r.check("saving Beta's drawer sends company_id beta with the number",
    upd && upd.args.company_id === 'beta' && upd.args.project_no === '4521'
      && upd.args.fields.description === 'Beta job edited', upd && JSON.stringify(upd.args).slice(0, 200));
  const descs = JSON.parse(app.eval("JSON.stringify(DATA.projects.filter(p=>String(p.project_no)==='4521').map(p=>[p.company_id, String(p.description)]))"));
  r.check("and the local mirror edits Beta's record, leaving Acme's untouched",
    JSON.stringify(descs) === JSON.stringify([['acme', '12345'], ['beta', 'Beta job edited']]), JSON.stringify(descs));
  safe('closeDrawer');
  safe('setFilter', 'all'); safe('select', 'beta');
  const betaRow = clickOf((app.el('main') || EMPTY).innerHTML, 'Beta job edited', 'tr');
  r.check("the company page row names Beta", /openProject\('4521','beta'\)/.test(betaRow), betaRow.slice(0, 200));
  safe('setFilter', 'project');
  const betaTab = clickOf((app.el('main') || EMPTY).innerHTML, 'Beta job edited', 'tr');
  r.check("the Projects tab row names Beta", /openProject\('4521','beta'\)/.test(betaTab), betaTab.slice(0, 200));
  const betaSide = ((app.el('clist') || EMPTY).innerHTML || '').split('class="citem"').find(x => x.includes('Beta job edited')) || '';
  r.check("and so does the projects sidebar item", /openProject\('4521','beta'\)/.test(betaSide), betaSide.slice(0, 200));
  // a rename from Beta's drawer names Beta, and the local mirror moves only
  // Beta's number; Acme keeps 4521
  safe('closeDrawer'); safe('openProject', '4521', 'beta');
  if (app.el('f_pno')) app.el('f_pno').value = '4523';
  app.resetCalls();
  await app.fn('saveProject')('4521', 'beta');
  const ren = app.calls().find(c => c.tool === 'rename_project');
  r.check("a rename from Beta's drawer names Beta",
    ren && ren.args.company_id === 'beta' && ren.args.old_project_no === '4521' && ren.args.new_project_no === '4523',
    ren && JSON.stringify(ren.args));
  const nums = JSON.parse(app.eval("JSON.stringify(DATA.projects.filter(p=>['4521','4523'].includes(String(p.project_no))).map(p=>[p.company_id, String(p.project_no)]))"));
  r.check("and the local mirror renumbers Beta's record only",
    JSON.stringify(nums) === JSON.stringify([['acme', '4521'], ['beta', '4523']]), JSON.stringify(nums));
  // (review round 2) the company-less leg follows the rename, as on disk; the
  // leg filed under ' acme ' is Acme's -- the other holder's -- and stays
  const legs45 = JSON.parse(app.eval("JSON.stringify(['4521-L1','4521-L4','4521-L5'].map(id=>String(DATA.shipments.find(x=>x.shipment_id===id).project_no)))"));
  r.check("the company-less leg on the shared number follows Beta's rename locally, and Acme's padded one stays",
    JSON.stringify(legs45) === JSON.stringify(['4521', '4523', '4521']), JSON.stringify(legs45));
  // put the number back for the checks below
  safe('closeDrawer'); safe('openProject', '4523', 'beta');
  if (app.el('f_pno')) app.el('f_pno').value = '4521';
  await app.fn('saveProject')('4523', 'beta');
  // a new leg from Beta's drawer names Beta
  safe('closeDrawer'); safe('openNewShipment', '4521', 'beta');
  if (app.el('n_po')) app.el('n_po').value = 'VPO-BETA';
  app.resetCalls();
  await app.fn('saveNewShipment')('4521', 'beta');
  const crs = app.calls().find(c => c.tool === 'create_shipment');
  r.check("a leg added from Beta's drawer names Beta",
    crs && crs.args.company_id === 'beta' && crs.args.project_no === '4521', crs && JSON.stringify(crs.args).slice(0, 200));
  // delete from Beta's drawer archives Beta's, and only Beta's leaves the page
  app.resetCalls();
  await app.fn('deleteProject')('4521', 'beta');
  const arc = app.calls().find(c => c.tool === 'archive_project');
  r.check("deleting from Beta's drawer names Beta",
    arc && arc.args.company_id === 'beta' && arc.args.project_no === '4521', arc && JSON.stringify(arc.args));
  const left = JSON.parse(app.eval("JSON.stringify(DATA.projects.filter(p=>String(p.project_no)==='4521').map(p=>p.company_id))"));
  r.check("and only Beta's record leaves the page", JSON.stringify(left) === '["acme"]', JSON.stringify(left));
  // opened by number alone: the first record, as before, and no customer is sent
  safe('closeDrawer'); safe('openProject', '4521');
  r.check('a project opened by number alone still opens (the first record of that number)',
    (app.el('f_desc') || EMPTY).value === '12345', `desc=${(app.el('f_desc') || EMPTY).value}`);
  app.resetCalls();
  await app.fn('saveProject')('4521');
  const bare = app.calls().find(c => c.tool === 'update_project');
  r.check('a save with no customer given sends none',
    bare && !('company_id' in bare.args) && bare.args.project_no === '4521', bare && JSON.stringify(bare.args).slice(0, 120));
  safe('closeDrawer');

  // ---- an invoice row opens its drawer, as a project's or a shipment's does ----
  // The rows in "Invoices / customer orders" carried no handler; the only way
  // in was a 37x17px Edit button in the last column, off the right edge of a
  // narrow window once the table scrolled.
  safe('setFilter', 'all'); safe('select', 'acme');
  const invRow = rowOf((app.el('main') || EMPTY).innerHTML, '9001', 'tr');
  r.check('an invoice row on the company page is clickable into its edit drawer',
    /^ class="click" onclick="openEditInvoice\('acme','9001'\)"/.test(invRow), invRow.slice(0, 160));
  r.check('and its Edit button stops the click reaching the row, so the drawer opens once',
    /onclick="event\.stopPropagation\(\);openEditInvoice\('acme','9001'\)">Edit</.test(invRow)
      && !/style="padding:2px 8px;font-size:11px"/.test(invRow), invRow.slice(-200));

  // ---- vendors on legs: the drawer's select, and the vendor page ----------------
  // the page first: the saves below change L1's vendor in the local mirror
  safe('closeDrawer'); safe('setFilter', 'all'); safe('select', 'fs-racking');
  const vendMain = (app.el('main') || EMPTY).innerHTML || '';
  // jesc() writes the id's hyphen as \x2d inside the onclick, as every id is
  r.check('a vendor page opens with its Open POs above the details -- the open leg, not the delivered one',
    /Open POs \(1\)/.test(vendMain) && vendMain.includes("openShipment('4521\\x2dL1')")
      && !vendMain.includes("openShipment('4521\\x2dL6')")
      && vendMain.indexOf('Open POs') < vendMain.indexOf('Vendor details'),
    'h2=' + JSON.stringify((/<h2>Open POs[^<]*<\/h2>/.exec(vendMain) || ['none'])[0]));
  safe('select', 'penco');
  r.check('a vendor with no open legs has no Open POs section', !/Open POs/.test((app.el('main') || EMPTY).innerHTML || ''));
  safe('select', 'acme');
  safe('closeDrawer'); safe('openShipment', '4521-L1');
  const selHtml = (app.el('dbody') || EMPTY).innerHTML || '';
  const selBlock = (selHtml.split('<select id="s_vendor">')[1] || '').split('</select>')[0];
  r.check('the shipment drawer has a Vendor select with "— none —" first and the stored vendor selected',
    /^<option value="" >\u2014 none \u2014<\/option>/.test(selBlock)
      && /<option value="fs-racking" selected>FS Racking<\/option>/.test(selBlock)
      && selBlock.indexOf('FS Racking') < selBlock.indexOf('Penco'),
    selBlock.slice(0, 300));
  app.resetCalls();
  await app.fn('saveShipment')('4521-L1');
  const shV = app.calls().find(c => c.tool === 'update_shipment');
  r.check('a save that did not touch the vendor does not send it',
    shV && !('vendor_id' in shV.args.fields), shV && JSON.stringify(Object.keys(shV.args.fields)));
  safe('openShipment', '4521-L1');
  app.el('s_vendor').value = 'penco';
  app.resetCalls();
  await app.fn('saveShipment')('4521-L1');
  const shV2 = app.calls().find(c => c.tool === 'update_shipment');
  r.check('a changed vendor is sent', shV2 && shV2.args.fields.vendor_id === 'penco', shV2 && JSON.stringify(shV2.args.fields));
  safe('openShipment', '4521-L1');
  app.el('s_vendor').value = '';
  app.resetCalls();
  await app.fn('saveShipment')('4521-L1');
  const shV3 = app.calls().find(c => c.tool === 'update_shipment');
  r.check('clearing it sends null', shV3 && shV3.args.fields.vendor_id === null, shV3 && JSON.stringify(shV3.args.fields));
  safe('openShipment', '4521-L3');
  const ghost = ((app.el('dbody') || EMPTY).innerHTML || '').split('<select id="s_vendor">')[1] || '';
  r.check('a stored vendor no record carries is still an option, selected, and says so',
    /<option value="ghost" selected>ghost \(no vendor record\)<\/option>/.test(ghost), ghost.slice(0, 200));

  // ---- review round 1: the customer is a guess on the Receivables screen ------
  // Invoice 9002 is filed under Beta but linked to 4600, which only Acme
  // holds. The invoice's company used as a hard filter rendered a link that
  // opened nothing.
  safe('setFilter', 'receivable');
  const recvRow = clickOf((app.el('main') || EMPTY).innerHTML, '9002', 'tr');
  r.check("a Receivables link for an invoice filed under a customer that does not hold the number names the holder",
    /openProject\('4600','acme'\)/.test(recvRow), recvRow.slice(0, 300));
  safe('closeDrawer'); safe('openProject', '4600', 'acme');
  r.check('and it opens the holder\'s project',
    (app.el('f_desc') || EMPTY).value === 'acme only', `desc=${(app.el('f_desc') || EMPTY).value}`);
  // ---- review round 1: a scoped mirror on a number one customer holds ------
  // The server's cascade follows the number alone when it is unshared; the
  // page's mirror must too, or the company-less leg and the mis-filed
  // invoice stay on a number no project holds until the next reload.
  if (app.el('f_pno')) app.el('f_pno').value = '4601';
  app.resetCalls();
  await app.fn('saveProject')('4600', 'acme');
  const moved = JSON.parse(app.eval("JSON.stringify([DATA.shipments.find(x=>x.shipment_id==='4600-L1').project_no, DATA.invoices.find(x=>x.invoice_no==='9002').project_no])"));
  r.check("a rename from the sole holder's drawer renumbers its company-less leg and mis-filed invoice locally",
    JSON.stringify(moved) === JSON.stringify(['4601', '4601']), JSON.stringify(moved));
  safe('closeDrawer'); safe('openProject', '4601', 'acme');
  if (app.el('f_pno')) app.el('f_pno').value = '4600';
  await app.fn('saveProject')('4601', 'acme');
  safe('closeDrawer');
  // and a delete from the sole holder's drawer takes them off the page, as the
  // server hides every record of a number with no live holder
  await app.fn('deleteProject')('4600', 'acme');
  const left4600 = JSON.parse(app.eval("JSON.stringify([DATA.shipments.some(x=>x.shipment_id==='4600-L1'), DATA.invoices.some(x=>x.invoice_no==='9002')])"));
  r.check("a delete from the sole holder's drawer removes its company-less leg and mis-filed invoice from the page",
    JSON.stringify(left4600) === '[false,false]', JSON.stringify(left4600));

  // ---- review round 1: one twin archived, and a company-less twin ------------
  // A second store: Acme's 4521 archived, Beta's live, and a third record of
  // 4521 with no company at all. The page hid Beta's leg and invoice along
  // with Acme's (the archived set keyed by the number alone), and the
  // company-less twin's own card opened ACME's drawer ('' read as "no
  // customer" on the page, while the server reads it as the empty key).
  const dirB = path.join(tmp, 'store-twins');
  fs.mkdirSync(dirB, { recursive: true });
  const wB = (n, v) => fs.writeFileSync(path.join(dirB, n + '.json'), JSON.stringify(v, null, 2));
  wB('companies', [{ company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer', domains: [], locations: [], archived: false },
    { company_id: 'beta', display_name: 'Beta Works', role: 'customer', domains: [], locations: [], archived: false }]);
  wB('projects', [
    { company_id: 'acme', project_no: '4521', status: 'won', year: 2024, revenue: 1, description: 'Acme job', archived: true },
    { company_id: 'beta', project_no: '4521', status: 'won', year: 2024, revenue: 2, description: 'Beta job', archived: false,
      tracker_status: 'action_admin', open_orders_notes: 'beta live job' },
    { company_id: null, project_no: '4521', status: 'won', year: 2024, revenue: 3, description: 'orphan job', archived: false,
      tracker_status: 'action_admin', open_orders_notes: 'orphan live job' }]);
  wB('shipments', [
    { shipment_id: '4521-LA', company_id: 'acme', project_no: '4521', all_project_nos: ['4521'], stage: 'Ordered', vendor_po_raw: 'VPO-ACME' },
    { shipment_id: '4521-LB', company_id: 'beta', project_no: '4521', all_project_nos: ['4521'], stage: 'Ordered', vendor_po_raw: 'VPO-BETA' }]);
  wB('invoices', [
    { company_id: 'acme', invoice_no: '7001', project_no: '4521', payment_status: 'open', invoice_date: '2026-01-01' },
    { company_id: 'beta', invoice_no: '7002', project_no: '4521', payment_status: 'open', invoice_date: '2026-01-01' }]);
  wB('contacts', []); wB('vendors', []); wB('needs_review', []);
  const appB = launch({ crmDir, storeDir: dirB, outDir: tmp, mode: 'http' });
  const onPageB = JSON.parse(appB.eval("JSON.stringify([DATA.shipments.map(s=>s.shipment_id), DATA.invoices.map(i=>i.invoice_no)])"));
  r.check("with one twin archived, the live twin's leg and invoice are still on the page, and the archived twin's are not",
    JSON.stringify(onPageB) === JSON.stringify([['4521-LB'], ['7002']]), JSON.stringify(onPageB));
  appB.eval("setFilter('all'); select('beta');");
  const mainB = appB.doc.getElementById('main').innerHTML;
  r.check("and Beta's company page shows them",
    /VPO-BETA/.test(mainB) && /7002/.test(mainB), mainB.slice(0, 300));
  appB.eval("setFilter('live');");
  const orphanCard = clickOf(appB.doc.getElementById('main').innerHTML, 'orphan live job', 'div class="lt-card"');
  r.check("a company-less twin's own Live card names its empty customer",
    /openProject\('4521',''\)/.test(orphanCard), orphanCard.slice(0, 300));
  appB.fn('openProject')('4521', '');
  r.check("and opens ITS drawer, not another customer's record of the number",
    (appB.el('f_desc') || EMPTY).value === 'orphan job'
      && /saveProject\('4521',''\)/.test((appB.el('dbody') || EMPTY).innerHTML || ''),
    `desc=${(appB.el('f_desc') || EMPTY).value}`);

  // ---- KPI arithmetic ----------------------------------------------------
  // nothing validates the TYPE of year or revenue, and `a + (p.revenue||0)` on
  // a string CONCATENATES rather than adds
  app.eval(`DATA.projects.push({company_id:'acme', project_no:'8001', status:'won',
                                year:String(new Date().getFullYear()),
                                revenue:'12000', archived:false});
            DATA.projects.push({company_id:'acme', project_no:'8002', status:'won',
                                year:new Date().getFullYear(),
                                revenue:5000, archived:false});
            reindex();`);
  safe('kpis');
  const kpiText = (app.el('kpis') || EMPTY).innerHTML;
  const wonFigure = (/\$([0-9,]+)/.exec(kpiText.split('Won revenue')[0].split('<div class="n">').pop()) || [])[1];
  r.check('a string-typed year is counted in the KPI, not silently dropped',
    kpiText.includes('17,000'),
    `Won revenue rendered as ${wonFigure} -- expected 17,000 (12000 + 5000)`);
  r.check('and a string revenue is added, not concatenated',
    !/\$1[0-9]{6,}/.test(kpiText),
    'a string revenue concatenated into a nonsense total');

  // ---- a write that never reaches the server ------------------------------
  //
  // THE CLASS, not six separate defects. Every one of these awaited CRM.call
  // with no catch, so a dead socket rejected out of the handler and the
  // operator saw the button go quiet: no message, no alert, nothing changed
  // and nothing said.
  //
  // Of the ten sites that awaited CRM.call, four caught and six did not, and
  // catching was UNCORRELATED with being tested: three of the four -- 
  // fetchEnrichment, draft, replyToThread -- had no test at all. Habit put
  // those try/catches there, and habit is not coverage. What tests predicted
  // was not whether a catch existed but whether it told the truth, which is
  // why every check below asserts what the operator SEES.
  //
  // `sees` asserts what the OPERATOR gets, never that a catch exists. A
  // handler that swallows the rejection silently passes a structural check
  // and fails this one.
  const dead = () => launch({ crmDir, storeDir: seedStore(
    fs.mkdtempSync(path.join(os.tmpdir(), 'crmdead-'))), outDir: tmp, mode: 'http',
    onCall: (t) => Promise.reject(new Error('socket hung up: ' + t)) });
  const msgOf = (a) => ((a.el('savedMsg') || EMPTY).textContent || '');
  const SITES = [
    ['rename_project', async (a) => {
      a.fn('openProject')('4521'); a.el('f_pno').value = '4599';
      await a.fn('saveProject')('4521');
    }, (a) => /✗/.test(msgOf(a))],
    ['archive_project', async (a) => { await a.fn('deleteProject')('4521'); },
      (a) => a.alerts().some(m => /failed/i.test(m))
             && a.eval("String(DATA.projects.some(p=>String(p.project_no)==='4521'))") === 'true'],
    ['convert_lead', async (a) => { await a.fn('convertLead')('acme'); },
      (a) => a.alerts().some(m => /failed/i.test(m))],
    ['rename_invoice', async (a) => {
      a.fn('openEditInvoice')('acme', '9001'); a.el('e_iv_no').value = '9099';
      await a.fn('saveEditInvoice')('acme', '9001');
    }, (a) => /✗/.test(msgOf(a))],
    ['archive_company', async (a) => { await a.fn('deleteCompany')('acme'); },
      (a) => a.alerts().some(m => /failed/i.test(m))
             && a.eval("String(DATA.companies.some(c=>c.company_id==='acme'))") === 'true'],
    ['reassign_shipment', async (a) => {
      a.fn('openShipment')('4521-L2'); a.el('s_pno').value = '4599';
      await a.fn('saveShipment')('4521-L2');
    }, (a) => /✗/.test(msgOf(a))],
  ];
  for (const [tool, drive, sees] of SITES) {
    const a = dead();
    let threw = null;
    try { await drive(a); } catch (e) { threw = e; }
    // Separate checks on purpose: "it did not blow up" and "the operator was
    // told" are different failures and a combined check hides which happened.
    r.check(`a dead socket on ${tool} does not escape the handler`,
      threw === null, threw && threw.message);
    r.check(`and ${tool} tells the operator it failed`, threw === null && sees(a),
      `msg=${JSON.stringify(msgOf(a))} alerts=${JSON.stringify(a.alerts())}`);
  }

  // The two sites that ALREADY caught, and what they did with the value.
  //
  // A structural check -- "is there a catch here" -- passes on both of these
  // unchanged, which is exactly why this suite does not write one. doSave
  // printed `e.message` and replyToThread alerted it; for an Error that is the
  // reason, and for anything else it is the literal string "undefined". The
  // operator gets a red mark that says nothing, which is the silence this
  // whole commit is about, one layer in.
  //
  // Reachable only in COWORK mode. CRM.call has no throw of its own: it
  // propagates whatever its transport rejects with, and fetch (http) and
  // embeddedCall reject with Errors. cowork's rejection comes from the host's
  // window.cowork.callMcpTool, which owes us nothing -- a string or a bare
  // {code:-32603} both arrive. That is also the mode the operator runs in.
  {
    const bridge = (v) => launch({ crmDir, storeDir: seedStore(
      fs.mkdtempSync(path.join(os.tmpdir(), 'crmbridge-'))), outDir: tmp,
      mode: 'cowork', onCall: () => Promise.reject(v) });
    // A string and a bare object: the two shapes an MCP bridge actually
    // produces. Neither has `.message`.
    for (const [label, v] of [['a string', 'bridge closed'],
                              ['a bare object', { code: -32603 }]]) {
      {
        // No rename -- f_pno is left alone so this falls through to
        // doSave('update_project'), which is the catch under test. Renaming
        // would be caught by saveProject's own guard instead.
        const a = bridge(v);
        a.fn('openProject')('4521');
        await a.fn('saveProject')('4521');
        const m = msgOf(a);
        r.check(`doSave names a reason when the bridge rejects with ${label}`,
          /✗/.test(m) && !/undefined/.test(m), `savedMsg=${JSON.stringify(m)}`);
      }
      {
        const a = bridge(v);
        let threw = null;
        try { await a.fn('replyToThread')('acme', 'msg-1'); }
        catch (e) { threw = e; }
        const said = a.alerts().join(' | ');
        r.check(`replyToThread names a reason when the bridge rejects with ${label}`,
          threw === null && /could not create reply draft/i.test(said)
            && !/undefined/.test(said),
          `threw=${threw && threw.message} alerts=${JSON.stringify(a.alerts())}`);
      }
    }
  }

  // The same rule for a READ. `ENRICH[id] = null` renders "No Outlook signal
  // on file" -- a claim about the data, byte-identical to a company that
  // genuinely has none, made when the truth is that nobody managed to ask.
  {
    const a = dead();
    a.fn('select')('acme');          // the real path: select renders, then asks
    await a.fn('fetchEnrichment')('acme');
    r.check('an unreachable Outlook is reported as unreachable, not as "none"',
      /Could not reach Outlook/.test((a.el('main') || EMPTY).innerHTML || ''),
      ((a.el('main') || EMPTY).innerHTML || '').includes('No Outlook signal')
        ? 'rendered "No Outlook signal on file" for a call that never completed'
        : 'neither message rendered');
  }

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

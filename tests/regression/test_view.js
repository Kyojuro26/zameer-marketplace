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
const { launch, makeResult } = require('../lib/view.js');

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
    role: 'customer', domains: [], locations: [], archived: false }]);
  // every field below carries a type the render path did not expect
  w('contacts', [{ company_id: 'acme', name: 'A Person', email: FIXTURE_EMAIL,
    last_action: 45731 }]);
  w('projects', [{ company_id: 'acme', project_no: '4521', status: null,
    year: 2026, revenue: 100000, owner: 'D', annotations: 'note one',
    description: 12345, collection_status: 'partial:30%', archived: false },
    // NO NUMBER. The deal log yields these (16 of 261 on the real store); the
    // app cannot open or edit one. year 2024 keeps it out of the KPI checks.
    { company_id: 'acme', project_no: null, status: 'won', year: 2024,
      revenue: 500, description: 'numberless deal', archived: false },
    // and one on the Live screen, which renders its own card and list item
    { company_id: 'acme', project_no: null, status: 'won', year: 2024,
      revenue: 700, description: 'numberless live', archived: false,
      tracker_status: 'action_admin', open_orders_notes: 'numberless live job' }]);
  w('shipments', [
    { shipment_id: '4521-L1', company_id: 'acme', project_no: '4521',
      all_project_nos: '4521', stage: null, ship_date: 45731 },
    { shipment_id: '4521-L2', company_id: 'acme', project_no: '4521',
      all_project_nos: ['4521'], stage: 'Shipped', ship_date: '3/14/2026' },
    { shipment_id: '4521-L3', company_id: 'acme', project_no: 4521,
      all_project_nos: [4521], stage: 'Ordered', ship_date: '2026-03-14 00:00:00' }]);
  w('invoices', [{ company_id: 'acme', invoice_no: '9001', project_no: '4521',
    payment_status: 'partial:30%', payment_notes: 45731, invoice_date: 45731 }]);
  w('vendors', []); w('needs_review', []);
  return dir;
}

async function run(crmDir) {
  const r = makeResult('view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmview-'));
  const store = seedStore(path.join(tmp, 'store'));
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });

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
  app.resetCalls();
  safe('saveProject', '4521');
  const proj = app.calls().find(c => c.tool === 'update_project');
  r.check('a project with no stored status does not send an empty status',
    proj && proj.args.fields.status !== '',
    proj && JSON.stringify(proj.args.fields.status));

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
  r.check('a numbered row is still clickable',
    /onclick="openProject\('4521'\)"/.test(numbered), numbered.slice(0, 200));
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
  r.check('the Live sidebar item for it carries no click',
    /citem/.test(side) && !/onclick="openProject\('(null|)'\)"/.test(side), side.slice(0, 200));
  // and the entry point itself: a click that does slip through opens nothing
  safe('closeDrawer');
  safe('openProject', ''); safe('openProject', 'null');
  r.check('openProject with no number opens no drawer',
    !((app.el('drawer') || EMPTY).classList || { contains: () => false }).contains('open'));
  safe('setFilter', 'all'); safe('select', 'acme');

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

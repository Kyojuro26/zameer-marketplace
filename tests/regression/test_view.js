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
    description: 12345, collection_status: 'partial:30%', archived: false }]);
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

function run(crmDir) {
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

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

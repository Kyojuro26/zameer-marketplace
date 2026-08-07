// Drawer close affordances: scrim click, Escape, and the unsaved-edit guard.
//
// The change under test made closing EASY (click outside / Esc), which is a
// convenience that creates a data-loss path: the X was a deliberate act, a
// stray click beside a drawer is not, and this store is the only copy of the
// operator's receivables. So the guard is the point, not the scrim.
//
// Three things these tests are built to catch, all of which have real
// precedent in this repo:
//
//  1. GUARD APPLIED TO ONE PATH, NOT ITS TWINS. A confirm wired to the scrim
//     but not to Escape (or to the X) is the fix-by-instance failure. Every
//     user-initiated close is asserted separately -- none is assumed to
//     inherit the others' behaviour.
//
//  2. A GUARD THAT BLOCKS THE WRONG THING. Every save path calls closeDrawer()
//     after a successful write; if the guard leaked into that path, a save
//     would prompt "discard your changes?" about changes it had just SAVED,
//     and answering no would leave the drawer stranded open over committed
//     data. closeDrawer() is asserted to close unconditionally while dirty.
//
//  3. A STATED GUARANTEE NOTHING ENFORCES. Eleven drawers open; all eleven
//     must route through openDrawer() or their scrim never appears and the
//     dirty flag never resets, so the NEXT drawer inherits the last one's
//     dirty state. Asserted against the generated bundle, not the template.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { launch, makeResult, buildBundle } = require('../lib/view.js');
const { fire } = require('../lib/dom.js');

const FIXTURE_EMAIL = ['person', 'example.invalid'].join('@');

function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer',
      domains: [], locations: ['Dallas TX'], archived: false },
    { company_id: 'other', display_name: 'Meridian Corp', role: 'customer',
      domains: [], locations: ['Columbus OH'], archived: false }]);
  w('contacts', [{ company_id: 'acme', name: 'A Person', email: FIXTURE_EMAIL,
    last_action: '2026-07-22' }]);
  w('projects', [{ company_id: 'acme', project_no: '4521', status: 'Won',
    year: 2026, revenue: 100000, owner: 'D', description: 'Conveyor',
    collection_status: 'partial:30%', archived: false }]);
  w('shipments', [{ shipment_id: '4521-L1', company_id: 'acme',
    project_no: '4521', all_project_nos: ['4521'], stage: 'Shipped',
    ship_date: '2026-03-14' }]);
  w('invoices', [{ company_id: 'acme', invoice_no: '9001', project_no: '4521',
    payment_status: 'partial:30%', payment_notes: '30% deposit',
    invoice_date: '2026-06-09' }]);
  w('vendors', []); w('needs_review', []);
  return dir;
}

// The eleven entry points, with an argument set that reaches the open call.
const OPENERS = [
  ["openProject('4521')", 'project'],
  ["openNewProject('acme')", 'new project'],
  ["openNewContact('acme')", 'new contact'],
  [`openEditContact('acme','${FIXTURE_EMAIL}','A Person')`, 'edit contact'],
  ["openNewShipment('4521')", 'new shipment'],
  ["openNewCompany('customer')", 'new company'],
  ["openEditCompany('acme')", 'edit company'],
  ["openEditVendor('acme')", 'edit vendor'],
  ["openNewInvoice('acme')", 'new invoice'],
  ["openEditInvoice('acme','9001')", 'edit invoice'],
  ["openShipment('4521-L1')", 'shipment'],
];

function run(crmDir) {
  const r = makeResult('drawer-close');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmdrawer-'));
  const store = seedStore(path.join(tmp, 'store'));

  // ---- source-level: the wiring exists at all -------------------------------
  // These run against the GENERATED bundle. A template that looks right but
  // emits something else is the exact gap that made "shipped fact" unreliable
  // in this repo before.
  const { js, html } = buildBundle(crmDir, store, tmp);

  r.check('scrim element is in the page', /id="scrim"/.test(html));
  r.check('the X routes through the guard, not a bare close',
    /class="x"[^>]*onclick="requestCloseDrawer\(\)"/.test(html),
    'the X must ask about unsaved edits too -- it discards just as much');
  r.check('scrim becomes clickable only when open',
    /\.scrim\.open\{[^}]*pointer-events:auto/.test(html));
  r.check('scrim sits under the drawer but over the page',
    (() => {
      const s = /\.scrim\{[^}]*z-index:(\d+)/.exec(html);
      const d = /\.drawer\{[^}]*z-index:(\d+)/.exec(html);
      return s && d && +s[1] < +d[1];
    })(), 'a scrim above the drawer would swallow every click in the form');

  // no drawer may open by touching the class directly -- that bypasses both
  // the scrim and the dirty reset
  const strayOpens = (js.match(/getElementById\('drawer'\)\.classList\.add\('open'\)/g) || []).length;
  r.check('every drawer opens through openDrawer()', strayOpens === 1,
    `${strayOpens} direct .add('open') calls; expected exactly 1 (inside openDrawer)`);
  r.check('openDrawer does not call itself', !/function openDrawer\(\)\{[^}]*openDrawer\(\)/.test(js.replace(/\s+/g, '')));

  // ---- behavioural ----------------------------------------------------------
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
  // via the document's own lazy getter: #drawer is not registered until
  // something reaches for it, and app.el() only reads the existing registry
  const drawer = app.doc.getElementById('drawer');
  const scrim = app.doc.getElementById('scrim');
  const dbody = app.doc.getElementById('dbody');
  const isOpen = () => drawer.classList.contains('open');
  const scrimOn = () => scrim.classList.contains('open');

  r.check('a listener is actually bound to the scrim',
    (scrim._listeners.click || []).length > 0, 'no handler -> clicking outside does nothing');
  r.check('a keydown listener is actually bound',
    (app.doc._listeners.keydown || []).length > 0);
  r.check('an input listener is bound to the drawer body',
    (dbody._listeners.input || []).length > 0, 'without it nothing is ever dirty');

  // all eleven open the scrim, not just the three named in the request
  OPENERS.forEach(([call, label]) => {
    app.eval('closeDrawer();');
    app.eval(call);
    r.check(`${label}: drawer opens`, isOpen(), call);
    r.check(`${label}: scrim opens with it`, scrimOn(), call);
  });

  // clean drawer -> outside click closes with NO prompt
  app.eval("closeDrawer(); openEditInvoice('acme','9001');");
  app.resetConfirms();
  fire(scrim, 'click', {});
  r.check('clean drawer: outside click closes it', !isOpen());
  r.check('clean drawer: scrim hides too', !scrimOn(),
    'a scrim left visible blocks the whole page');
  r.check('clean drawer: no pointless prompt', app.confirms().length === 0,
    `asked: ${JSON.stringify(app.confirms())}`);

  // dirty drawer -> outside click asks; answering NO keeps it open
  app.eval("openEditInvoice('acme','9001');");
  fire(dbody, 'input', {});
  app.resetConfirms();
  app.answerConfirm(false);
  fire(scrim, 'click', {});
  r.check('dirty drawer: the operator is asked before discarding',
    app.confirms().length === 1, `asked ${app.confirms().length} times`);
  r.check('dirty drawer: answering no keeps the drawer open', isOpen(),
    'this is the whole point -- a stray click must not lose typed work');
  r.check('dirty drawer: answering no keeps the scrim up', scrimOn());

  // ...answering YES discards and closes
  app.resetConfirms();
  app.answerConfirm(true);
  fire(scrim, 'click', {});
  r.check('dirty drawer: answering yes closes it', !isOpen());

  // Escape must behave identically -- the fix-by-instance trap
  app.eval("openEditInvoice('acme','9001');");
  fire(dbody, 'change', {});                    // a <select> edit, not typing
  app.resetConfirms();
  app.answerConfirm(false);
  fire(app.doc, 'keydown', { key: 'Escape' });
  r.check('Escape asks on a dirty drawer too', app.confirms().length === 1,
    'a guard on the scrim but not Escape is the same bug in a new place');
  r.check('Escape obeys no', isOpen());
  app.answerConfirm(true);
  fire(app.doc, 'keydown', { key: 'Escape' });
  r.check('Escape closes when allowed', !isOpen());

  // a non-Escape key must not close anything
  app.eval("openEditInvoice('acme','9001');");
  app.resetConfirms();
  fire(app.doc, 'keydown', { key: 'a' });
  r.check('other keys do not close the drawer', isOpen());
  r.check('other keys do not prompt', app.confirms().length === 0);

  // Escape with NO drawer open must not prompt about anything
  app.eval('closeDrawer();');
  app.resetConfirms();
  fire(app.doc, 'keydown', { key: 'Escape' });
  r.check('Escape with no drawer open is inert', app.confirms().length === 0);

  // the save path must never be interrupted, even while dirty
  app.eval("openEditInvoice('acme','9001');");
  fire(dbody, 'input', {});
  app.resetConfirms();
  app.answerConfirm(false);          // if the guard leaked in, this would block
  app.eval('closeDrawer();');
  r.check('a completed save closes without prompting', !isOpen(),
    'closeDrawer() is the save path -- prompting there strands a saved record');
  r.check('the save path asks nothing', app.confirms().length === 0);

  // dirt must not survive into the next drawer
  app.eval("openEditInvoice('acme','9001');");
  fire(dbody, 'input', {});
  app.eval("closeDrawer(); openProject('4521');");
  app.resetConfirms();
  fire(scrim, 'click', {});
  r.check('a fresh drawer starts clean', !isOpen() && app.confirms().length === 0,
    'stale dirt makes every later drawer prompt for edits that were never made');

  // reopening without closing (drawer -> drawer) must also reset
  app.eval("openEditInvoice('acme','9001');");
  fire(dbody, 'input', {});
  app.eval("openProject('4521');");        // straight from one drawer to another
  app.resetConfirms();
  fire(scrim, 'click', {});
  r.check('switching drawers directly resets dirt',
    !isOpen() && app.confirms().length === 0);

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

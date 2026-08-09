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
//
// WHAT THIS FILE CANNOT VERIFY
// ---------------------------
// Read this before trusting a green run. The harness is a hand-written DOM
// shim (../lib/dom.js) running the real bundle under node. It models state you
// ASSIGN well and behaviour that FOLLOWS from state not at all. Concretely:
//
//   * No Node.contains and no document.activeElement. The focusin fallback in
//     build_view.py returns on its second line under this shim, so NOT ONE line
//     of that handler has ever executed here. The check below confirms only
//     that a listener was registered -- the handler body could be anything.
//   * focus() is a no-op that records nothing, so drawerReturnFocus, the focus
//     move into an opening drawer, and the restore on close are unassertable.
//   * `inert` is a plain property with no semantics: assigning it does not
//     affect focus, hit-testing or tab order. "a closed drawer is inert" below
//     asserts that an assignment happened. It is NOT a test of tab order --
//     the proposition and the assertion share a word and nothing else.
//   * No CSS. Whether a refused save is actually VISIBLE depends on the .show
//     class against `.saved{opacity:0}`, and nothing here can see that. The
//     scrim's four checks are regexes over the stylesheet TEXT, not over any
//     computed effect.
//   * `disabled` has no semantics either: fire() reaches a disabled control.
//     The save-time form lock is asserted by reading the property.
//   * querySelectorAll answers tag-name selectors only (added for that lock).
//
// Anything in that list needs a real browser to test honestly. Until there is
// one, treat these as change-detectors for the wiring, not proof of behaviour.
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
  // a tracker row with no project number: the 12th drawer adopts it into the
  // CRM, and without a row to adopt that opener would bail before opening
  w('tracker_unlinked', [{ sheet_row: 4, reason: 'no project number',
    client: 'Ace Manufacturing', client_po: 'PO-9', start_date: '2026-05-01',
    location: 'Dallas TX', open_orders_notes: 'waiting on frames',
    tracker_status: 'awaiting_materials', legs: [] }]);
  w('tracker_buckets', [{ key: 'awaiting_materials', label: 'Waiting on materials',
    argb: 'FF00FFFF', legend_row: 19 }]);
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
  ["openAdoptTrackerRow(0)", 'adopt tracker row'],
];

// async: one assertion needs a real save to have completed before it can ask
// whether the drawer is still dirty. run_all.py's runner awaits the result.
async function run(crmDir) {
  const r = makeResult('drawer-close');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmdrawer-'));
  const store = seedStore(path.join(tmp, 'store'));

  // ---- source-level: the wiring exists at all -------------------------------
  // These run against the GENERATED bundle. A template that looks right but
  // emits something else is the exact gap that made "shipped fact" unreliable
  // in this repo before.
  const { js, html } = buildBundle(crmDir, store, tmp);

  r.check('scrim element is in the page', /id="scrim"/.test(html));

  // Anchored to the DRAWER's own X (id=drawerX), not to "any element with
  // class=x anywhere on the page" -- the looser form was satisfied by a decoy
  // button elsewhere in the document while the real X had been reverted.
  r.check('the X routes through the guard, not a bare close',
    /id="drawerX"[^>]*onclick="requestCloseDrawer\(\)"|onclick="requestCloseDrawer\(\)"[^>]*id="drawerX"/.test(html),
    'the X must ask about unsaved edits too -- it discards just as much');

  // The scrim's four load-bearing properties. Each of these was mutated and
  // survived the first version of this file, and each has a distinct
  // user-visible failure, so each is asserted separately.
  r.check('scrim is inert when closed',
    /\.scrim\{[^}]*pointer-events:none/.test(html),
    'without the base rule an invisible scrim swallows EVERY click in the app');
  r.check('scrim becomes clickable only when open',
    /\.scrim\.open\{[^}]*pointer-events:auto/.test(html));
  r.check('scrim actually covers the viewport',
    /\.scrim\{[^}]*inset:0/.test(html),
    'a zero-size scrim blocks nothing and the stale-record bug returns');
  r.check('scrim sits under the drawer but over the page',
    (() => {
      const s = /\.scrim\{[^}]*z-index:(\d+)/.exec(html);
      const d = /\.drawer\{[^}]*z-index:(\d+)/.exec(html);
      // the page layer that matters: the sticky header. A scrim beneath it
      // leaves the topbar clicking through to the page under an open drawer.
      const h = /header\{[^}]*z-index:(\d+)/.exec(html);
      return s && d && h && +s[1] < +d[1] && +s[1] > +h[1];
    })(), 'must be above the sticky header and below the drawer');

  // no drawer may open by touching the class directly -- that bypasses the
  // scrim, the dirty reset, inert and focus. Quote-agnostic: the single-quote
  // -only form missed a double-quoted twelfth opener.
  // Matched on the ACT of adding the class, not on one spelling of how the
  // element was fetched: an earlier version keyed on the literal
  // `getElementById('drawer').classList.add('open')` and silently matched
  // nothing the moment that line was refactored to a local `const d`.
  const openBody = /function openDrawer\(\)\s*\{([\s\S]*?)\n\}/.exec(js);
  r.check('openDrawer() is findable in the bundle', !!openBody);
  const addsAll = (js.match(/\.classList\.add\((['"])open\1\)/g) || []).length;
  const addsInside = openBody
    ? (openBody[1].match(/\.classList\.add\((['"])open\1\)/g) || []).length : -1;
  r.check('the open class is only ever set inside openDrawer()',
    addsAll === addsInside && addsInside === 2,
    `${addsAll} in the bundle, ${addsInside} inside openDrawer (expect 2 = drawer + scrim)`);
  // every open* entry point is accounted for by OPENERS below; a new one added
  // later must be added there too, or this fails
  const entryPoints = (js.match(/^function open[A-Z]\w*\(/gm) || [])
    .map(s => s.replace(/^function /, '').replace(/\($/, ''))
    .filter(n => n !== 'openDrawer');
  r.check(`all ${entryPoints.length} open* entry points are exercised below`,
    entryPoints.length === OPENERS.length,
    `bundle has ${entryPoints.length} (${entryPoints.join(',')}), OPENERS lists ${OPENERS.length}`);

  // ---- behavioural ----------------------------------------------------------
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
  // via the document's own lazy getter: #drawer is not registered until
  // something reaches for it, and app.el() only reads the existing registry
  const drawer = app.doc.getElementById('drawer');
  const scrim = app.doc.getElementById('scrim');
  const dbody = app.doc.getElementById('dbody');
  const isOpen = () => drawer.classList.contains('open');
  const scrimOn = () => scrim.classList.contains('open');

  // Checked by RUNNING openDrawer, not by pattern-matching the source. Two
  // regex versions of this check were written and BOTH could never fail: the
  // first stripped all whitespace then searched for a pattern containing a
  // space; the second used [^}]*, which stops at the first `}` -- the close of
  // an if-block four lines above the recursive call. A regex cannot answer
  // this question about JavaScript; calling the function can.
  const recursionOk = r.check('openDrawer does not recurse', (() => {
    try { app.eval("openProject('4521'); closeDrawer();"); return true; }
    catch (e) { return !/call stack/i.test(String((e && e.message) || e)); }
  })(), 'openDrawer() calling openDrawer() blows the stack on the first open');
  // Bail with a VERDICT rather than letting the next openProject take the
  // process down. A module that dies prints no [PASS]/[FAIL] line, and both
  // run_all.py and the mutation harness now (correctly) refuse to read a crash
  // as a detection -- so without this the one real signal here is thrown away.
  if (!recursionOk) { fs.rmSync(tmp, { recursive: true, force: true }); return r; }

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

  // ...answering YES discards and closes -- and MUST still have asked.
  // Without the "was asked" half, clearing the flag before prompting passes:
  // cancel once and the second stray click discards silently, unasked.
  app.resetConfirms();
  app.answerConfirm(true);
  fire(scrim, 'click', {});
  r.check('dirty drawer: answering yes closes it', !isOpen());
  r.check('dirty drawer: the second attempt still asks', app.confirms().length === 1,
    'a guard that clears the flag before prompting stops asking after one cancel');

  // the wording itself, not just that something was asked. An inverted prompt
  // ("Keep editing?") means OK does the opposite of what the operator reads.
  const msg = app.confirms()[0] || '';
  r.check('the prompt says discard', /discard/i.test(msg), msg);
  r.check('the prompt names the record', /Edit invoice/.test(msg),
    `should name what is being discarded; got: ${msg}`);
  r.check('the prompt says the loss is permanent', /cannot be recovered/i.test(msg), msg);

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

  // Escape with NO drawer open must do nothing at all. Asserting only "no
  // prompt" was tautological -- closeDrawer() clears the flag, so a guard that
  // had lost its is-open check would still not prompt. The real claim is that
  // the page is not left inert and focus is not stolen.
  // A sentinel, because the obvious assertions are all tautological here:
  // closeDrawer() clears the dirty flag, so "no prompt" holds whether or not
  // the handler ran, and closing an already-closed drawer looks like a no-op.
  // The one thing that DOES differ is that closeDrawer() writes the page's
  // inert state -- so a value only it would overwrite proves it never ran.
  app.eval('closeDrawer();');
  app.resetConfirms();
  app.eval("document.getElementById('apphdr').inert = 'UNTOUCHED';");
  fire(app.doc, 'keydown', { key: 'Escape' });
  r.check('Escape with no drawer open does not prompt', app.confirms().length === 0);
  r.check('Escape with no drawer open runs nothing at all',
    app.doc.getElementById('apphdr').inert === 'UNTOUCHED',
    'the handler must check the drawer is open before doing any work');
  r.check('Escape with no drawer open does not open one', !isOpen());
  app.eval("document.getElementById('apphdr').inert = false;");

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

  // ---- the four defects found by review of the first version ---------------

  // 1. A SAVE CLEARS THE FLAG. saveProject deliberately does not close (it
  //    keeps the "Saved" flash), so without this the flag stayed true over a
  //    written record and the next Escape asked about saved changes. The harm
  //    is habituation: an operator taught to dismiss a false prompt dismisses
  //    the real one.
  app.eval("closeDrawer(); openProject('4521');");
  fire(dbody, 'input', {});
  app.resetCalls();
  await app.eval("saveProject('4521')");
  r.check('a successful save was actually attempted',
    app.calls().some(c => c.tool === 'update_project'),
    `tools called: ${app.calls().map(c => c.tool).join(',') || 'none'}`);
  r.check('the drawer stays open after a project save', isOpen(),
    'saveProject keeps it open on purpose -- if this changed, the test below is moot');
  app.resetConfirms();
  app.answerConfirm(false);
  fire(app.doc, 'keydown', { key: 'Escape' });
  r.check('no false prompt after a successful save', app.confirms().length === 0,
    'the record is on disk; asking "discard unsaved changes?" here is a lie');
  r.check('and it closes', !isOpen());

  // 2. IN-DRAWER NAVIGATION ASKS. "+ Add shipment" sits inside the project
  //    drawer and replaces the form; the openers swap #dbody before calling
  //    openDrawer, so the reset would hide the loss.
  // EVERY call site, not "at least one". A second + Add shipment button was
  // added later (the shipments empty state), and the old any-one-of form then
  // passed with the in-drawer button reverted to a bare opener.
  {
    const calls = (js.match(/onclick="[^"]*?openNewShipment\(/g) || []);
    const wrapped = calls.filter(c => /navFromDrawer\(\(\)=>openNewShipment\($/.test(c));
    r.check(`all ${calls.length} openNewShipment call sites route through navFromDrawer`,
      calls.length > 0 && wrapped.length === calls.length,
      `${wrapped.length}/${calls.length} wrapped -- an unwrapped one discards the open form silently`);
  }
  app.eval("closeDrawer(); openProject('4521');");
  fire(dbody, 'input', {});
  app.resetConfirms();
  app.answerConfirm(false);
  app.eval("navFromDrawer(()=>openNewShipment('4521'))");
  r.check('leaving a dirty project form asks first', app.confirms().length === 1);
  r.check('answering no keeps the project form', /Project/.test(app.doc.getElementById('dtitle').textContent),
    `title is now: ${app.doc.getElementById('dtitle').textContent}`);
  app.answerConfirm(true);
  app.eval("navFromDrawer(()=>openNewShipment('4521'))");
  r.check('answering yes navigates', /shipment/i.test(app.doc.getElementById('dtitle').textContent));
  app.resetConfirms();
  fire(scrim, 'click', {});
  r.check('the new form starts clean', !isOpen() && app.confirms().length === 0);

  // 3. DOUBLE-CLICK. The scrim goes live the instant the drawer opens while the
  //    dim is still fading, so click 2 of a double-click on a row lands on it
  //    and shuts what click 1 opened.
  app.eval("closeDrawer(); openProject('4521');");
  app.resetConfirms();
  fire(scrim, 'click', { detail: 2 });
  r.check('the second click of a double-click does not close the drawer', isOpen(),
    'otherwise every double-clicked row looks like it refuses to open');
  fire(scrim, 'click', { detail: 1 });
  r.check('an ordinary single click still closes it', !isOpen());

  // 4. THE PAGE IS INERT WHILE A DRAWER IS OPEN. The scrim stops the mouse;
  //    only inert stops Tab reaching the search box and filter buttons, where
  //    Enter repaints the main pane under the open drawer.
  app.eval("closeDrawer();");
  const hdr = app.doc.getElementById('apphdr'), wrap = app.doc.getElementById('appwrap');
  r.check('page is interactive with no drawer open',
    hdr.inert !== true && wrap.inert !== true);
  app.eval("openProject('4521');");
  r.check('header goes inert when a drawer opens', hdr.inert === true,
    'without this, Tab reaches the KPIs and the search box under the scrim');
  r.check('sidebar and main go inert when a drawer opens', wrap.inert === true,
    'this is what stops Enter on a filter button repainting under the drawer');
  app.eval("closeDrawer();");
  r.check('header is interactive again after close', hdr.inert !== true);
  r.check('sidebar and main are interactive again after close', wrap.inert !== true,
    'a page left inert is an app that cannot be clicked at all');

  // 5. RELOAD/CLOSE-TAB. Same loss, different exit.
  const bu = (app.sandbox.window._listeners.beforeunload || []);
  r.check('a beforeunload guard is bound', bu.length > 0);
  if (bu.length) {
    app.eval("closeDrawer(); openProject('4521');");
    let ev = { prevented: false, preventDefault() { this.prevented = true; }, returnValue: null };
    bu[0](ev);
    r.check('clean drawer does not block a reload', !ev.prevented,
      'prompting on every reload trains the operator to ignore it');
    fire(dbody, 'input', {});
    ev = { prevented: false, preventDefault() { this.prevented = true; }, returnValue: null };
    bu[0](ev);
    r.check('dirty drawer blocks a reload', ev.prevented);
  }

  // ---- defects found by the review of the FIXES ---------------------------

  // 6. A FAILED SAVE MUST NOT BE PAPERED OVER. Renaming a project is two calls:
  //    the rename can land while the field update is refused. doSave reports
  //    failure by writing into #savedMsg and never throws, so the reopen ran
  //    regardless -- wiping the error AND the typed values, and redrawing from
  //    data the failed save never updated. The operator saw the new number with
  //    the old figures and no error.
  r.check('saveProject only reopens when the save succeeded',
    /if\(renamed && ok\) openProject/.test(js),
    'reopening after a refused save destroys the error and the typed values');
  {
    const failApp = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (tool) => tool === 'update_project'
        ? { ok: false, error: 'refused' } : { ok: true },
    });
    failApp.eval("select('acme'); openProject('4521');");
    failApp.eval("document.getElementById('f_pno').value='9999';");
    await failApp.eval("saveProject('4521')");
    const t = failApp.doc.getElementById('dtitle').textContent;
    const m = failApp.doc.getElementById('savedMsg');
    r.check('a refused save leaves the form up', /4521/.test(t),
      `drawer retitled to: ${t} -- the reopen destroyed the failed form`);
    r.check('a refused save writes an error (VISIBILITY not verified -- no CSS)',
      /✗/.test(m.textContent || ''),
      `savedMsg is now: ${JSON.stringify(m.textContent)}`);
  }

  // 6b. ...and the reopen must STILL happen when the save succeeds. It exists
  //     because a rename changes the project_no baked into this drawer's own
  //     Delete and "+ Add shipment" handlers; without it they keep acting on a
  //     number that no longer exists. Guarding the reopen on `ok` is only
  //     correct if `ok` is genuinely true on success.
  {
    const okApp = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: () => ({ ok: true }),
    });
    okApp.eval("select('acme'); openProject('4521');");
    okApp.eval("document.getElementById('f_pno').value='9999';");
    await okApp.eval("saveProject('4521')");
    const t = okApp.doc.getElementById('dtitle').textContent;
    r.check('a successful rename reopens the drawer on the new number',
      /9999/.test(t),
      `drawer still titled: ${t} -- its buttons would act on the old number`);
  }

  // 7. THE FORM IS LOCKED FOR THE WHOLE ROUND TRIP. Callers read their fields
  //    into the payload before doSave runs, so anything typed while the call is
  //    in flight would not be sent -- and ten of the eleven callers close the
  //    drawer from inside applyLocal, which clears the dirty flag, so those
  //    keystrokes went with no prompt and no beforeunload warning. An earlier
  //    attempt used a counter checked AFTER applyLocal, which could never fire
  //    on those ten paths. The window is now closed rather than accounted for.
  {
    let release;
    const slow = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: () => new Promise(res => { release = () => res({ ok: true }); }),
    });
    slow.eval("select('acme'); openProject('4521');");
    const rev = slow.doc.getElementById('f_revenue');
    r.check('fields are editable before a save', rev.disabled !== true);
    const p = slow.eval("saveProject('4521')");     // in flight, not awaited
    r.check('fields are locked while the save is in flight', rev.disabled === true,
      'an editable field here accepts keystrokes that are not in the payload');
    r.check('so is the notes box', slow.doc.getElementById('f_notes').disabled === true);
    release();
    await p;
    r.check('fields are editable again afterwards', rev.disabled === false,
      'a form left locked is a drawer that can never be corrected');
    r.check('and so is the save button',
      slow.doc.getElementById('saveBtn').disabled === false);
  }

  // 8. A CLOSED DRAWER IS OUT OF THE TAB ORDER. It is only translated
  //    off-screen, so its fields stayed focusable; typing in them set the dirty
  //    flag with nothing on screen, and beforeunload then blocked every reload
  //    with no visible cause.
  app.eval('closeDrawer();');
  r.check('a closed drawer has inert set (tab order NOT verified -- see header)',
    drawer.inert === true,
    'the intent is to keep the off-screen form out of the tab order');
  app.eval("openProject('4521');");
  r.check('an open drawer has inert cleared', drawer.inert === false,
    'an inert drawer cannot be typed into at all');
  app.eval('closeDrawer();');

  // 8b. navFromDrawer must not clear the flag until the opener has actually
  //     swapped the form. Several openers bail on a missing record; clearing
  //     first leaves the old form on screen, edits intact, marked clean --
  //     discarded later with no prompt. openNewShipment (the only wired
  //     caller today) cannot bail, so this is asserted against the contract
  //     directly rather than through it.
  app.eval("closeDrawer(); openProject('4521');");
  fire(dbody, 'input', {});
  app.answerConfirm(true);
  app.eval('navFromDrawer(function(){ return; })');   // an opener that bails
  app.resetConfirms();
  app.answerConfirm(false);
  fire(scrim, 'click', {});
  r.check('a bailing opener leaves the form still protected',
    app.confirms().length === 1,
    'the flag was cleared before the opener ran, so the untouched form reads clean');
  app.answerConfirm(true);
  app.eval('closeDrawer();');

  // 9. FALLBACK IF inert IS UNSUPPORTED. `el.inert = true` on an older engine
  //    is a silent no-op expando, which returns the keyboard bug with no signal.
  r.check('a focusin listener is registered (body NOT verified -- see header)',
    (app.doc._listeners.focusin || []).length > 0,
    'this only proves addEventListener ran; the shim cannot execute the body');

  // 10. beforeunload's legacy value must be NON-empty -- per the unload
  //     algorithm '' is precisely the value meaning "do not prompt".
  {
    const bu2 = (app.sandbox.window._listeners.beforeunload || []);
    app.eval("closeDrawer(); openProject('4521');");
    fire(dbody, 'input', {});
    const ev = { prevented: false, preventDefault() { this.prevented = true; }, returnValue: null };
    if (bu2.length) bu2[0](ev);
    r.check('beforeunload sets a non-empty returnValue',
      typeof ev.returnValue === 'string' && ev.returnValue.length > 0,
      `returnValue was ${JSON.stringify(ev.returnValue)} -- '' disables the prompt`);
    app.answerConfirm(true);
    app.eval('closeDrawer();');
  }

  // ---- the FAILURE branches, which had no assertions at all ----------------
  // Every mutant in the first three rounds targeted a success path. A reviewer
  // then showed that clearing the dirty flag on refusal, applying the local
  // write on refusal, and letting a refused rename fall through all survived.

  // 11. A REFUSED SAVE MUST LEAVE THE WORK PROTECTED. This is the moment the
  //     guard matters most: the store rejected it, so the typed values exist
  //     nowhere else.
  {
    const bad = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (t) => t === 'update_project' ? { ok: false, error: 'refused' } : { ok: true },
    });
    bad.eval("select('acme'); openProject('4521');");
    fire(bad.doc.getElementById('dbody'), 'input', {});
    await bad.eval("saveProject('4521')");
    bad.resetConfirms();
    bad.answerConfirm(false);
    fire(bad.doc, 'keydown', { key: 'Escape' });
    r.check('a refused save still prompts before discarding',
      bad.confirms().length === 1,
      'the store rejected it -- those values exist only on screen');
    r.check('and the drawer stays open on cancel',
      bad.doc.getElementById('drawer').classList.contains('open'));
  }

  // 11b. ...and the same when the call THROWS rather than returning ok:false.
  //      A dropped connection is the likeliest way this happens on his machine,
  //      and doSave's catch had no assertion at all.
  {
    const boom = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (t) => t === 'update_project'
        ? Promise.reject(new Error('network down')) : { ok: true },
    });
    boom.eval("select('acme'); openProject('4521');");
    fire(boom.doc.getElementById('dbody'), 'input', {});
    await boom.eval("saveProject('4521')");
    boom.resetConfirms();
    boom.answerConfirm(false);
    fire(boom.doc, 'keydown', { key: 'Escape' });
    r.check('a save that threw still prompts before discarding',
      boom.confirms().length === 1,
      'a dropped connection must not be read as a successful write');
  }

  // 12. A REFUSED SAVE MUST NOT BE APPLIED LOCALLY. Otherwise the KPI row and
  //     every list render show a figure the store never took, for the rest of
  //     the session, while the error is displayed alongside it.
  {
    const bad2 = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (t) => t === 'update_project' ? { ok: false, error: 'refused' } : { ok: true },
    });
    bad2.eval("select('acme'); openProject('4521');");
    bad2.eval("document.getElementById('f_revenue').value='250000';");
    await bad2.eval("saveProject('4521')");
    const rev = bad2.eval(
      "String((DATA.projects.find(p=>String(p.project_no)==='4521')||{}).revenue)");
    r.check('a refused save does not enter the in-memory ledger', rev === '100000',
      `DATA now says ${rev} for a write the store refused`);
  }

  // 13. A REFUSED RENAME MUST ABORT THE WHOLE SAVE. Falling through renumbers
  //     the project locally and then targets update_project at a number the
  //     store does not have -- while reporting success.
  {
    const badRen = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (t) => t === 'rename_project'
        ? { ok: false, error: 'number already in use' } : { ok: true },
    });
    badRen.eval("select('acme'); openProject('4521');");
    badRen.eval("document.getElementById('f_pno').value='9999';");
    await badRen.eval("saveProject('4521')");
    const tools = badRen.calls().map(c => c.tool);
    r.check('a refused rename does not go on to save fields',
      !tools.includes('update_project'),
      `called: ${tools.join(',')} -- update_project would target a phantom number`);
    r.check('a refused rename leaves the local number alone',
      badRen.eval("String((DATA.projects.find(p=>String(p.project_no)==='4521')||{}).project_no)") === '4521');
    r.check('a refused rename re-enables the save button',
      badRen.doc.getElementById('saveBtn').disabled === false,
      'otherwise the operator cannot correct it without a reload');
  }

  // 14. A COMMITTED RENAME IS NOT FIRED TWICE. rename lands, field save is
  //     refused, operator presses Save again: the old number is gone from the
  //     store, so re-firing reports "rename failed" for a rename that worked.
  {
    let renames = 0;
    const retry = launch({
      crmDir, storeDir: store, outDir: tmp, mode: 'http',
      onCall: (t) => {
        if (t === 'rename_project') { renames++; return { ok: true }; }
        if (t === 'update_project') return { ok: false, error: 'refused' };
        return { ok: true };
      },
    });
    retry.eval("select('acme'); openProject('4521');");
    retry.eval("document.getElementById('f_pno').value='9999';");
    await retry.eval("saveProject('4521')");
    await retry.eval("saveProject('4521')");        // the retry
    r.check('a committed rename is not re-sent on retry', renames === 1,
      `rename_project fired ${renames}x -- the second targets a number that is gone`);
    const targets = retry.calls().filter(c => c.tool === 'update_project')
      .map(c => String(c.args.project_no));
    r.check('the retry saves fields against the NEW number',
      targets.length === 2 && targets[1] === '9999',
      `update_project targeted: ${targets.join(',')}`);
  }

  // 15. THE DRAWER IS OUT OF THE TAB ORDER ON A FRESHLY LOADED PAGE. Every
  //     other inert assertion runs after closeDrawer(), which sets it itself,
  //     so the page-load initialiser had no coverage.
  {
    const fresh = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
    r.check('the drawer starts inert on a freshly loaded page',
      fresh.doc.getElementById('drawer').inert === true,
      'before anything is opened, Tab reaches the off-screen form');
  }

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

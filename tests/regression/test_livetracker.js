// The Live Tracker's SCREEN half: the landing view, the lateness flags, and
// adoption of a row that has no project number.
//
// This screen is the one he opens the app to look at, and almost everything on
// it is derived at render time rather than stored:
//
//  1. LATENESS IS COMPUTED AGAINST TODAY. A ship-date cell is a real date about
//     half the time; the rest are "EST 8/03/26", "US Pickup", or empty. Three
//     different things are late in three different ways and an empty one is
//     the worst of them -- it is the leg nobody is tracking. So the clock is
//     FROZEN below: a test whose expected answers drift with the wall clock
//     silently stops asserting anything the week after it is written.
//
//  2. ADOPTION WRITES A NEW PROJECT. It is the only path on this screen that
//     creates a record, and it refuses without BOTH a project number and a
//     customer. Not defensive padding: with no name match the browser selects
//     the FIRST option of a <select>, and that silently filed a tracker row
//     under an arbitrary company. One of the operator's companies is an address
//     string the importer read as a customer, so "the first one" is not even a
//     plausible company. There is no default; he chooses.
//
//  3. THE NOTE IS THE SUBSTANCE. It comes off an Excel cell a person typed, it
//     is never truncated, and it is therefore also the app's largest surface of
//     external text rendered into HTML.
//
// What this file does NOT verify is listed in the header of
// test_drawer_close.js and applies here too: no CSS layout, no tab order, no
// real focus. One shim limitation matters specifically here -- the DOM shim
// gives every <select> an empty value regardless of which <option> carries
// `selected`, so the preselect assertions below read the generated markup
// rather than el.value.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { launch, makeResult, buildBundle } = require('../lib/view.js');

const TODAY = '2026-08-09';

// A note long enough that any truncation shows, carrying the punctuation and
// newlines a person actually types into a spreadsheet cell.
// A DISTINCT long note per card type. The two cards are rendered by two
// different templates, and sharing one note let a truncation mutant in
// liveCard survive: the tail sentence was still on the page, from the unlinked
// card the mutant had not touched.
const LONG_NOTE = 'Two of the four frames short-shipped; supplier says the '
  + 'balance leaves their dock on the 14th.\nCustomer has been told the 21st '
  + 'so there is a week of float, but the crate cannot be built until all four '
  + 'are on site. Chase Tuesday if there is no tracking number by Monday.';
const LONG_NOTE_UNLINKED = 'Started off the back of the walkthrough, so there '
  + 'is no paperwork on it yet and no number.\nTwo vendor POs are already out '
  + 'against it. Needs a number before anything else can be filed under it.';
// External text from a spreadsheet cell, rendered into the page.
const XSS_NOTE = '<img src=x onerror="globalThis.__pwned=1">';

function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer',
      domains: [], locations: [], archived: false },
    { company_id: 'mer', display_name: 'Meridian Corp', role: 'customer',
      domains: [], locations: [], archived: false },
    { company_id: 'cob', display_name: 'Cobalt Freight', role: 'vendor',
      domains: [], locations: [], archived: false }]);
  w('projects', [
    // three late legs of three different kinds, plus the long note
    { company_id: 'acme', project_no: '4501', status: 'won', year: 2026,
      archived: false, tracker_status: 'action_admin', tracker_row: 2,
      date: '2026-07-01', open_orders_notes: LONG_NOTE },
    // no late leg, but a start date nobody has committed to
    { company_id: 'acme', project_no: '4502', status: 'won', year: 2026,
      archived: false, tracker_status: 'action_owner', tracker_row: 3,
      date: 'TBD', open_orders_notes: 'Waiting on the drawing sign-off.' },
    // clean: an unparseable but non-empty ship date is not lateness
    { company_id: 'mer', project_no: '4503', status: 'won', year: 2026,
      archived: false, tracker_status: 'awaiting_materials', tracker_row: 4,
      date: '2026-07-15', open_orders_notes: '' },
    // NOT on the tracker at all -- must not appear on this screen
    { company_id: 'mer', project_no: '4504', status: 'won', year: 2026,
      archived: false, open_orders_notes: 'Not a tracker row.' },
    // on the tracker but archived -- must not appear either
    { company_id: 'acme', project_no: '4505', status: 'won', year: 2026,
      archived: true, tracker_status: 'action_admin',
      open_orders_notes: 'Archived.' },
    // the note came off a spreadsheet cell somebody else can type into
    { company_id: 'mer', project_no: '4506', status: 'won', year: 2026,
      archived: false, tracker_status: 'action_admin', date: '2026-07-20',
      open_orders_notes: XSS_NOTE },
    // a status no bucket knows about. It was counted in the header and
    // rendered in no section at all, so a live job left the daily board.
    { company_id: 'acme', project_no: '4507', status: 'won', year: 2026,
      archived: false, tracker_status: 'done', date: '2026-07-02',
      open_orders_notes: 'Status the legend does not name.' },
    // NOTE: start_date is a shipment/unlinked-row field, not a project one --
    // it is absent from PROJECT_FIELDS, so no project can really carry it.
    // Seeded anyway because the store is read raw and the point is that the
    // card and the flags read the SAME expression; asserted directly below too.
    { company_id: 'acme', project_no: '4508', status: 'won', year: 2026,
      archived: false, tracker_status: 'action_owner', start_date: 'TBD',
      open_orders_notes: 'Start date lives on the other field.' },
    // every leg already delivered: nothing here needs a person today
    { company_id: 'mer', project_no: '4509', status: 'won', year: 2026,
      archived: false, tracker_status: 'awaiting_materials',
      date: '2026-06-01', open_orders_notes: 'Shipped and signed for.' }]);
  w('shipments', [
    { shipment_id: '4501-L1', company_id: 'acme', project_no: '4501',
      all_project_nos: ['4501'], vendor_po_raw: 'VPO-A (50% paid)',
      ship_date: '2026-07-20', stage: 'Ordered', linked_to_project: true },
    // a SECOND passed leg: the flag list must not say it twice
    { shipment_id: '4501-L2', company_id: 'acme', project_no: '4501',
      all_project_nos: ['4501'], vendor_po_raw: 'VPO-B',
      ship_date: '2026-07-22', stage: 'Ordered', linked_to_project: true },
    { shipment_id: '4501-L3', company_id: 'acme', project_no: '4501',
      all_project_nos: ['4501'], vendor_po_raw: 'VPO-C',
      ship_date: 'EST 7/25/26', stage: 'Ordered', linked_to_project: true },
    { shipment_id: '4501-L4', company_id: 'acme', project_no: '4501',
      all_project_nos: ['4501'], vendor_po_raw: 'VPO-D',
      ship_date: null, stage: 'Ordered', linked_to_project: true },
    // SAME project number, DIFFERENT company. Two customers can hold one
    // number; pulling this onto Ace's card is a leg on the wrong job.
    { shipment_id: 'x-4501-L1', company_id: 'mer', project_no: '4501',
      all_project_nos: ['4501'], vendor_po_raw: 'VPO-WRONG',
      ship_date: '2026-01-01', stage: 'Ordered', linked_to_project: true },
    { shipment_id: '4502-L1', company_id: 'acme', project_no: '4502',
      all_project_nos: ['4502'], vendor_po_raw: 'VPO-E',
      ship_date: '2026-12-01', stage: 'Ordered', linked_to_project: true },
    { shipment_id: '4503-L1', company_id: 'mer', project_no: '4503',
      all_project_nos: ['4503'], vendor_po_raw: 'VPO-F',
      ship_date: 'US Pickup', stage: 'Ordered', linked_to_project: true },
    { shipment_id: '4506-L1', company_id: 'mer', project_no: '4506',
      all_project_nos: ['4506'], vendor_po_raw: 'VPO-G',
      ship_date: '2026-11-01', stage: 'Ordered', linked_to_project: true },
    // long past its date, but it ARRIVED. list_shipments(overdue=True) has
    // always excluded these stages; the screen must agree or the same store
    // answers the same question two ways.
    { shipment_id: '4509-L1', company_id: 'mer', project_no: '4509',
      all_project_nos: ['4509'], vendor_po_raw: 'VPO-H',
      ship_date: '2026-01-05', stage: 'Delivered', linked_to_project: true },
    { shipment_id: '4509-L2', company_id: 'mer', project_no: '4509',
      all_project_nos: ['4509'], vendor_po_raw: 'VPO-I',
      ship_date: null, stage: 'Cancelled', linked_to_project: true }]);
  w('tracker_buckets', [
    // Long enough to be shortened for the sidebar, and carrying a '/' inside
    // the first 28 characters -- esc() inflates that to five characters, so
    // escaping before slicing cuts a different string and can sever an entity.
    { key: 'action_admin', label: 'Waiting on the office/front desk today',
      argb: 'FFFF00FF', legend_row: 17 },
    { key: 'action_owner', label: 'With the rep', argb: 'FFFFFF00',
      legend_row: 18 },
    // the sheet never named this one: it must still group, under its key
    { key: 'awaiting_materials', label: null, argb: 'FF00FFFF',
      legend_row: null }]);
  w('tracker_unlinked', [
    // A FALSY ENTRY, deliberately first. renderLiveMain filters these out
    // before numbering the cards while both handlers index the raw array, so
    // a leading null shifted every card: the first button went dead and every
    // later one adopted the PREVIOUS row's client, note, status and dates
    // under the number typed for the row that was clicked.
    null,
    // client matches a company EXACTLY -> the dropdown may preselect it
    { sheet_row: 7, reason: 'no project number', client: 'Meridian Corp',
      client_po: 'PO-7007', start_date: '2026-07-03', location: 'Dayton OH',
      open_orders_notes: LONG_NOTE_UNLINKED,
      tracker_status: 'awaiting_materials',
      legs: [{ vendor_po_raw: 'VPO-M1', ship_date: '2026-07-10' },
             { vendor_po_raw: 'VPO-M2', ship_date: null }] },
    // client matches NOTHING -> there must be no preselected company at all
    // start_date in a DIFFERENT year to the frozen clock (2026): the year
    // stamped from the adoption date and the year taken from the row are
    // otherwise the same number, and no assertion could tell them apart.
    { sheet_row: 8, reason: 'no matching project', raw_key: '1419',
      client: 'Northgate Tooling', client_po: 'PO-8008',
      start_date: '2025-12-28', location: 'Akron OH',
      open_orders_notes: 'Keyed 1419 on the sheet; the deal log calls it '
        + 'something else.', tracker_status: 'action_admin',
      legs: [{ vendor_po_raw: 'VPO-Z', ship_date: null }] },
    // client matches a VENDOR. The dropdown excludes vendors, so a preselect
    // here suppressed the "choose a customer" placeholder while leaving NO
    // option selected -- the browser then reported the first customer and the
    // guard passed on it, filing the job under a company nobody chose.
    { sheet_row: 10, reason: 'no project number', client: 'Cobalt Freight',
      client_po: 'PO-1010', start_date: '2026-07-08', location: 'Toledo OH',
      open_orders_notes: 'Freight job, no number.',
      tracker_status: 'action_owner', legs: [] }]);
  w('contacts', []); w('invoices', []); w('vendors', []); w('needs_review', []);
  return dir;
}

// Freeze the clock inside the bundle's own scope. todayISO() resolves `Date`
// from the global at call time, so replacing it here reaches every derived
// answer on the screen. Without this the lateness expectations below decay
// into "whatever today happens to make true".
function freezeClock(app, iso) {
  app.eval(`
    (function(){
      const Real = Date, fixed = Real.parse(${JSON.stringify(iso + 'T12:00:00Z')});
      function Frozen(...a){
        return a.length === 0 ? new Real(fixed) : new Real(...a);
      }
      Frozen.prototype = Real.prototype;
      Frozen.now = () => fixed;
      Frozen.UTC = Real.UTC;
      Frozen.parse = Real.parse;
      globalThis.Date = Frozen;
    })();
  `);
}

async function run(crmDir) {
  const r = makeResult('live-tracker/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmlt-'));
  const store = seedStore(path.join(tmp, 'store'));
  const { js, html } = buildBundle(crmDir, store, tmp);
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
  const ev = (code) => app.eval(code);
  freezeClock(app, TODAY);
  r.check('the frozen clock reaches the view', ev('todayISO()') === TODAY,
    `got ${ev('todayISO()')} -- every lateness answer below would drift`);

  // ---- the landing screen ---------------------------------------------------
  r.check('there is a Live tab', /data-f="live"/.test(html));
  r.check('Live is the tab that starts selected',
    /data-f="live" class="on"/.test(html),
    'the daily screen is the reason he opens the app');
  r.check('the app starts on the live filter', ev('filter') === 'live');
  // #main ships with "Select a company to begin."; a cross-company landing
  // view has to paint ITSELF as the bundle loads, because renderMain is
  // otherwise only reached by selecting a company or switching tabs. Read what
  // the bundle already did -- calling renderMain() here would make the check
  // below pass on a build that never paints.
  let main = app.doc.getElementById('main').innerHTML;
  r.check('the live view paints without a company being selected',
    /Live projects/.test(main) && !/Select a company to begin/.test(main),
    'renderMain is otherwise only reached by selecting a company');

  // A live refresh must repaint the CARDS, not just the sidebar. Asserted
  // against the generated source, not behaviour: lib/view.js stubs fetch with
  // a promise that never settles, so CRM.detect()/refreshData() cannot
  // complete under this harness at all. Naming the limitation rather than
  // writing a check that cannot fail.
  r.check('a live refresh repaints the main pane on the landing screen',
    /filter === 'live'\)\s*renderMain\(\);/.test(
      js.slice(js.indexOf('async function refreshData'),
               js.indexOf('async function refreshData') + 1400)),
    'the landing screen has no `selected`, so without this the sidebar '
    + 'repaints from the refreshed store while the cards beside it keep '
    + 'showing the build-time snapshot indefinitely');

  // ---- bucket labels come from the sheet ------------------------------------
  r.check('a bucket shows the name the legend gave it',
    ev("bucketLabel('action_admin')") === 'Waiting on the office/front desk today');
  r.check('a second one too',
    ev("bucketLabel('action_owner')") === 'With the rep');
  r.check('a bucket the legend never named falls back to its key',
    ev("bucketLabel('awaiting_materials')") === 'Awaiting materials',
    'showing nothing would hide a whole group of live work');
  r.check('the neutral key is never what he reads when a label exists',
    !/Action admin/.test(main),
    'the key is a storage detail; the legend is his own wording');
  r.check('with no legend at all, the three buckets still exist',
    ev("(function(){const b=DATA.tracker_buckets;DATA.tracker_buckets=[];"
       + "const n=trackerBuckets().length;DATA.tracker_buckets=b;return n})()")
    === 3,
    'a store seeded before the tracker shipped must not lose the grouping');

  // ---- what a ship-date cell means ------------------------------------------
  r.check('a date in the past is passed',
    ev("legDate('2026-07-20').kind") === 'passed');
  r.check('a date in the future is fine',
    ev("legDate('2026-12-01').kind") === 'ok');
  r.check('an EST that has come and gone is its own kind',
    ev("legDate('EST 7/25/26').kind") === 'est-passed',
    'an estimate that has passed is weaker news than a hard date that has');
  r.check('an EST still ahead is not late',
    ev("legDate('EST 12/25/26').kind") === 'ok');
  r.check('an empty cell is a leg with no date, not a date of nothing',
    ev("legDate('').kind") === 'none' && ev("legDate(null).kind") === 'none');
  r.check('unparseable text is shown as it stands',
    ev("legDate('US Pickup').kind") === 'text'
    && ev("legDate('US Pickup').text") === 'US Pickup',
    'inventing a date here is worse than admitting there is not one');
  r.check('a parsed date renders in the one house format',
    ev("legDate('2026-07-20').text") === '20 Jul 2026');

  // ---- the flags ------------------------------------------------------------
  const flags = (pno) => JSON.parse(ev(
    `JSON.stringify((liveRows().find(x=>String(x.p.project_no)==='${pno}')||{}).flags)`));
  const f4501 = flags('4501');
  r.check('a passed ship date is flagged', f4501.includes('ship date passed'));
  r.check('a passed EST is flagged separately', f4501.includes('EST passed'));
  r.check('a leg with no date is flagged', f4501.includes('leg with no date'),
    'the untracked leg is the one that goes wrong quietly');
  r.check('two passed legs produce ONE flag, not two',
    f4501.filter(x => x === 'ship date passed').length === 1,
    `got ${JSON.stringify(f4501)} -- a row with five late legs would wear five `
    + 'identical badges and read as noise');
  r.check('a TBD start date is flagged',
    JSON.stringify(flags('4502')) === JSON.stringify(['start TBD']),
    `got ${JSON.stringify(flags('4502'))}`);
  r.check('a clean row carries no flags',
    JSON.stringify(flags('4503')) === '[]',
    `got ${JSON.stringify(flags('4503'))} -- "US Pickup" is not a late date`);
  r.check('the most-flagged row sorts first',
    ev("String(liveRows()[0].p.project_no)") === '4501',
    'the screen exists to answer what needs a person today');

  // ---- a leg that has already arrived is not late ---------------------------
  r.check('a delivered leg past its date is not flagged',
    JSON.stringify(flags('4509')) === '[]',
    `got ${JSON.stringify(flags('4509'))} -- list_shipments(overdue=True) has `
    + 'always excluded Delivered/Installed/Cancelled, so a badge here means '
    + 'chat and the screen disagree about the same leg');
  r.check('and a cancelled leg with no date is not flagged either',
    !flags('4509').includes('leg with no date'),
    'it was cancelled; nobody is waiting on a date for it');
  const card4509 = (main.split('<div class="lt-card">')
    .find(c => c.includes('Shipped and signed for.')) || '');
  r.check("4509's card is on the page", !!card4509);
  r.check('a settled leg is not rendered as late either',
    !!card4509 && !card4509.includes('lt-bad'),
    'dropping the row badge while leaving the leg bold red says the same '
    + 'wrong thing in a quieter voice, and the leg is the line he reads');
  r.check('and it is still shown, not hidden',
    !!card4509 && card4509.includes('VPO-H'),
    'a delivered leg is still part of the job');
  r.check('a settled leg does not pin the row to the top of the screen',
    ev("String(liveRows()[liveRows().length-1].p.project_no)") !== '4501',
    'rows sort by flag count, so a permanent phantom flag is a permanent '
    + 'first place');

  // ---- the start date is read from one place, not two -----------------------
  r.check('a start date stored as start_date still flags TBD',
    flags('4508').includes('start TBD'));
  // Scoped to 4508's own card: the page has other cards that legitimately say
  // "no start date", so a page-wide regex passes whatever this one renders.
  const card4508 = (main.split('<div class="lt-card">')
    .find(c => c.includes('Start date lives on the other field')) || '');
  r.check("4508's card is actually on the page", !!card4508,
    'the check below is vacuous without it');
  // The invariant, independent of the fixture: whatever expression the flags
  // read for a start date, the card reads the same one. A fixture alone cannot
  // pin this, because the field it needs cannot exist on a real project.
  r.check('the card and the flags read the same start-date expression',
    (js.match(/p\.date\s*\|\|\s*p\.start_date/g) || []).length >= 2,
    'they disagreed once and a row wore a TBD badge while showing no start '
    + 'date at all');
  r.check('and it shows the start date rather than "no start date"',
    card4508.includes('TBD') && !card4508.includes('no start date'),
    'the flag read p.date || p.start_date and the card read p.date alone, so '
    + 'a row wore a TBD badge while showing no start date at all');

  // ---- who is on the screen at all ------------------------------------------
  const live = JSON.parse(ev("JSON.stringify(liveRows().map(x=>String(x.p.project_no)))"));
  r.check('a project with no tracker status is not live work',
    !live.includes('4504'), `got ${JSON.stringify(live)}`);
  r.check('an archived project is not live work either',
    !live.includes('4505'), `got ${JSON.stringify(live)}`);
  const legs4501 = JSON.parse(ev(
    "JSON.stringify(liveRows().find(x=>String(x.p.project_no)==='4501')"
    + ".legs.map(l=>l.vendor_po_raw))"));
  r.check('legs are matched on the company as well as the number',
    !legs4501.includes('VPO-WRONG') && legs4501.length === 4,
    `got ${JSON.stringify(legs4501)} -- two customers can hold one number`);

  // ---- every counted row is a row you can see -------------------------------
  // The single invariant that catches the whole bucket-drift class: the header
  // counts liveRows(), the sections render per known bucket, and a status no
  // bucket knows about used to fall between the two.
  const counted = ev('String(liveRows().length)');
  const cards = (main.match(/class="lt-card"/g) || []).length;
  r.check('the header count equals the number of cards on the page',
    String(cards) === counted,
    `header says ${counted} active, ${cards} cards rendered -- a row counted `
    + 'and not drawn is a live job that left the daily board silently');
  r.check('an unrecognised status gets its own section rather than vanishing',
    /Status not recognised/.test(main) &&
    main.indexOf('Status the legend does not name.') > -1,
    'it is live work; hiding it is worse than showing it under a heading that '
    + 'admits the tracker cannot name it');
  r.check('and it is still in the sidebar, as it always was',
    /4507/.test(app.doc.getElementById('clist').innerHTML),
    'the sidebar and the main pane disagreeing is the symptom');
  r.check('the sidebar does not dress it up as a real bucket',
    /status not recognised/.test(app.doc.getElementById('clist').innerHTML)
    && !/>Done</.test(app.doc.getElementById('clist').innerHTML),
    "bucketLabel's fallback title-cases the key, so 'done' read as \"Done\" "
    + 'beside a main pane saying the tracker cannot name it');

  // ---- the sidebar label ----------------------------------------------------
  // 'Waiting on the office/front ' is the first 28 characters; escaped, that
  // is 'Waiting on the office&#47;front '. Escaping FIRST and slicing after
  // gives 'Waiting on the office&#47;fr' -- visibly shorter, and one character
  // either way from leaving a half-written entity the browser prints raw.
  r.check('a bucket label is shortened before escaping, not after',
    app.doc.getElementById('clist').innerHTML
      .includes('Waiting on the office&#47;front'),
    `got ${(app.doc.getElementById('clist').innerHTML.match(/<span>Waiting[^<]*/) || ['none'])[0]}`
    + ' -- esc() inflates one character into five or six, so slicing after it '
    + 'cuts a different string and can sever an entity');

  // ---- the note -------------------------------------------------------------
  r.check('the note wraps rather than being clipped',
    /\.lt-note\{[^}]*white-space:pre-wrap/.test(html),
    'a one-line note box turns the substance of the screen into a tooltip');
  r.check('the whole note is on the page, not a prefix of it',
    main.indexOf('Chase Tuesday if there is no tracking number by Monday.') > -1,
    'truncation here drops the sentence that says what to do');
  r.check('an unlinked row is not truncated either',
    main.indexOf('Needs a number before anything else can be filed under it.') > -1,
    'the two cards are separate templates; clipping one is not clipping both');
  r.check('a project with no note says so rather than showing a gap',
    /no note/.test(main));
  r.check('a note from a spreadsheet cell is escaped, not executed',
    !/<img src=x onerror/.test(main) && /&lt;img src=x/.test(main),
    'the note is external text: anyone who can edit the workbook can edit it');
  r.check('and nothing in it ran', ev('typeof globalThis.__pwned') === 'undefined');

  // ---- unlinked rows are shown, in full -------------------------------------
  r.check('the unlinked section is on the screen',
    /Not in the CRM yet/.test(main),
    'a live job that exists only as a dangling leg is invisible work');
  r.check('every unlinked row is shown',
    ['7', '8', '10'].every(n => main.includes('tracker row ' + n)),
    'a live job that exists only as a dangling leg is invisible work');
  r.check('the falsy entry produces no card',
    !/tracker row undefined/.test(main) && !/tracker row null/.test(main));
  r.check('an unlinked row names its client',
    /Northgate Tooling/.test(main));
  r.check('an unlinked row keeps the key the sheet carried',
    /keyed 1419/.test(main),
    'it is how he recognises the row when he goes to give it a number');
  r.check('an unlinked row shows its note in full',
    main.indexOf('the deal log calls it something else.') > -1);
  r.check('each unlinked row offers adoption',
    (main.match(/openAdoptTrackerRow\(/g) || []).length === 3);
  // THE index check: the card for row 8 must carry the index that actually
  // reaches row 8 in the raw array, not its position after filtering.
  r.check('a card carries its index in the RAW array, not the filtered one',
    /tracker row 8[\s\S]{0,900}?openAdoptTrackerRow\(2\)/.test(main),
    'off-by-one here opens the previous row under the number typed for this '
    + 'one, which is a silently mis-filed project');
  r.check('and the first real card is not numbered zero',
    /tracker row 7[\s\S]{0,900}?openAdoptTrackerRow\(1\)/.test(main),
    'index 0 is the falsy entry; a card pointing there is a dead button');

  // Scope the preselect checks to the CUSTOMER select. The drawer now carries
  // a status select too, whose 'won' option is legitimately `selected`, so a
  // page-wide regex for a selected option answers about the wrong control.
  const cidSel = (h) => (h.match(/<select id="a_cid">[\s\S]*?<\/select>/) || [''])[0];
  // ---- adoption: no blind default -------------------------------------------
  ev('openAdoptTrackerRow(2);');           // Northgate -- matches no company
  let body = app.doc.getElementById('dbody').innerHTML;
  r.check('adopting opens the drawer',
    app.doc.getElementById('drawer').classList.contains('open'),
    'the same drawer every other editor uses');
  r.check('with no name match there is an explicit empty choice',
    /<option value="">— choose a customer —<\/option>/.test(body),
    'without it the browser selects the FIRST company and the row is filed '
    + 'under whatever happens to sort first');
  r.check('and it is the FIRST option, so nothing else can be preselected',
    /<select id="a_cid"><option value="">/.test(body),
    `got ${(body.match(/<select id="a_cid">.{0,60}/) || [''])[0]}`);
  r.check('no company is marked selected',
    !/<option value="[^"]*" selected>/.test(cidSel(body)));
  r.check('vendors are not offerable as the customer',
    !/Cobalt Freight/.test(body),
    'a vendor cannot be the customer on a project');
  r.check('the note comes into the form so it is not retyped',
    /Keyed 1419 on the sheet/.test(body));
  // A KEYED row's legs WERE imported -- under the sheet's own number, so they
  // will not follow the number chosen here.
  r.check("a keyed row's drawer says its legs stay on the old number",
    /were imported under the[\s\S]{0,60}1419/.test(body)
    && !/were NOT imported/.test(body),
    `got ${(body.match(/vendor leg\(s\)[\s\S]{0,140}/) || ['none'])[0]}`);

  // ---- a client name that matches a VENDOR ---------------------------------
  // The dropdown excludes vendors. If the guess does not, cid is truthy, the
  // placeholder is suppressed, the matched company is absent from the options
  // so nothing carries `selected`, and a real browser reports the FIRST
  // customer -- which the !cid guard then accepts. The shim cannot show that
  // (every select reads back empty), so this is asserted on the markup.
  ev('openAdoptTrackerRow(3);');           // Cobalt Freight -- a vendor
  body = app.doc.getElementById('dbody').innerHTML;
  r.check('a vendor name does not count as a customer guess',
    /<option value="">— choose a customer —<\/option>/.test(body),
    'suppressing the placeholder on a guess that cannot be offered is how the '
    + 'browser got to pick the company');
  r.check('and nothing is preselected',
    !/<option value="[^"]*" selected>/.test(cidSel(body)));
  r.check('the vendor is still not in the list',
    !/Cobalt Freight/.test(body));
  r.check('_slugGuess returns nothing for a vendor name',
    ev("_slugGuess('Cobalt Freight')") === '',
    'a guess that cannot be offered must not count as a guess');
  r.check('and still resolves a real customer',
    ev("_slugGuess('Meridian Corp')") === 'mer',
    'without this the check above passes on a guess that never works');

  // A NUMBERLESS row returns from the importer BEFORE the vendor loop, so its
  // legs exist nowhere. Telling him they are already in the CRM and not to
  // re-add them is the worse of the two errors: it suppresses the only action
  // that recovers them.
  ev('openAdoptTrackerRow(1);');           // Meridian -- no project number
  body = app.doc.getElementById('dbody').innerHTML;
  r.check("a numberless row's drawer says its legs were NOT imported",
    /were NOT imported/.test(body) && /Add them from the\s+project/.test(body),
    `got ${(body.match(/vendor leg\(s\)[\s\S]{0,160}/) || ['none'])[0]}`
    + " -- normalize's own review text says \"its shipment legs were not "
    + 'imported" for exactly this row');
  r.check('and does not claim they are already in the CRM',
    !/already in the CRM/.test(body));

  // back to the row the adoption checks below are about
  ev('openAdoptTrackerRow(2);');

  // refuses with no number. The customer IS filled in, so the number guard is
  // the only thing that can stop this write -- with both blank the check would
  // pass on a build that had lost the number guard entirely.
  app.resetCalls();
  ev("document.getElementById('a_pno').value='';");
  ev("document.getElementById('a_cid').value='mer';");
  await ev('saveAdoptTrackerRow(2)');
  r.check('adoption refuses with no project number',
    app.calls().length === 0,
    `got ${JSON.stringify(app.calls())} -- a project with no number cannot be `
    + 'opened, edited or found again');
  r.check('and says which field it wants',
    /project #/.test(app.doc.getElementById('savedMsg').textContent),
    `got ${app.doc.getElementById('savedMsg').textContent}`);

  // refuses with a number but no customer -- the case the browser hides
  ev("document.getElementById('a_pno').value='1500';");
  ev("document.getElementById('a_cid').value='';");
  await ev('saveAdoptTrackerRow(2)');
  r.check('adoption refuses with a number but no customer',
    app.calls().length === 0,
    'this is the one that silently filed a row under an arbitrary company');
  r.check('and says so',
    /customer/.test(app.doc.getElementById('savedMsg').textContent));

  // ---- adoption: the happy path ---------------------------------------------
  // The note is assigned explicitly: the DOM shim only reads a `value="..."`
  // attribute, and a <textarea> carries its content between the tags, so it
  // reads back empty here where a browser would hand over the prefilled text.
  // The prefill itself is asserted against the generated markup above.
  ev("document.getElementById('a_pno').value='1500';");
  ev("document.getElementById('a_cid').value='mer';");
  ev("document.getElementById('a_note').value="
     + JSON.stringify('Keyed 1419 on the sheet; edited before adopting.') + ";");
  ev("document.getElementById('a_status').value='pending';");
  await ev('saveAdoptTrackerRow(2)');
  const calls = app.calls();
  r.check('with both, exactly one write is made', calls.length === 1,
    `got ${JSON.stringify(calls)}`);
  if (calls.length === 1) {
    const c = calls[0];
    r.check('adoption goes through create_project like everything else',
      c.tool === 'create_project',
      `got ${c.tool} -- a private path here is one more thing to keep in step`);
    const f = (c.args && c.args.fields) || {};
    r.check('it writes the number he typed', String(f.project_no) === '1500');
    r.check('and the customer he chose', f.company_id === 'mer');
    r.check('the tracker status comes across',
      f.tracker_status === 'action_admin',
      'without it the adopted row drops off the screen it came from');
    r.check('the note as edited in the form is what gets written',
      String(f.open_orders_notes) === 'Keyed 1419 on the sheet; edited before '
        + 'adopting.',
      `got ${JSON.stringify(f.open_orders_notes)} -- reading the stored row `
      + 'instead of the form would throw away his edit');
    r.check('the start date comes across', f.date === '2025-12-28');
    r.check('the year is the one the WORK is in, not the adoption date',
      String(f.year) === '2025',
      `got ${JSON.stringify(f.year)} -- the clock is frozen at 2026-08-09, so `
      + 'stamping the adoption year files a December job under the wrong year '
      + 'on every annual figure');
    r.check('the status is the one he chose, not an assumed win',
      f.status === 'pending',
      `got ${JSON.stringify(f.status)} -- every adopted row used to count as a `
      + '$0 win in the Won revenue KPI');
    r.check('no synthetic key is smuggled in as the number',
      String(f.project_no) !== '1419',
      'the sheet key is shown to him, never written as the CRM key');
    r.check('the sheet row it came from is recorded on the project',
      String(f.tracker_row) === '8',
      `got ${JSON.stringify(f.tracker_row)} -- a numberless row has no key to `
      + 'match on, so this plus the note is the only way the next import knows '
      + 'the row is already a project and stops re-offering it for adoption');
  }
  r.check('the adopted row stops being offered for adoption',
    ev("String(arr(DATA.tracker_unlinked).filter(u=>u).map(u=>u.sheet_row))")
      === '7,10',
    `got ${ev("String(arr(DATA.tracker_unlinked).filter(u=>u).map(u=>u.sheet_row))")}`
    + ' -- leaving it there invites a second project for the same job');
  r.check('and the new project is on the screen',
    ev("liveRows().some(x=>String(x.p.project_no)==='1500')"),
    'it was adopted so it can be worked from here');
  r.check('the drawer closed behind the save',
    !app.doc.getElementById('drawer').classList.contains('open'));

  // a matching client name may preselect -- but only preselect
  ev('openAdoptTrackerRow(1);');
  body = app.doc.getElementById('dbody').innerHTML;
  r.check('an exactly-matching client is preselected',
    /<option value="mer" selected>/.test(cidSel(body)),
    'a correct guess saves a click; it is still shown before anything is written');
  r.check('a preselected match still lists the other customers',
    /<option value="acme"/.test(cidSel(body)),
    'a wrong guess must cost one click, not a wrong record');

  // ---- a row that is no longer there ---------------------------------------
  app.resetCalls();
  ev("document.getElementById('a_pno').value='1600';");
  ev("document.getElementById('a_cid').value='mer';");
  let missingErr = '';
  // Catch rather than let it propagate: an uncaught throw here kills the
  // module before it prints a verdict, and the mutation runner reads that as
  // "crashed, not a kill" -- correctly. The assertion has to survive the bug
  // it is testing for.
  try { await ev('saveAdoptTrackerRow(0)'); } catch (e) { missingErr = String(e).slice(0, 160); }
  r.check('saving against a missing row does not throw', !missingErr, missingErr);
  r.check('saving against a missing row writes nothing',
    app.calls().length === 0,
    'it used to create a project with no status, no start date and no '
    + 'location -- which then would not appear on the screen it was adopted '
    + 'into, while the card it came from stayed put');
  r.check('and says so rather than failing silently',
    /no longer on the list/.test(app.doc.getElementById('savedMsg').textContent),
    `got ${app.doc.getElementById('savedMsg').textContent}`);

  // ---- legs stored as something other than a list --------------------------
  //
  // In its OWN store, launched inside a try/catch. The landing screen renders
  // during the bundle's own startup, so a throw in unlinkedCard kills the
  // module before it can print a verdict -- which the mutation runner scores
  // as "crashed, not a kill", correctly. An assertion has to survive the bug
  // it is testing for.
  const legsDir = path.join(tmp, 'store-legs');
  fs.cpSync(store, legsDir, { recursive: true });
  fs.writeFileSync(path.join(legsDir, 'tracker_unlinked.json'), JSON.stringify([
    { sheet_row: 11, reason: 'no project number', client: 'Harbour Plate',
      client_po: 'PO-1111', open_orders_notes: 'Legs came back as a string.',
      tracker_status: 'action_owner', legs: 'VPO-Q' }]));
  let legsErr = '', legsApp = null;
  try {
    legsApp = launch({ crmDir, storeDir: legsDir, outDir: tmp, mode: 'http' });
  } catch (e) { legsErr = String(e).slice(0, 200); }
  r.check('a row whose legs are a string does not kill the page', !legsErr,
    legsErr + ' -- renderMain re-runs after EVERY save, so one malformed row '
    + 'would blank the whole screen on the next thing he does');
  if (legsApp) {
    r.check('and its card is rendered rather than the pane being blank',
      /tracker row 11/.test(legsApp.doc.getElementById('main').innerHTML),
      'every other list-shaped field in this app goes through arr() for '
      + 'exactly this reason');
  }

  // ---- the note finally has an editor, where the screen shows it -----------
  ev("openProject('4501');");
  const pbody = app.doc.getElementById('dbody').innerHTML;
  r.check('the project drawer has a box for the job-level note',
    /id="f_oon"/.test(pbody),
    'the Live card shows this note and nothing could edit it: the only '
    + 'writable copy was the shipment drawer\'s, a different field on a '
    + 'different record, so he edited it, saw "Saved", and the card did not '
    + 'change');
  r.check('and it is prefilled with the note the card shows',
    pbody.indexOf('Chase Tuesday if there is no tracking number by Monday.') > -1,
    'a note he has to retype is a note he will not edit');
  r.check('the form says which of the two notes this is',
    /separate "Order notes" box/.test(pbody),
    'two fields called notes on two records is how the confusion started');

  app.resetCalls();
  // No slash in this note ON PURPOSE: esc() renders "/" as "&#47;", so a
  // raw-string search for "8/8" fails on a page that is rendering it correctly.
  ev("document.getElementById('f_oon').value='Frames landed on the 8th, crating Monday.';");
  await ev("saveProject('4501')");
  const upd = app.calls().find(c => c.tool === 'update_project');
  r.check('saving the project sends the job-level note', !!upd
    && upd.args.fields.open_orders_notes === 'Frames landed on the 8th, crating Monday.',
    `got ${JSON.stringify(upd && upd.args.fields.open_orders_notes)}`);
  r.check('and it is a real edit when cleared, not "never set"',
    !!upd && typeof upd.args.fields.open_orders_notes === 'string',
    'null would read as unset and the next re-import would put the sheet\'s '
    + 'text back over a deliberate deletion');
  app.resetCalls();
  ev("openProject('4501');");
  ev("document.getElementById('f_oon').value='';");
  await ev("saveProject('4501')");
  const cleared = app.calls().find(c => c.tool === 'update_project');
  r.check('clearing the note sends an empty string, not null',
    !!cleared && cleared.args.fields.open_orders_notes === '',
    `got ${JSON.stringify(cleared && cleared.args.fields.open_orders_notes)} -- `
    + 'null reads as "never set", so the next re-import would put the sheet\'s '
    + 'text back over a deliberate deletion');
  ev("openProject('4501');");
  ev("document.getElementById('f_oon').value='Frames landed on the 8th, crating Monday.';");
  await ev("saveProject('4501')");

  ev("closeDrawer();");
  ev("setFilter('live');");
  main = app.doc.getElementById('main').innerHTML;
  r.check('the Live card shows the edited note straight away',
    main.indexOf('Frames landed on the 8th, crating Monday.') > -1,
    'the point of putting the editor here is that the card is the thing that '
    + 'changes');

  // ---- search works on the screen the app opens on -------------------------
  ev("query='meridian'; renderList(); renderMain();");
  const q1 = app.doc.getElementById('main').innerHTML;
  r.check('searching narrows the live cards',
    !/4501/.test(q1) && /4503/.test(q1),
    'the box promising "Search companies, contacts, projects..." sat on the '
    + 'landing screen doing nothing, then silently filtered the company list '
    + 'the moment he clicked All');
  r.check('and narrows the unlinked rows by client too',
    /tracker row 7/.test(q1) && !/Northgate Tooling/.test(q1),
    `got ${(q1.match(/tracker row \d+/g) || []).join(',')}`);
  ev("query='drawing sign-off'; renderList(); renderMain();");
  const q2 = app.doc.getElementById('main').innerHTML;
  r.check('searching matches the note, not just the number and customer',
    /4502/.test(q2) && !/4501/.test(q2),
    'the note is the substance of this screen; a search that cannot reach it '
    + 'misses the thing he is actually looking for');
  ev("query='no-such-thing'; renderList(); renderMain();");
  r.check('a search that matches nothing empties the screen honestly',
    /No live projects yet/.test(app.doc.getElementById('main').innerHTML));
  ev("query=''; renderList(); renderMain();");
  main = app.doc.getElementById('main').innerHTML;
  r.check('clearing the search brings everything back',
    /4501/.test(main) && /tracker row 7/.test(main) && /tracker row 10/.test(main),
    'row 8 is legitimately absent by now -- it was adopted earlier in this run');
  r.check('typing in the box repaints the cards, not only the sidebar',
    /filter === 'project' \|\| filter === 'live'\) renderMain\(\);/.test(js),
    'renderList alone leaves the main pane on the unfiltered set');

  // ---- adoption stops inventing a status and a year ------------------------
  ev('openAdoptTrackerRow(1);');            // Meridian, start_date 2026-07-03
  const abody = app.doc.getElementById('dbody').innerHTML;
  r.check('adoption asks for the status rather than assuming won',
    /id="a_status"/.test(abody),
    'every adopted row counted as a $0 win in the Won revenue KPI');
  r.check('the year defaults to the one the sheet\'s start date is in',
    /id="a_year"[^>]*value="2026"/.test(abody),
    `got ${(abody.match(/id="a_year"[^>]*/) || ['none'])[0]} -- it used the `
    + 'year of the ADOPTION, so a job started in December and adopted in '
    + 'January landed in the wrong year on every annual figure');
  r.check('_adoptYear reads the start date, not the clock',
    ev("String(_adoptYear({start_date:'12/28/2025'}))") === '2025',
    'this is the case that motivated it');
  r.check('and falls back to this year when the row has no start date',
    ev("String(_adoptYear({}))") === '2026');

  // ---- leaving the screen ---------------------------------------------------
  ev("select('acme');");
  r.check('selecting a company leaves the live view', ev('filter') === 'all',
    'staying would leave the main pane on the tracker while the sidebar '
    + 'says otherwise');
  r.check('and lands on that company', ev('selected') === 'acme');

  // ---- a tracker file of the wrong SHAPE must not kill the app --------------
  //
  // Valid JSON, wrong type. The archived-company scrub iterates four store
  // files and would raise on a dict, failing the build safely -- the two
  // tracker files are not in that loop, so a `{}` sailed into the page and
  // threw at the bundle's very first statement. The operator got an empty
  // sidebar, "Select a company to begin.", and a mode pill stuck on
  // "Connecting..." forever: no error, no clue, every edit impossible.
  const bad = path.join(tmp, 'store-bad');
  fs.cpSync(store, bad, { recursive: true });
  fs.writeFileSync(path.join(bad, 'tracker_unlinked.json'), '{}');
  fs.writeFileSync(path.join(bad, 'tracker_buckets.json'), '"not a list"');
  let badErr = '';
  let badApp = null;
  try {
    badApp = launch({ crmDir, storeDir: bad, outDir: tmp, mode: 'http' });
  } catch (e) { badErr = String(e).slice(0, 200); }
  r.check('the app still loads with a malformed tracker file', !badErr, badErr);
  if (badApp) {
    r.check('and the live screen still paints',
      /Live projects/.test(badApp.doc.getElementById('main').innerHTML),
      'a throw at the first statement leaves the whole app dead, not just '
      + 'this screen');
    r.check('the linked live rows are all still there',
      badApp.eval('String(liveRows().length)') === counted,
      'a bad unlinked file must not cost him the rows that were fine');
  }

  // ---- archiving a customer hides its unlinked row too ---------------------
  //
  // The scrub filters four store files by company_id. tracker_unlinked rows
  // carry the sheet's raw client NAME instead -- that is exactly why they are
  // unlinked -- so an archived customer kept its name and its full note on the
  // Live screen, under an "Add to CRM" button. Archiving is this product's
  // delete.
  const archDir = path.join(tmp, 'store-arch');
  fs.cpSync(store, archDir, { recursive: true });
  const cos = JSON.parse(fs.readFileSync(path.join(archDir, 'companies.json'), 'utf8'));
  cos.find(c => c.company_id === 'mer').archived = true;
  fs.writeFileSync(path.join(archDir, 'companies.json'), JSON.stringify(cos));
  const archApp = launch({ crmDir, storeDir: archDir, outDir: tmp, mode: 'http' });
  const archMain = archApp.doc.getElementById('main').innerHTML;
  r.check("an archived customer's unlinked row is gone from the screen",
    !/tracker row 7/.test(archMain),
    'it rendered their name and their note after they had been archived');
  r.check('and its note went with it',
    archMain.indexOf('Needs a number before anything else') === -1);
  r.check('a live customer\'s unlinked row is untouched',
    /tracker row 8/.test(archMain),
    'the filter must hide one company, not the section');
  r.check('the match is on the name, since that is all the row carries',
    archApp.eval("String(arr(DATA.tracker_unlinked).filter(u=>u).length)") === '2',
    'Meridian Corp is archived; the other two rows name nobody archived');

  // ---- the main pane caps like every sibling list, and says so -------------
  const bigDir = path.join(tmp, 'store-big');
  fs.cpSync(store, bigDir, { recursive: true });
  const many = [];
  for (let i = 0; i < 430; i++) {
    many.push({ company_id: 'acme', project_no: 'B' + i, status: 'won',
      year: 2026, archived: false, tracker_status: 'action_admin',
      date: '2026-07-01', open_orders_notes: 'bulk row ' + i });
  }
  fs.writeFileSync(path.join(bigDir, 'projects.json'), JSON.stringify(many));
  fs.writeFileSync(path.join(bigDir, 'shipments.json'), '[]');
  fs.writeFileSync(path.join(bigDir, 'tracker_unlinked.json'), '[]');
  const bigApp = launch({ crmDir, storeDir: bigDir, outDir: tmp, mode: 'http' });
  const bigMain = bigApp.doc.getElementById('main').innerHTML;
  r.check('the main pane stops at the same 400 its siblings use',
    (bigMain.match(/class="lt-card"/g) || []).length === 400,
    `got ${(bigMain.match(/class="lt-card"/g) || []).length} cards -- this is `
    + 'the operator\'s own sheet, and a week where he colours the whole table '
    + 'renders every card with every leg');
  r.check('and SAYS it capped, rather than looking like all the work there is',
    /Showing\s+the first 400 of 430/.test(bigMain),
    'a silent truncation on the daily screen reads as "that is everything"');
  r.check('the header still counts them all',
    /430 active/.test(bigMain),
    'the count is what tells him the list is longer than the page');

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

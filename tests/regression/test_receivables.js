// The Receivables view: the money arithmetic, and the parts of it that can be
// silently wrong.
//
// This screen answers "who owes me, and how late". Every number on it is
// derived rather than stored, which is a new class of risk for this app:
//
//  1. OUTSTANDING IS COMPUTED, NOT READ. An invoice carries no amount -- the
//     value lives on the linked project, and "partial:30%" means 30% has been
//     RECEIVED. Reading that percentage the other way round understates every
//     part-paid receivable, and the number still looks plausible.
//
//  2. A MISSING AMOUNT MUST NOT BECOME ZERO. One real invoice in the operator's
//     store has no project link and therefore no amount anywhere. Counting it
//     as $0 drops it out of the total silently -- and it is the oldest debt he
//     has. It must appear in the list and be named in the total's caveat.
//
//  3. TWO PLACES NOW DECIDE "IS THIS OVERDUE". The company page and this view
//     share invoiceBucket() for exactly that reason. A copy that drifted would
//     have the same store answering the same question two ways.
//
// What this file does NOT verify is listed in the header of
// test_drawer_close.js and applies here too: no CSS, no tab order, no real
// focus. Assertions below are about values and wiring.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { launch, makeResult, buildBundle } = require('../lib/view.js');

function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer',
      domains: [], locations: [], archived: false },
    { company_id: 'mer', display_name: 'Meridian Corp', role: 'customer',
      domains: [], locations: [], archived: false }]);
  w('projects', [
    { company_id: 'acme', project_no: '4521', status: 'won', year: 2026,
      revenue: 128000, collection_status: 'partial:30%', archived: false },
    { company_id: 'acme', project_no: '4522', status: 'won', year: 2026,
      revenue: 46500, collection_status: 'paid', archived: false },
    { company_id: 'mer', project_no: '4600', status: 'won', year: 2026,
      revenue: 83000, collection_status: 'open', archived: false },
    // deliberately revenue-less: a project can exist with no figure yet
    { company_id: 'mer', project_no: '4602', status: 'won', year: 2026,
      revenue: null, collection_status: 'open', archived: false }]);
  w('invoices', [
    { company_id: 'acme', invoice_no: '7001', project_no: '4521',
      payment_status: 'partial:30%', invoice_date: '2026-06-09',
      payment_notes: '30% deposit received 5/2' },
    { company_id: 'acme', invoice_no: '7002', project_no: '4522',
      payment_status: 'paid', invoice_date: '2026-06-19' },
    { company_id: 'mer', invoice_no: '7003', project_no: '4600',
      payment_status: 'open', invoice_date: '2026-06-14' },
    // no project link at all -> no amount exists anywhere for it
    { company_id: 'mer', invoice_no: '7004', project_no: null,
      payment_status: 'open', invoice_date: '3/14/2026' },
    // linked to a project that has no revenue -> also no amount
    { company_id: 'mer', invoice_no: '7005', project_no: '4602',
      payment_status: 'open', invoice_date: '2026-06-01' }]);
  w('contacts', []); w('shipments', []); w('vendors', []); w('needs_review', []);
  return dir;
}

function run(crmDir) {
  const r = makeResult('receivables');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmrecv-'));
  const store = seedStore(path.join(tmp, 'store'));
  const { js, html } = buildBundle(crmDir, store, tmp);
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
  const ev = (code) => app.eval(code);

  // ---- the shared definition -----------------------------------------------
  r.check('the receivables filter button exists', /data-f="receivable"/.test(html));
  r.check('only ONE definition of the overdue bucket',
    (js.match(/function invoiceBucket\s*\(/g) || []).length === 1);
  r.check('the company page uses the shared bucket, not its own copy',
    /const bucketOf = \(v\)=> invoiceBucket\(/.test(js),
    'a second inline copy is the same store answering one question two ways');

  // ---- outstanding arithmetic ----------------------------------------------
  // 30% received on $128,000 -> $89,600 still to collect
  r.check('a part-paid invoice counts only its remainder',
    ev("String(outstanding(DATA.invoices.find(i=>String(i.invoice_no)==='7001')))") === '89600',
    'reading the percentage as UNPAID would give 38400 and look plausible');
  r.check('a paid invoice owes nothing',
    ev("String(outstanding(DATA.invoices.find(i=>String(i.invoice_no)==='7002')))") === '0');
  r.check('an open invoice owes the full amount',
    ev("String(outstanding(DATA.invoices.find(i=>String(i.invoice_no)==='7003')))") === '83000');
  r.check('an unlinked invoice has NO amount, not zero',
    ev("String(outstanding(DATA.invoices.find(i=>String(i.invoice_no)==='7004')))") === 'null',
    'zero would silently drop the oldest debt out of the total');
  r.check('a linked project with no revenue also has no amount',
    ev("String(outstanding(DATA.invoices.find(i=>String(i.invoice_no)==='7005')))") === 'null');

  // an amount must belong to THIS company's project of that number
  r.check('the amount is matched on company as well as project number',
    /String\(x\.project_no\) === String\(pno\)[\s\S]{0,80}company_id/.test(js),
    'two customers can hold the same project number');

  // ---- bucketing and lateness ----------------------------------------------
  ev("__t='2026-08-07';");
  r.check('overdue is measured against the due date',
    ev("invoiceBucket(DATA.invoices.find(i=>String(i.invoice_no)==='7001'),'2026-08-07','2026-08-14')") === 'Overdue');
  r.check('a paid invoice is never overdue',
    ev("invoiceBucket(DATA.invoices.find(i=>String(i.invoice_no)==='7002'),'2026-08-07','2026-08-14')") === 'Paid');
  r.check('not-yet-due lands in Due later',
    ev("invoiceBucket({payment_status:'open',invoice_date:'2026-08-01'},'2026-08-07','2026-08-14')") === 'Due later',
    'Net 30 from 1 Aug is 31 Aug, which is past the 7-day window');
  r.check('due inside the week is its own bucket',
    ev("invoiceBucket({payment_status:'open',due_on:'2026-08-10'},'2026-08-07','2026-08-14')") === 'Due this week');
  r.check('an unreadable date is No due date, not overdue',
    ev("invoiceBucket({payment_status:'open',invoice_date:'not a date'},'2026-08-07','2026-08-14')") === 'No due date',
    'a 1970 fallback would put junk at the top of the chase list');

  // fmtDate is asserted directly: in this view it only ever receives a computed
  // ISO due date, so its unparseable branch is unreachable from the table --
  // but the helper is used wherever a stored date is shown, and a stored date
  // that cannot be parsed is exactly the case that must not vanish.
  r.check('fmtDate renders ISO readably', ev("fmtDate('2026-04-13')") === '13 Apr 2026');
  r.check('fmtDate renders the tracker format the same way',
    ev("fmtDate('3/14/2026')") === '14 Mar 2026',
    'the whole point is one format in the column');
  r.check('fmtDate shows an unreadable date AS STORED, not blank',
    ev("fmtDate('TBD on PO')") === 'TBD on PO',
    'blanking it hides that a real value is there and is unusable');
  r.check('fmtDate leaves an empty value empty', ev("fmtDate(null)") === '');
  r.check('fmtDate does not invent a day from a bad calendar date',
    ev("fmtDate('2/30/2026')") === '2/30/2026',
    '30 Feb must not silently become 2 Mar');

  r.check('days late counts whole days',
    ev("String(daysLate(DATA.invoices.find(i=>String(i.invoice_no)==='7001'),'2026-08-07'))") === '29');
  r.check('the tracker-format invoice is dated correctly, not in 1970',
    ev("String(daysLate(DATA.invoices.find(i=>String(i.invoice_no)==='7004'),'2026-08-07'))") === '116',
    '3/14/2026 must parse as March 2026');
  r.check('a future due date is not negative-late',
    ev("String(daysLate({due_on:'2026-12-01'},'2026-08-07'))") === '0');

  // ---- the rendered view ---------------------------------------------------
  ev("setFilter('receivable');");
  r.check('the view renders', /Receivables/.test(app.doc.getElementById('main').innerHTML));
  r.check('it opens on Overdue', ev('recvBucket') === 'Overdue',
    'the point of the screen is what is late');

  const rows = JSON.parse(ev("JSON.stringify(recvRows().map(r=>String(r.v.invoice_no)))"));
  r.check('overdue rows are oldest debt first',
    JSON.stringify(rows) === JSON.stringify(['7004', '7005', '7001', '7003']),
    `got ${JSON.stringify(rows)}`);

  const total = ev("String(recvRows().filter(r=>r.owed!=null).reduce((a,r)=>a+r.owed,0))");
  r.check('the total sums only what has an amount', total === '172600', `got ${total}`);

  const main = app.doc.getElementById('main').innerHTML;
  r.check('the total names what it excludes', /excludes 2 invoices with no amount on file/.test(main),
    'a receivables figure that quietly drops rows is worse than none');
  r.check('an invoice with no project is marked, not blank',
    /Not linked/.test(main));
  r.check('dates render in one readable format', /13 Apr 2026/.test(main),
    'the store holds 3/14/2026 and 2026-06-09; the column must not show both shapes');
  r.check('a part-paid status reads as part paid', /Part paid 30%/.test(main),
    'partial:30% is a stored value, not a label for a person');

  // ---- bucket switching ----------------------------------------------------
  ev("setRecvBucket('Paid');");
  const paid = JSON.parse(ev("JSON.stringify(recvRows().map(r=>String(r.v.invoice_no)))"));
  r.check('the Paid bucket shows the paid invoice',
    JSON.stringify(paid) === JSON.stringify(['7002']), `got ${JSON.stringify(paid)}`);
  r.check('counts are per bucket',
    ev("String(recvCount('Overdue'))") === '4' && ev("String(recvCount('Paid'))") === '1');
  ev("setRecvBucket('Overdue');");

  // ---- leaving the view ----------------------------------------------------
  ev("select('acme');");
  r.check('selecting a company leaves the receivables view', ev('filter') === 'all',
    'staying would leave the main pane on the list while the sidebar says otherwise');
  r.check('and lands on that company', ev('selected') === 'acme');

  // ---- the KPI goes somewhere ---------------------------------------------
  r.check('the receivables KPI is a control',
    /class="kpi go"[^>]*onclick="setFilter\('receivable'\)"/.test(app.doc.getElementById('kpis').innerHTML),
    'the number he opens the app for should be the one that navigates');
  r.check('and is reachable by keyboard',
    /tabindex="0"[\s\S]{0,200}onkeydown=/.test(app.doc.getElementById('kpis').innerHTML));

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

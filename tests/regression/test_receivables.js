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

async function run(crmDir) {
  const r = makeResult('receivables');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmrecv-'));
  const store = seedStore(path.join(tmp, 'store'));
  const { js, html } = buildBundle(crmDir, store, tmp);
  const app = launch({ crmDir, storeDir: store, outDir: tmp, mode: 'http' });
  const ev = (code) => app.eval(code);

  // ---- the shared definition -----------------------------------------------
  r.check('the receivables filter button exists', /data-f="receivable"/.test(html));
  // SOURCE CHECK, and not executable by construction: "there is exactly ONE
  // definition of this function" is a claim about the file, and both copies
  // would answer identically until the day someone edits one of them -- which
  // is precisely the failure it guards.
  // CAN detect: a second inline copy of the bucket rule appearing.
  // CANNOT detect: whether the one definition is correct. The behavioural half
  // is the bucket assertions further down, which do execute.
  r.check('only ONE definition of the overdue bucket (SOURCE CHECK)',
    (js.match(/function invoiceBucket\s*\(/g) || []).length === 1);
  // SOURCE CHECK, same DRY claim as above: two spellings agree on every input
  // until one is edited, and that divergence is the defect.
  r.check('the company page uses the shared bucket, not its own copy (SOURCE CHECK)',
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

  // an amount must belong to THIS company's project of that number.
  // EXECUTED: the grep that stood here matched an expression in the bundle and
  // would have passed on any rewrite that kept those two tokens near each
  // other, however it combined them.
  {
    const dupDir = path.join(tmp, 'store-dupno');
    fs.cpSync(store, dupDir, { recursive: true });
    fs.writeFileSync(path.join(dupDir, 'companies.json'), JSON.stringify([
      { company_id: 'acme', display_name: 'Ace', role: 'customer', archived: false },
      { company_id: 'beta', display_name: 'Beta', role: 'customer', archived: false }]));
    // SAME project number under two different customers, different revenue
    // BETA FIRST, deliberately. DATA.projects.find returns the first match, so
    // with acme first the guard could be deleted and the check would still
    // pass -- it would be finding the right revenue by accident of ordering.
    fs.writeFileSync(path.join(dupDir, 'projects.json'), JSON.stringify([
      { company_id: 'beta', project_no: '900', status: 'won', year: 2026,
        archived: false, revenue: 9000 },
      { company_id: 'acme', project_no: '900', status: 'won', year: 2026,
        archived: false, revenue: 1000 }]));
    fs.writeFileSync(path.join(dupDir, 'invoices.json'), JSON.stringify([
      { company_id: 'acme', invoice_no: 'I-900', project_no: '900',
        payment_status: 'open', invoice_date: '2026-01-05' }]));
    fs.writeFileSync(path.join(dupDir, 'shipments.json'), '[]');
    const dupApp = launch({ crmDir, storeDir: dupDir, outDir: tmp, mode: 'http' });
    dupApp.eval("setFilter('receivable'); renderMain();");
    const dupMain = dupApp.el('main').innerHTML || '';
    r.check('an amount comes from THIS company\'s project of that number',
      /1,000/.test(dupMain) && !/9,000/.test(dupMain),
      `got ${(dupMain.match(/[\d,]{3,}/g) || []).join(' ')} -- two customers `
      + 'can hold the same project number, and pricing an invoice from the '
      + "wrong one bills Ace for Beta's job");
  }

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

  // ---- the tile and the header read the SERVER's shape (0.1.36) -----------
  //
  // Before this the tile summed projects with a collection status filled in
  // (8 of 261 in the real store) and read as the receivables. Now both
  // surfaces read company.metrics.exposure_open_receivable_usd -- embedded at
  // build time by mcp/server.py's own builder and refreshed from
  // list_companies -- and say beside the figure how many invoices they could
  // price. In this fixture: acme 89,600 (7001 at 30% received) + 0 (7002 paid)
  // over 2 of 2; mer 83,000 over 1 of 3, one unlinked, one unpriced. Ledger:
  // 172,600 across 3 of 5.
  ev("kpis();");
  const kpi = app.doc.getElementById('kpis').innerHTML;
  r.check('the tile shows the server\'s ledger exposure, net of part-payments',
    kpi.includes('172,600'), `tile reads: ${kpi.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,200)}`);
  r.check('and says how many invoices it could price, beside the figure',
    /3 of 5 invoices priced/.test(kpi),
    'a figure without its denominator is the defect this release exists for');
  r.check('the tile no longer sums projects by collection status',
    !kpi.includes('211,000') && !kpi.includes('128,000'),
    '128000 (partial) + 83000 (open) is the old project-based figure');
  r.check('ledgerExposure adds shapes; it prices nothing itself (SOURCE CHECK)',
    !/function ledgerExposure[\s\S]{0,1200}(outstanding|invoiceAmount)\(/.test(js),
    'a second pricing rule in the view is how two figures on one screen disagree');
  const led = JSON.parse(ev("JSON.stringify(ledgerExposure())"));
  r.check('the ledger tally is additive: counted + excluded == population',
    led && led.counted + Object.values(led.excluded).reduce((a,b)=>a+b,0) === led.population
      && led.population === 5 && led.counted === 3,
    JSON.stringify(led));
  r.check('and names the exclusions by reason',
    led && led.excluded.no_project_link === 1 && led.excluded.no_revenue_on_project === 1,
    JSON.stringify(led && led.excluded));
  ev("setFilter('receivable');");
  const headHtml = app.doc.getElementById('main').innerHTML;
  r.check('the Receivables header carries the same figure and the same denominator',
    headHtml.includes('172,600') && /3 of 5 invoices priced/.test(headHtml),
    headHtml.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,240));
  r.check('and no longer claims the header counts full invoiced value',
    !/header total counts full invoiced value/.test(headHtml));
  // A page whose companies carry no shape -- an older server, or a build
  // without one -- must say so, and must never show $0 or fall back to a sum.
  ev("DATA.companies.forEach(c => { delete c.metrics; }); kpis();");
  const tile = (h) => h.split('class="kpi go"')[1] || '';   // the receivables tile alone
  const bare = tile(app.doc.getElementById('kpis').innerHTML);
  r.check('without a shape the tile shows a dash and says it needs the server',
    /needs the server/.test(bare) && !/\$0\b/.test(bare) && !bare.includes('211,000'),
    bare.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,200));
  // A shape with nothing counted is null, and null is not $0.
  ev("DATA.companies.forEach(c => { c.metrics = {exposure_open_receivable_usd: "
     + "{value: null, unit: 'usd', counted: 0, population: 2, excluded: {no_project_link: 2}, basis: 'b'}}; }); kpis();");
  const nul = tile(app.doc.getElementById('kpis').innerHTML);
  r.check('a ledger with nothing priced shows a dash, not $0',
    !/\$0\b/.test(nul) && /0 of 4 invoices priced/.test(nul),
    nul.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').slice(0,200));

  // ---- the shapes are refreshed after a write, not carried stale --------------
  //
  // Every doSave applies the edit to DATA locally; the server's shapes were
  // computed BEFORE it. Without a refresh the tile kept the old figure, and a
  // company edit (whose response carries no metrics) dropped that company
  // from the total with no caveat. The refresh copies metrics ONLY, so a local
  // optimistic edit is not overwritten by the read.
  {
    const store2 = seedStore(path.join(tmp, 'store2'));
    const served = {};          // what list_companies will answer after the "save"
    const app2 = launch({ crmDir, storeDir: store2, outDir: tmp, mode: 'http',
      onCall: (tool) => {
        if (tool === 'list_companies') return served.answer || { ok: true };
        if (tool === 'update_company') return { ok: true, company: { company_id: 'acme',
          display_name: 'Ace Renamed', role: 'customer', domains: [], locations: [], archived: false } };
        return { ok: true };
      } });
    const ev2 = (code) => app2.eval(code);
    const tile2 = () => (app2.doc.getElementById('kpis').innerHTML.split('class="kpi go"')[1] || '')
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    ev2("kpis();");
    r.check('before any edit the tile carries the build-time shapes', /172,600/.test(tile2()), tile2());
    served.answer = { ok: true, companies: [
      { company_id: 'acme', display_name: 'Ace Manufacturing', metrics: { exposure_open_receivable_usd:
        { value: 0, unit: 'usd', counted: 2, population: 2, excluded: {}, basis: 'b' } } },
      { company_id: 'mer', display_name: 'Meridian Corp', metrics: { exposure_open_receivable_usd:
        { value: 83000, unit: 'usd', counted: 1, population: 3, excluded: { no_project_link: 1, no_revenue_on_project: 1 }, basis: 'b' } } },
    ] };
    // a company edit through the real doSave path
    ev2("select('acme'); openEditCompany && openEditCompany('acme');");
    const head2 = () => ((app2.doc.getElementById('main').innerHTML.match(/<p class="co-sum">[\s\S]*?<\/p>/) || [''])[0])
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    const side2 = () => (app2.doc.getElementById('clist').innerHTML.split('class="citem').find(x => /Ace/.test(x)) || '')
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    r.check('before any edit the company headline carries the build-time shape',
      /89,600 outstanding/.test(head2()) && /2 of 2 invoices priced/.test(head2()), head2());
    ev2("document.getElementById('e_co_name') && (document.getElementById('e_co_name').value='Ace Renamed');");
    app2.resetCalls();
    await ev2("saveEditCompany('acme')");
    // settle the refresh the SAVE started -- never start one from here, or a
    // save that stopped refreshing would pass this check
    await ev2("metricsRefresh || Promise.resolve()");
    const tools = app2.calls().map(c => c.tool);
    r.check('a successful save is followed by a list_companies read for fresh shapes',
      tools.includes('update_company') && tools.indexOf('list_companies') > tools.indexOf('update_company'),
      `calls: ${tools.join(',')}`);
    r.check('the tile shows the refreshed figure, not the build-time one',
      /83,000/.test(tile2()) && /3 of 5 invoices priced/.test(tile2()), tile2());
    const acme2 = JSON.parse(ev2("JSON.stringify(DATA.companies.find(c=>c.company_id==='acme'))"));
    r.check('the local optimistic edit survives the refresh (metrics copied, record kept)',
      acme2.display_name === 'Ace Renamed' && acme2.metrics && acme2.metrics.exposure_open_receivable_usd.counted === 2,
      JSON.stringify(acme2).slice(0, 200));
    // The tile was the only surface the refresh repainted. The company page
    // and the sidebar read the same shapes and kept the pre-edit figure.
    r.check('the company headline shows the refreshed shape, not the build-time one',
      /\$0 outstanding/.test(head2()) && /2 of 2 invoices priced/.test(head2()) && !/89,600/.test(head2()), head2());
    r.check('and so does the sidebar line for that customer',
      /\$0 owed · 2 of 2 priced/.test(side2()) && !/89,600/.test(side2()), side2());
    // a refresh the server refuses drops the shapes rather than keeping stale ones
    served.answer = { ok: false, error: 'store locked' };
    await ev2("refreshMetrics()");
    r.check('when the refresh fails the tile says it needs the server, not a stale figure',
      /needs the server/.test(tile2()) && !/83,000/.test(tile2()) && !/172,600/.test(tile2()), tile2());
    r.check('and the company headline says so too, rather than keeping the figure',
      /needs the server/.test(head2()) && !/\$/.test(head2()), head2());
  }

  // ---- the company headline and the sidebar read the shape too --------------
  //
  // companySummary() summed the view's own outstanding(). When no open invoice
  // could be priced that sum was 0 and the line read "$0 outstanding · oldest
  // 433 days late" in red: a real zero and nothing-counted were the same
  // pixels, on 66 of 67 customers with open invoices on the fresh-import
  // store. The sidebar had the same gap behind `owed ? ... : role`. Both now
  // read company.metrics -- the shapes the tile reads -- and say the
  // denominator. The invoice TABLE rows keep outstanding(); that duplication is
  // known and documented at the function.
  {
    const dir3 = path.join(tmp, 'store3');
    fs.mkdirSync(dir3, { recursive: true });
    const w3 = (n, v) => fs.writeFileSync(path.join(dir3, n + '.json'), JSON.stringify(v, null, 2));
    w3('companies', [
      { company_id: 'unl', display_name: 'Unlinked Ltd', role: 'customer', domains: [], locations: [], archived: false },
      { company_id: 'pd', display_name: 'Paid Co', role: 'customer', domains: [], locations: [], archived: false }]);
    w3('projects', [
      { company_id: 'pd', project_no: '8001', status: 'won', year: 2026, revenue: 12000, archived: false },
      { company_id: 'pd', project_no: '8002', status: 'won', year: 2026, revenue: 3000, archived: false }]);
    // thirteen open invoices, none linked to a project: the real store's shape
    const unl = Array.from({ length: 13 }, (_, i) => ({ company_id: 'unl', invoice_no: String(6001 + i),
      project_no: null, payment_status: 'open', invoice_date: i === 0 ? '2025-01-10' : '2026-06-01' }));
    w3('invoices', unl.concat([
      { company_id: 'pd', invoice_no: '7101', project_no: '8001', payment_status: 'paid', invoice_date: '2026-05-01' },
      { company_id: 'pd', invoice_no: '7102', project_no: '8002', payment_status: 'paid', invoice_date: '2026-05-02' }]));
    w3('contacts', []); w3('shipments', []); w3('vendors', []); w3('needs_review', []);
    const app3 = launch({ crmDir, storeDir: dir3, outDir: tmp, mode: 'http' });
    const ev3 = (code) => app3.eval(code);
    const headline = () => ((app3.doc.getElementById('main').innerHTML.match(/<p class="co-sum">[\s\S]*?<\/p>/) || [''])[0])
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    const sideItem = (name) => (app3.doc.getElementById('clist').innerHTML.split('class="citem').find(x => x.includes(name)) || '')
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

    ev3("setFilter('all'); select('unl');");
    let h = headline();
    r.check('a customer whose open invoices cannot be priced never reads $0',
      !/\$0\b/.test(h), `headline: ${h}`);
    r.check('it says nothing was priced, how many are open, and why',
      /nothing priced/.test(h) && /13 open invoices/.test(h) && /13 no project link/.test(h), `headline: ${h}`);
    r.check('and still says how late the oldest one is -- lateness needs no price',
      /oldest \d+ days late/.test(h), `headline: ${h}`);
    r.check('the headline is not a view sum (SOURCE CHECK)',
      !/function companySummary[\s\S]{0,2600}(outstanding|invoiceAmount|daysLate)\(/.test(js),
      'a second pricing rule under the customer\'s name is how the headline and the tile come to disagree');

    ev3("select('pd');");
    h = headline();
    r.check('a paid-only ledger is a real $0, with its count beside it',
      /\$0 outstanding/.test(h) && /2 of 2 invoices priced/.test(h), `headline: ${h}`);
    r.check('and is not called overdue', /none overdue/.test(h) && !/days late/.test(h), `headline: ${h}`);

    // the sidebar: same rule, short form
    let unlSide = sideItem('Unlinked Ltd');
    const pdSide = sideItem('Paid Co');
    r.check('the sidebar never shows $0 for a customer nothing could be priced for',
      !/\$0\b/.test(unlSide) && /nothing priced · 13 open/.test(unlSide), `item: ${unlSide}`);
    r.check('and shows the real $0 with its denominator for the paid-only one',
      /\$0 owed · 2 of 2 priced/.test(pdSide), `item: ${pdSide}`);
    r.check('the sidebar carries the lateness of the unpriced customer',
      /\d+d late/.test(unlSide), `item: ${unlSide}`);

    // no shape at all: say so, on both surfaces, and show no figure
    ev3("DATA.companies.forEach(c => { delete c.metrics; }); select('unl'); renderList();");
    h = headline(); unlSide = sideItem('Unlinked Ltd');
    r.check('with no shape the headline says it needs the server and shows no figure',
      /needs the server/.test(h) && !/\$/.test(h), `headline: ${h}`);
    r.check('and so does the sidebar', /needs the server/.test(unlSide) && !/\$/.test(unlSide), `item: ${unlSide}`);
  }

  // ---- the row and the header price the same invoice the same way -------------
  //
  // The header is the server's; each row is the view's own outstanding(). Two
  // rules the server applies that the view did not: keys are compared
  // trimmed (_key), and "" is not a revenue. Both produced a header that
  // priced an invoice whose row read "no amount on file" or "$0".
  r.check('a project key with stray whitespace still prices its invoice (as the server does)',
    ev("(()=>{ DATA.projects.push({company_id:'acme',project_no:' 4777 ',status:'won',year:2026,revenue:5000,archived:false});"
       + " const v={company_id:'acme',invoice_no:'x',project_no:'4777',payment_status:'open'};"
       + " const a=outstanding(v); DATA.projects.pop(); return String(a); })()") === '5000',
    'the server compares keys through _key(), which strips whitespace');
  r.check('an empty-string revenue is "no amount on file", not $0 (as the server does)',
    ev("(()=>{ DATA.projects.push({company_id:'acme',project_no:'4778',status:'won',year:2026,revenue:'',archived:false});"
       + " const v={company_id:'acme',invoice_no:'y',project_no:'4778',payment_status:'open'};"
       + " const a=outstanding(v); DATA.projects.pop(); return String(a); })()") === 'null',
    'Number("") is 0, and a blank revenue cell was rendering as $0 owed');

  // ---- the build hides what the server hides --------------------------------
  //
  // Review finding: archive_project hides a project and every invoice and leg
  // linked to it from every read tool, but the build shipped them. The
  // customer's headline -- the server's shape -- said nothing for such an
  // invoice while the table beneath showed it $7,777 overdue; the first live
  // refresh made it vanish.
  {
    const dirA = path.join(tmp, 'store-arch');
    fs.mkdirSync(dirA, { recursive: true });
    const wA = (n, v) => fs.writeFileSync(path.join(dirA, n + '.json'), JSON.stringify(v, null, 2));
    wA('companies', [
      { company_id: 'archlink', display_name: 'Archived Link Co', role: 'customer', domains: [], locations: [], archived: false },
      // an ARCHIVED customer whose archived project number a live customer's
      // invoice also carries: the server's archived-number set is store-wide,
      // and the build computed its own set after this company was scrubbed
      { company_id: 'xco', display_name: 'Gone Co', role: 'customer', domains: [], locations: [], archived: true }]);
    wA('projects', [
      { company_id: 'archlink', project_no: 'A1', status: 'won', year: 2026, revenue: 7777, archived: true },
      { company_id: 'archlink', project_no: 'A2', status: 'won', year: 2026, revenue: 100, archived: false },
      { company_id: 'xco', project_no: 'A9', status: 'won', year: 2026, revenue: 555, archived: true }]);
    wA('invoices', [
      { company_id: 'archlink', invoice_no: 'ARCH-7', project_no: 'A1', payment_status: 'open', invoice_date: '2025-01-01' },
      { company_id: 'archlink', invoice_no: 'LIVE-8', project_no: 'A2', payment_status: 'open', invoice_date: '2026-06-01' },
      { company_id: 'archlink', invoice_no: 'CROSS-9', project_no: 'A9', payment_status: 'open', invoice_date: '2025-02-01' }]);
    wA('shipments', [
      { shipment_id: 'A1-L1', company_id: 'archlink', project_no: 'A1', all_project_nos: ['A1'], stage: 'Ordered', vendor_po_raw: 'VPO-ARCH' },
      { shipment_id: 'A2-L1', company_id: 'archlink', project_no: 'A2', all_project_nos: ['A2'], stage: 'Ordered', vendor_po_raw: 'VPO-LIVE' }]);
    wA('contacts', []); wA('vendors', []); wA('needs_review', []);
    const appA = launch({ crmDir, storeDir: dirA, outDir: tmp, mode: 'http' });
    appA.eval("setFilter('all'); select('archlink');");
    const mainA = appA.doc.getElementById('main').innerHTML;
    r.check('an invoice on an archived project is not on the page, as it is not in any read tool',
      !/ARCH-7/.test(mainA) && /LIVE-8/.test(mainA), 'the server hides it; the page must not show money the server does not list');
    r.check("nor is one keyed to an ARCHIVED customer's archived project number",
      !/CROSS-9/.test(mainA), 'the server keys archived numbers store-wide; a set computed after the company scrub missed this one');
    r.check('nor is the archived project, nor its leg',
      !/>A1</.test(mainA) && !/VPO-ARCH/.test(mainA) && /VPO-LIVE/.test(mainA));
    const headA = ((mainA.match(/<p class="co-sum">[\s\S]*?<\/p>/) || [''])[0]).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    r.check('so the headline and the table describe the same invoices',
      /\$100 outstanding/.test(headA) && /1 of 1 invoice priced/.test(headA), headA);
    appA.eval("setFilter('receivable');");
    r.check('and the Receivables list does not count it either',
      !/ARCH-7/.test(appA.doc.getElementById('main').innerHTML));
  }
  // If a build and a store ever do disagree -- the server lists no invoice for
  // a customer whose page still shows some -- the headline must say so rather
  // than fall silent above a table of money.
  ev("DATA.companies.find(c=>c.company_id==='acme').metrics.exposure_open_receivable_usd = "
     + "{value:null, unit:'usd', counted:0, population:0, excluded:{}, basis:'b'}; setFilter('all'); select('acme');");
  const silent = ((app.doc.getElementById('main').innerHTML.match(/<p class="co-sum">[\s\S]*?<\/p>/) || [''])[0])
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  r.check('a shape with no population over a page that shows invoices says it needs the server, not nothing',
    /needs the server/.test(silent) && /lists no invoice/.test(silent), `headline: ${JSON.stringify(silent)}`);
  ev("renderList();");
  const silentSide = (app.doc.getElementById('clist').innerHTML.split('class="citem').find(x => x.includes('Ace')) || '')
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  r.check('and the sidebar says the same, rather than falling back to the role line',
    /needs the server/.test(silentSide) && !/\$/.test(silentSide), `item: ${silentSide}`);

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

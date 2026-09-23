// The Receivables screen with a QuickBooks snapshot beside the store (0.1.38 B3),
// in a real browser.
//
// The header shows the QuickBooks open balance first, labelled with the
// snapshot's as_of, with a visible "stale" marker past 7 days; the CRM-basis
// figure comes second, labelled quoted. The rows gain QBO amount and QBO open
// columns, and the sum of the rendered QBO open cells over EVERY bucket equals
// the header's QuickBooks figure, to the cent. Every figure is the server's
// shape (embedded at build time from the same builder); the view only renders
// and sums them.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { buildBundle, makeResult } = require('../lib/view.js');
const { drive } = require('../lib/browser.js');

function isoDaysAgo(n) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
    + String(d.getDate()).padStart(2, '0');
}

// Generic names only: this repo is public and swept for identifying content.
function seed(dir, asOf) {
  const store = path.join(dir, 'store');
  fs.mkdirSync(store, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(store, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer',
      domains: [], locations: [], archived: false },
    { company_id: 'beta', display_name: 'Beta Works', role: 'customer',
      domains: [], locations: [], archived: false }]);
  w('projects', [
    { company_id: 'acme', project_no: '4521', status: 'won', revenue: 10000, archived: false },
    { company_id: 'beta', project_no: '4600', status: 'won', revenue: 3000, archived: false },
    { company_id: 'beta', project_no: '4601', status: 'won', revenue: 8000, archived: false }]);
  w('invoices', [
    { company_id: 'acme', invoice_no: '7001', project_no: '4521',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'acme', invoice_no: '1342 (INV 7002-50%)', project_no: '4521',
      payment_status: 'open', invoice_date: '2026-06-02' },
    { company_id: 'beta', invoice_no: 'INV 7003', project_no: '4600',
      payment_status: 'paid', invoice_date: '2026-06-03' },
    { company_id: 'beta', invoice_no: '7010', project_no: '4601',
      payment_status: 'open', invoice_date: '2026-06-04' },
    { company_id: 'acme', invoice_no: '7020', payment_status: 'open' },
    // numbers stored as JSON numbers, one of them a float: a documented real
    // case (0.1.24). The server and the page must key these rows alike.
    { company_id: 'beta', invoice_no: 7030, payment_status: 'open', invoice_date: '2026-06-05' },
    { company_id: 'beta', invoice_no: 7040, payment_status: 'open', invoice_date: '2026-06-06' }]);
  const ip = path.join(store, 'invoices.json');
  fs.writeFileSync(ip, fs.readFileSync(ip, 'utf8').replace('"invoice_no": 7040', '"invoice_no": 7040.0'));
  w('contacts', []); w('shipments', []); w('vendors', []); w('needs_review', []);
  if (asOf) {
    const snap = path.join(dir, 'qbo-snapshots');
    fs.mkdirSync(snap, { recursive: true });
    const row = (num, a, o) => ({ type: 'Invoice', num, date: '2026-06-01', due_date: null,
      name: 'Someone', memo: null, amount_cents: a, open_cents: o });
    fs.writeFileSync(path.join(snap, 'invoices.json'), JSON.stringify({
      kind: 'invoices', source: 'export', as_of: asOf, window_start: '2026-01-01',
      window_end: '2026-12-31', loaded_at: '2026-09-01T00:00:00+00:00',
      rows: [row('7001', 500000, 123456), row('7002', 250000, 10005),
             row('7003', 300000, 50000), row('7020', 4200, 4200),
             row('7030', 70000, 70000), row('7040', 80000, 80000),
             row('7099', 999900, 999900)] }));
  }
  return store;
}

const cents = (s) => {
  const m = /\$([\d,]+)\.(\d{2})/.exec(String(s || ''));
  return m ? Number(m[1].replace(/,/g, '')) * 100 + Number(m[2]) : null;
};
const ROWS = "[...document.querySelectorAll('#main table tbody tr')].map(tr => ({"
  + " inv: tr.children[0].innerText.trim(), qamt: (tr.children[4]||{}).innerText,"
  + " qopen: (tr.children[5]||{}).innerText,"
  + " qtitle: (((tr.children[5]||{querySelector:()=>null}).querySelector('[title]')) || {}).title || '' }))";
const ALL_BUCKETS = "(() => { const out = {}; "
  + "for (const b of BUCKET_ORDER) { setRecvBucket(b); out[b] = " + ROWS + "; } return out; })()";

function view(crmDir, asOf) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmqbo-'));
  const store = seed(tmp, asOf);
  buildBundle(crmDir, store, tmp);
  const got = drive(path.join(tmp, 'view.html'), [
    { wait: 400 },
    { click: '#filters button[data-f="receivable"]' },
    { eval: "(document.querySelector('#main .co-head') || {}).innerText || ''", as: 'header' },
    { eval: "[...document.querySelectorAll('#main table thead th')].map(t => t.innerText.trim())", as: 'cols' },
    { eval: ALL_BUCKETS, as: 'buckets' },
  ]);
  fs.rmSync(tmp, { recursive: true, force: true });
  return got;
}

async function run(crmDir) {
  const r = makeResult('qbo/view');

  const fresh = isoDaysAgo(2);
  const got = view(crmDir, fresh);
  r.check('the page ran with no script error', (got.__pageerrors || []).length === 0,
    JSON.stringify(got.__pageerrors));
  const head = got.header || '';
  r.check('the header leads with the QuickBooks open balance, labelled with its as_of',
    /QuickBooks/.test(head) && cents(head) === 123456 + 10005 + 50000 + 4200 + 70000 + 80000,
    JSON.stringify(head));
  const d = new Date(fresh + 'T00:00:00');
  const shown = d.getDate() + ' ' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()];
  r.check('... the as_of date is on screen', head.includes(shown), `${shown} not in ${JSON.stringify(head)}`);
  r.check('a 2-day-old snapshot is not marked stale', !/stale/i.test(head), JSON.stringify(head));
  const qi = head.indexOf('QuickBooks'), qq = head.search(/quoted/);
  r.check('the CRM-basis figure comes second, labelled quoted', qi >= 0 && qq > qi, JSON.stringify(head));
  r.check('the rows gain QBO amount and QBO open columns',
    /^qbo amount$/i.test((got.cols || [])[4]) && /^qbo open$/i.test((got.cols || [])[5]),
    JSON.stringify(got.cols));

  const all = Object.values(got.buckets || {}).flat();
  const byInv = Object.fromEntries(all.map(x => [x.inv, x]));
  r.check('every invoice appears in some bucket', all.length === 7, JSON.stringify(all.map(x => x.inv)));
  r.check('invoice numbers stored as JSON numbers (7030, and 7040.0) show their QuickBooks open',
    cents((byInv['7030'] || {}).qopen) === 70000 && cents((byInv['7040'] || {}).qopen) === 80000,
    JSON.stringify([byInv['7030'], byInv['7040']]));
  r.check('the composite invoice shows QuickBooks invoice 7002: $2,500.00 / $100.05',
    cents((byInv['1342 (INV 7002-50%)'] || {}).qamt) === 250000
      && cents((byInv['1342 (INV 7002-50%)'] || {}).qopen) === 10005,
    JSON.stringify(byInv['1342 (INV 7002-50%)']));
  r.check('the CRM-paid invoice shows its QuickBooks open balance: $500.00',
    cents((byInv['INV 7003'] || {}).qopen) === 50000, JSON.stringify(byInv['INV 7003']));
  const miss = byInv['7010'] || {};
  r.check('an invoice QuickBooks lacks shows a dash and says why',
    cents(miss.qopen) === null && /not in qbo snapshot/.test(miss.qtitle), JSON.stringify(miss));
  const rowSum = all.reduce((a, x) => a + (cents(x.qopen) || 0), 0);
  r.check('the rendered QBO open cells, over every bucket, sum to the header to the cent',
    cents(head) !== null && rowSum === cents(head),
    `rows ${rowSum} vs header ${cents(head)}: ${JSON.stringify(head)}`);

  const old = view(crmDir, '2026-01-02');
  r.check('a snapshot more than 7 days old shows a visible stale marker',
    /stale/i.test(old.header || ''), JSON.stringify(old.header));

  const none = view(crmDir, null);
  r.check('with no snapshot the page still renders, with no script error',
    (none.__pageerrors || []).length === 0 && /Receivables/.test(none.header || ''),
    JSON.stringify([none.__pageerrors, none.header]));
  r.check('... the header does not mention QuickBooks at all (no snapshot is not a $0 or an empty match)',
    !/QuickBooks/.test(none.header || ''), JSON.stringify(none.header));
  const n7001 = Object.values(none.buckets || {}).flat().find(x => x.inv === '7001') || {};
  r.check('... and a row says no snapshot is loaded rather than $0.00',
    cents(n7001.qopen) === null && /no qbo snapshot/.test(n7001.qtitle), JSON.stringify(n7001));
  return r;
}

module.exports = { run };

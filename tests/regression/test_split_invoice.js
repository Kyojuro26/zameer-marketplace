// The Receivables ROWS on a split-billed project, in a real browser.
//
// 0.1.37's server fix excludes an invoice whose project carries more than one
// invoice, and the header and tile only sum the server's shapes -- so they
// were fixed by it. The rows were not: build_view.py prices each row itself
// with outstanding(), a known, documented duplication of the server's rule.
// After the server fix alone the header said "2 on a project with more than
// one invoice" while the two rows beneath it each still showed the project's
// full revenue. That is the header-vs-rows disagreement 0.1.36 closed as its
// defect #5, reintroduced by a server-only change.
//
// This module drives the shipped page in headless Chromium (lib/browser.js):
// click the Receivables filter, read what is painted, and require that the
// sum of the rendered row amounts equals the header's figure.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { buildBundle, makeResult } = require('../lib/view.js');
const { drive } = require('../lib/browser.js');

// Generic names only: this repo is public and swept for identifying content.
function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'split', display_name: 'Split Co', role: 'customer',
      domains: [], locations: [], archived: false },
    { company_id: 'other', display_name: 'Other Co', role: 'customer',
      domains: [], locations: [], archived: false }]);
  w('projects', [
    // the split-billed project: three invoices, two open and one paid
    { company_id: 'split', project_no: '5001', status: 'won', year: 2026,
      revenue: 10000, total_cost: 6000, archived: false },
    // a one-invoice project, so the header has a figure the rows must add up to
    { company_id: 'split', project_no: '5002', status: 'won', year: 2026,
      revenue: 3000, archived: false },
    // the SAME number at another customer, one invoice: not split-billed
    { company_id: 'other', project_no: '5002', status: 'won', year: 2026,
      revenue: 2000, archived: false },
    // exactly TWO invoices, both open: "more than one" must not mean "more than two"
    { company_id: 'split', project_no: '5003', status: 'won', year: 2026,
      revenue: 4000, archived: false }]);
  // every invoice_date is 2026-06-01: due 2026-07-01, overdue on any day this
  // suite will run, so the Overdue bucket the view opens on holds them all
  w('invoices', [
    { company_id: 'split', invoice_no: '6001', project_no: '5001',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'split', invoice_no: '6002', project_no: '5001',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'split', invoice_no: '6003', project_no: '5001',
      payment_status: 'paid', invoice_date: '2026-06-01' },
    { company_id: 'split', invoice_no: '6004', project_no: '5002',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'other', invoice_no: '6005', project_no: '5002',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'split', invoice_no: '6006', project_no: '5003',
      payment_status: 'open', invoice_date: '2026-06-01' },
    { company_id: 'split', invoice_no: '6007', project_no: '5003',
      payment_status: 'open', invoice_date: '2026-06-01' }]);
  w('contacts', []); w('shipments', []); w('vendors', []); w('needs_review', []);
  return dir;
}

const dollars = (s) => {
  const m = /\$([\d,]+)/.exec(String(s || ''));
  return m ? Number(m[1].replace(/,/g, '')) : null;
};
const ROWS = "[...document.querySelectorAll('#main table tbody tr')].map(tr => ({"
  + " inv: tr.children[0].innerText.trim(), owed: tr.children[3].innerText.trim(),"
  + " title: ((tr.children[3].querySelector('[title]') || {}).title) || '' }))";

async function run(crmDir) {
  const r = makeResult('split-invoice/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmsplit-'));
  const store = seedStore(path.join(tmp, 'store'));
  buildBundle(crmDir, store, tmp);
  const html = path.join(tmp, 'view.html');

  const got = drive(html, [
    { wait: 400 },                                   // CRM.detect() settles in embedded mode
    { click: '#filters button[data-f="receivable"]' },
    { eval: 'filter', as: 'filter' },
    { eval: "(document.querySelector('#main .co-head') || {}).innerText || ''", as: 'header' },
    { eval: ROWS, as: 'rows' },
    { eval: "(document.querySelector('#main table tfoot') || {}).innerText || ''", as: 'footer' },
    { eval: "(document.getElementById('kpis') || {}).innerText || ''", as: 'tile' },
    { eval: 'JSON.stringify(ledgerExposure())', as: 'ledger' },
    // the Paid bucket, through its own sub-filter button
    { eval: "[...document.querySelectorAll('#subfilters button')]"
          + ".find(b => /^Paid/.test(b.textContent.trim())).click()", as: 'clickedPaid' },
    { eval: ROWS, as: 'paidRows' },
  ]);

  r.check('the page ran with no script error', (got.__pageerrors || []).length === 0,
    JSON.stringify(got.__pageerrors));
  r.check('the Receivables filter button opened the view', got.filter === 'receivable'
    && /Receivables/.test(got.header), `filter=${got.filter} header=${JSON.stringify(got.header)}`);

  const rows = got.rows || [];
  const byInv = Object.fromEntries(rows.map(x => [x.inv, x]));
  r.check('the Overdue bucket shows the six open invoices',
    JSON.stringify(rows.map(x => x.inv).sort())
      === JSON.stringify(['6001', '6002', '6004', '6005', '6006', '6007']),
    JSON.stringify(rows.map(x => x.inv)));
  const splitRows = ['6001', '6002', '6006', '6007'].map(k => byInv[k] || {});
  r.check('the four rows on the two split-billed projects render NO dollar figure',
    splitRows.every(x => x.owed && dollars(x.owed) === null),
    `rows read: ${splitRows.map(x => JSON.stringify(x.owed)).join(' / ')} -- each was the `
    + 'full project revenue before the view fix');
  r.check('...and the CELL says, visibly, that the project carries more than one invoice',
    splitRows.every(x => /more than one invoice/.test(x.owed)),
    splitRows.map(x => JSON.stringify(x.owed)).join(' / ')
    + ' -- a hover title alone is not something he reads mid-way through linking');
  r.check('...and nothing on those rows says "no amount on file"',
    splitRows.every(x => !/no amount on file/.test(x.owed + ' ' + x.title)),
    splitRows.map(x => JSON.stringify(x.owed + ' | ' + x.title)).join(' / ')
    + ' -- a label that reads like a linking error sends him back to re-link invoices that are right');
  r.check('the one-invoice project prices its row: $3,000',
    dollars((byInv['6004'] || {}).owed) === 3000, JSON.stringify(byInv['6004']));
  r.check("the other customer's one invoice on the same project NUMBER prices too: $2,000",
    dollars((byInv['6005'] || {}).owed) === 2000,
    JSON.stringify(byInv['6005']) + ' -- split-billed is per (project, customer)');

  const rowSum = rows.reduce((a, x) => a + (dollars(x.owed) || 0), 0);
  const headerValue = dollars(got.header);
  r.check('the sum of the rendered row amounts equals the header figure',
    headerValue !== null && rowSum === headerValue,
    `rows sum to ${rowSum}; header reads ${JSON.stringify(got.header)}`);
  const led = JSON.parse(got.ledger || 'null') || {};
  r.check("the header figure is the server's shape: 5000 over 3 of 7, four excluded as split-billed",
    headerValue === 5000 && led.value === 5000 && led.counted === 3 && led.population === 7
      && JSON.stringify(led.excluded) === JSON.stringify({ multiple_invoices_on_project: 4 }),
    JSON.stringify(led));
  r.check('the header names the exclusion in words',
    /3 of 7 invoices priced/.test(got.header) && /4 on a project with more than one invoice/.test(got.header),
    JSON.stringify(got.header));
  r.check('the tile carries the same figure and denominator', /5,000/.test(got.tile) && /3 of 7 invoices priced/i.test(got.tile),
    JSON.stringify((got.tile || '').replace(/\s+/g, ' ').slice(0, 240)));
  r.check('the table footer totals $5,000 and names the four split-billed rows it excludes',
    dollars(got.footer) === 5000 && /excludes 4 invoices on a project with more than one invoice/.test(got.footer)
      && !/no amount on file/.test(got.footer),
    JSON.stringify(got.footer));

  // The paid invoice on the split-billed project is a real $0, as the server
  // has it: the view's split check must run AFTER its paid short-circuit.
  const paid = (got.paidRows || []).find(x => x.inv === '6003') || {};
  r.check('the PAID invoice on the split-billed project reads $0 in the Paid bucket, not a dash',
    dollars(paid.owed) === 0, JSON.stringify(paid) + ' -- paid before split, or the zero rule breaks');

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

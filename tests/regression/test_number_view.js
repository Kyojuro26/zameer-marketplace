// Number search and the PO warning, in a real browser (0.1.38 B4).
//
// The page is built in embedded mode, which has no server. So CRM.call is
// replaced in the page with a stub that answers with responses the REAL
// server gave, captured from a python run of server.py against the same
// seeded store -- the page renders exactly what the server says, and the
// matching rule stays in ONE place (lookup_number).
//
//  * typing a number into the search box shows every typed hit, grouped and
//    labelled by type; a number that is six things shows six hits under six
//    labels, never collapsed into one result
//  * saving an invoice whose project_no is also a vendor PO shows the
//    server's warning after the save, and the save itself goes through
const path = require('path');
const os = require('os');
const fs = require('fs');
const { execFileSync } = require('child_process');
const { buildBundle, makeResult } = require('../lib/view.js');
const { drive } = require('../lib/browser.js');

// Seeds a store (and snapshots beside it) with test_number_lookup.py's own
// fixture, then answers the two calls the page will make. Generic names only.
const PY = `
import json, sys
sys.path.insert(0, sys.argv[1] + "/tests"); sys.path.insert(0, sys.argv[1] + "/tests/regression")
from lib.harness import load_server, Store
import test_number_lookup as T
srv = load_server(sys.argv[2])
st = Store(srv, sys.argv[3])
T.seed(srv, st)
# the two answers the page will need; update_invoice writes, so the store is
# re-seeded below and the build reads it as seeded
look = st.call("lookup_number", n="1167")
upd = st.call("update_invoice", company_id="acme", invoice_no="4521 (INV 1191)",
              fields={"project_no": "1167"})
T.seed(srv, st)          # put the store back as it was for the build
json.dump({"look": look, "upd": upd}, sys.stdout)
`;

async function run(crmDir) {
  const r = makeResult('number-lookup/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmnum-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  let answers;
  try {
    answers = JSON.parse(execFileSync('python3', ['-c', PY, repo, crmDir, store],
                                      { encoding: 'utf8' }));
  } catch (e) {
    r.check('the server answered the seeded store', false, String(e).slice(0, 300));
    fs.rmSync(tmp, { recursive: true, force: true });
    return r;
  }
  r.check('the server found 1167 (precondition)',
    answers.look && answers.look.ok === true && (answers.look.matches || []).length === 6,
    JSON.stringify(answers.look).slice(0, 200));
  buildBundle(crmDir, store, tmp);

  const stub = `(() => { const A = ${JSON.stringify(answers)};
    const real = CRM.call.bind(CRM);
    CRM.call = async (tool, args) => {
      if (tool === 'lookup_number' && String(args.n).trim() === '1167') return A.look;
      if (tool === 'lookup_number' && String(args.n).trim() === '2222')
        return {ok: true, matches: [{type: 'some_future_type', num: '2222'}]};
      if (tool === 'update_invoice') return A.upd;
      return real(tool, args);
    }; return true; })()`;
  const type = (v) => `(() => { const q = document.getElementById('q'); q.value = ${JSON.stringify(v)};
    q.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`;
  const HITS = "[...document.querySelectorAll('#numhits [data-type]')].map(g => ({"
    + " type: g.getAttribute('data-type'), label: (g.querySelector('.nh-label')||{}).innerText || '',"
    + " hits: [...g.querySelectorAll('.nh-hit')].map(h => h.innerText.trim()) }))";

  const got = drive(path.join(tmp, 'view.html'), [
    { wait: 400 },
    { eval: stub, as: 'stubbed' },
    { eval: type('1167'), as: 't1' },
    { wait: 300 },
    { eval: HITS, as: 'groups' },
    { eval: "(document.getElementById('numhits') || {}).innerText || ''", as: 'panel' },
    { eval: type('2222'), as: 'tf' },
    { wait: 300 },
    { eval: "(document.getElementById('numhits') || {}).innerText || ''", as: 'panelFuture' },
    { eval: type('Ace'), as: 't2' },
    { wait: 200 },
    { eval: "(document.getElementById('numhits') || {}).innerText || ''", as: 'panelText' },
    { eval: type('4521'), as: 't3' },
    { wait: 300 },
    { eval: "(document.getElementById('numhits') || {}).innerText || ''", as: 'panelDemo' },
    { eval: type(''), as: 't4' },
    { eval: "select('acme'); openEditInvoice('acme', '4521 (INV 1191)'); "
          + "document.getElementById('e_iv_proj').value = '1167'; true", as: 'opened' },
    { click: '#saveBtn' },
    { wait: 500 },
    { eval: "(document.getElementById('noticeToast') || {}).innerText || ''", as: 'toast' },
    { eval: "(DATA.invoices.find(v => v.invoice_no === '4521 (INV 1191)') || {}).project_no", as: 'saved' },
  ]);
  fs.rmSync(tmp, { recursive: true, force: true });

  r.check('the page ran with no script error', (got.__pageerrors || []).length === 0,
    JSON.stringify(got.__pageerrors));
  const groups = got.groups || [];
  const types = groups.map(g => g.type).sort();
  r.check('1167 shows six groups, one per type',
    JSON.stringify(types) === JSON.stringify(['crm_invoice', 'project', 'qbo_bill', 'qbo_invoice',
                                              'qbo_po', 'vendor_po_on_leg']),
    JSON.stringify(groups));
  r.check('each group is labelled in words, never by its code',
    groups.length === 6 && groups.every(g => g.label && !/_/.test(g.label)),
    JSON.stringify(groups.map(g => g.label)));
  r.check('every hit is its own line: six hits, none collapsed',
    groups.reduce((a, g) => a + g.hits.length, 0) === 6, JSON.stringify(groups));
  const bill = groups.find(g => g.type === 'qbo_bill') || {hits: []};
  r.check("the bill says its Num is the vendor's own invoice number, not a PO",
    /not a PO/.test(bill.label + ' ' + bill.hits.join(' ')), JSON.stringify(bill));
  const leg = groups.find(g => g.type === 'vendor_po_on_leg') || {hits: []};
  r.check('the leg hit names its job and vendor',
    /4521/.test(leg.hits.join(' ')) && /Cobalt Freight/.test(leg.hits.join(' ')), JSON.stringify(leg));
  r.check('a match of a type this page has no label for is still shown, not dropped',
    /2222/.test(got.panelFuture || '') && /some.future.type/i.test(got.panelFuture || ''),
    JSON.stringify(got.panelFuture));
  r.check('text that is not a number shows no number panel', !(got.panelText || '').trim(),
    JSON.stringify(got.panelText));
  r.check('with no server (demo mode) the panel says the lookup needs the server',
    /needs the server|not available/.test(got.panelDemo || ''), JSON.stringify(got.panelDemo));

  r.check('the save went through: the invoice now links to 1167', got.saved === '1167',
    JSON.stringify(got.saved));
  r.check("after saving, the server's warning is on screen, naming the vendor and the job",
    /also vendor PO/.test(got.toast || '') && /Cobalt Freight/.test(got.toast || '')
      && /4521/.test(got.toast || ''), JSON.stringify(got.toast));
  return r;
}

module.exports = { run };

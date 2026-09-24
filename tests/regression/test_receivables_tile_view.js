// The Open receivables tile leads with QuickBooks' open balance (0.1.44 H2).
//
// The Receivables screen already led with QuickBooks' open balance when a
// snapshot was loaded; the top tile still showed the CRM's quoted figure, which
// cannot price a split-billed job (a CRM invoice carries no amount). On the
// operator's machine that was $136,693 on the tile against $179,545.38 in
// QuickBooks. Asserted, on a live local_server.py with a synthetic store and
// snapshot that include a split-billed job (one paid invoice, one open):
//   * the tile's headline is QuickBooks' open balance to the cent, dated, and
//     is the identical figure the Receivables header shows;
//   * the quoted figure sits beneath it, labelled quoted, with its denominator;
//   * a stale snapshot says so on the tile, with its age;
//   * with no snapshot the tile is byte-identical to 0.1.43's (e324117).
// Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

function isoDaysAgo(n) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function seed(dir, asOf, mismatch) {
  const store = path.join(dir, 'store');
  fs.mkdirSync(store, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(store, n + '.json'), JSON.stringify(v, null, 2));
  w('companies', [
    { company_id: 'acme', display_name: 'Ace Manufacturing', role: 'customer', domains: [], locations: [], archived: false },
    { company_id: 'beta', display_name: 'Beta Works', role: 'customer', domains: [], locations: [], archived: false,
      ...(mismatch ? { qbo_name: 'Beta Works' } : {}) },
    ...(mismatch ? [{ company_id: 'gamma', display_name: 'Gamma Tooling', role: 'customer', domains: [],
                      locations: [], archived: false }] : [])]);
  w('projects', [
    // split-billed: one paid invoice, one open -- the CRM cannot price it
    { company_id: 'acme', project_no: '1419', status: 'won', revenue: 90000, archived: false },
    { company_id: 'beta', project_no: '4600', status: 'won', revenue: 3000, archived: false }]);
  w('invoices', [
    { company_id: 'acme', invoice_no: '1202', project_no: '1419', payment_status: 'paid', invoice_date: '2026-06-01' },
    { company_id: 'acme', invoice_no: '1238', project_no: '1419', payment_status: 'open', invoice_date: '2026-07-01' },
    { company_id: 'beta', invoice_no: '7010', project_no: '4600', payment_status: 'open', invoice_date: '2026-06-04' },
    // an open invoice QuickBooks has no row for: counted out of both figures, with its reason
    { company_id: 'beta', invoice_no: '7011', payment_status: 'open', invoice_date: '2026-06-05' },
    // gamma is tied to no QuickBooks name: priced, and said to be not verified
    ...(mismatch ? [{ company_id: 'gamma', invoice_no: '7030', payment_status: 'open', invoice_date: '2026-06-06' }] : [])]);
  w('contacts', []); w('shipments', []); w('vendors', []); w('needs_review', []);
  if (asOf) {
    const snap = path.join(dir, 'qbo-snapshots');
    fs.mkdirSync(snap, { recursive: true });
    const row = (num, name, a, o) => ({ type: 'Invoice', num, date: '2026-06-01', due_date: null,
      name, memo: null, amount_cents: a, open_cents: o });
    fs.writeFileSync(path.join(snap, 'invoices.json'), JSON.stringify({
      kind: 'invoices', source: 'export', as_of: asOf, window_start: '2026-01-01',
      window_end: '2026-12-31', loaded_at: '2026-09-01T00:00:00+00:00',
      rows: [row('1202', 'Ace Manufacturing', 4500000, 0),
             row('1238', 'Ace Manufacturing', 4500000, 4285213),
             // 0.1.44 H3: with beta tied to 'Beta Works', a 7010 QuickBooks lists
             // under Ace Manufacturing is not beta's: not priced, both named
             row('7010', mismatch ? 'Ace Manufacturing' : 'Beta Works', 300000, 300025)]
             .concat(mismatch ? [row('7030', 'Somebody Else', 10000, 100)] : []) }));
  }
  return store;
}

const TILE = "((document.querySelector('#kpis .kpi.go')||{}).outerHTML||'')";
// the label is CSS text-transform: uppercase, and innerText returns it as rendered
const TILE_TEXT = "((document.querySelector('#kpis .kpi.go')||{}).innerText||'')";
const TILE_HEAD = "((document.querySelector('#kpis .kpi.go .n')||{}).innerText||'')";
const RECV_HEAD = "((document.querySelector('#main .co-head b')||{}).innerText||'')";

function serveAndRead(crmDir, store, steps) {
  const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
  const url = `http://127.0.0.1:${port}/`;
  const srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                                '--port', port, '--no-browser'], { stdio: 'ignore' });
  try {
    execFileSync('python3', ['-c', PY_WAIT, url]);
    return driveUrl(url, [{ wait: 1500 }].concat(steps));
  } finally {
    srv.kill();
  }
}

async function run(crmDir) {
  const r = makeResult('receivables-tile/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmtile-'));
  const repo = path.resolve(__dirname, '..', '..');
  let fresh = {}, stale = {}, none = {}, old = {}, mm = {};
  try {
    const read = [{ eval: TILE_HEAD, as: 'head' }, { eval: TILE_TEXT, as: 'text' }, { eval: TILE, as: 'html' },
                  { click: '#kpis .kpi.go' }, { wait: 500 }, { eval: RECV_HEAD, as: 'recv' }];
    fresh = serveAndRead(crmDir, seed(path.join(tmp, 'fresh'), isoDaysAgo(1)), read);
    stale = serveAndRead(crmDir, seed(path.join(tmp, 'stale'), isoDaysAgo(20)), read);
    none = serveAndRead(crmDir, seed(path.join(tmp, 'none'), null), [{ eval: TILE, as: 'html' }]);
    mm = serveAndRead(crmDir, seed(path.join(tmp, 'mm'), isoDaysAgo(1), true), [
      { eval: TILE_HEAD, as: 'head' }, { eval: TILE_TEXT, as: 'text' }, { click: '#kpis .kpi.go' }, { wait: 500 },
      { eval: RECV_HEAD, as: 'recv' }, { eval: "((document.querySelector('#main .co-head')||{}).innerText||'')", as: 'recvText' },
      { eval: "(() => { for (const b of BUCKET_ORDER) { setRecvBucket(b); const tr = [...document.querySelectorAll('#main table tbody tr')]"
        + ".find(t => t.children[0].innerText.trim() === '7010'); if (tr) return (tr.querySelector('[title]')||{}).title || ''; } return null; })()", as: 'cell' }]);
    // 0.1.43's page over the same no-snapshot store: a copy of the plugin
    // with e324117's build_view.py
    const oldCrm = path.join(tmp, 'crm-0143');
    fs.cpSync(crmDir, oldCrm, { recursive: true });
    fs.writeFileSync(path.join(oldCrm, 'view', 'build_view.py'), execFileSync('git',
      ['-C', repo, 'show', 'e324117:plugins/unrivaled-solutions/skills/crm/view/build_view.py'], { encoding: 'utf8' }));
    old = serveAndRead(oldCrm, seed(path.join(tmp, 'none-old'), null), [{ eval: TILE, as: 'html' }]);
  } catch (err) {
    r.check('the stores seeded and the servers started', false, String(err).slice(0, 300));
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const errs = [].concat(fresh.__pageerrors || [], stale.__pageerrors || [], none.__pageerrors || [], old.__pageerrors || [],
                         mm.__pageerrors || []);
  r.check('the page ran with no script error', errs.length === 0, JSON.stringify(errs));

  r.check("with a snapshot, the tile's headline is QuickBooks' open balance to the cent",
    fresh.head === '$45,852.38', fresh.head);
  r.check('... the identical figure the Receivables header shows', fresh.recv === fresh.head && !!fresh.head,
    JSON.stringify([fresh.head, fresh.recv]));
  r.check('... dated', /QuickBooks as of/i.test(fresh.text || ''), fresh.text);
  r.check('... with the quoted figure beneath it, labelled quoted', /\$3,000 quoted/i.test(fresh.text || ''), fresh.text);
  // QuickBooks' own count, not the quoted figure's: 3 of the 4 open CRM
  // invoices have a QuickBooks row; 7011 has none, and says why
  const qPart = (fresh.text || '').split(/quoted/i)[0];
  r.check('... and the denominator: how many matched QuickBooks and why the rest did not',
    /3 of 4 invoices priced · 1 /i.test(qPart), qPart);
  r.check('a fresh snapshot is not called stale', !/stale/i.test(fresh.text || ''), fresh.text);
  r.check('a stale snapshot says so on the tile, with its age', /stale · 20 days old/i.test(stale.text || ''), stale.text);
  r.check("... and still leads with QuickBooks' figure", stale.head === '$45,852.38', stale.head);
  r.check("a QuickBooks invoice under another customer is not priced: the tile and header leave it out",
    mm.head === '$42,853.13' && mm.recv === mm.head, JSON.stringify([mm.head, mm.recv]));
  r.check('a priced invoice whose customer is not verified is said so on the tile and the header',
    /1 customer not verified/i.test(mm.text || '') && /1 customer not verified/i.test(mm.recvText || ''),
    JSON.stringify([mm.text, mm.recvText]));
  r.check('... and the invoice names both customers where it is shown',
    /Ace Manufacturing/.test(mm.cell || '') && /Beta Works/.test(mm.cell || ''), mm.cell);
  r.check('with no snapshot the tile is byte-identical to 0.1.43',
    !!none.html && none.html === old.html, JSON.stringify([none.html, old.html]).slice(0, 400));
  return r;
}

module.exports = { run };

// The CFO page, through the real click path against a LIVE server (0.1.40 D3).
//
// local_server.py serves a temp store seeded with test_cfo.py's fixture; headless
// Chromium clicks the CFO tab. Four states, each first-class:
//   full     every snapshot loaded -- each tile equals the server's shape value
//   none     nothing loaded -- the page renders, and every tile says what to
//            load instead of showing $0
//   stale    snapshots a month old -- a visible stale marker
//   partial  invoices but no cash -- cash says what to load, receivables read
// The server's own report for the same store is computed by a separate python
// process, so the page is checked against the server, not against itself.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const PY_SEED = `
import json, sys, datetime
sys.path.insert(0, sys.argv[1] + "/tests"); sys.path.insert(0, sys.argv[1] + "/tests/regression")
from lib.harness import load_server, Store
import test_cfo as T
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3]); state = sys.argv[4]
T.seed_store(st)
today = datetime.date.today()
fresh = (today - datetime.timedelta(days=1)).isoformat()
old = (today - datetime.timedelta(days=30)).isoformat()
# a build with no snapshot layer or no CFO report still gets its store, so the
# page is driven and fails on what it renders
if hasattr(srv, "_save_qbo_snapshot"):
    if state in ("full", "partial", "stale"):
        T.qbo_invoices(srv, as_of=old if state == "stale" else fresh)
    if state in ("full", "stale"):
        T.load_vendor(srv, connector=True, as_of=old if state == "stale" else fresh)
        T.load_cash(srv, as_of=old if state == "stale" else fresh)
got = st.call("crm_metrics", report="cfo")
json.dump(((got.get("reports") or {}).get("cfo")) or None, sys.stdout)
`;
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

const cents = (s) => {
  const m = /(-?)\$([\d,]+)\.(\d{2})/.exec(String(s || ''));
  return m ? (m[1] ? -1 : 1) * (Number(m[2].replace(/,/g, '')) * 100 + Number(m[3])) : null;
};
const TILE = (id) => `(document.getElementById('${id}')||{}).innerText||''`;

function state(crmDir, name) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmcfov-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  const server = JSON.parse(execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store, name],
                                         { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
  const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
  const url = `http://127.0.0.1:${port}/`;
  const srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                                '--port', port, '--no-browser'], { stdio: 'ignore' });
  let page = {};
  try {
    execFileSync('python3', ['-c', PY_WAIT, url]);
    page = driveUrl(url, [
      { wait: 800 },
      { click: '#filters button[data-f="cfo"]' },
      { wait: 800 },
      { eval: 'filter', as: 'filter' },
      { eval: TILE('cfo-tile-cash'), as: 'cash' },
      { eval: TILE('cfo-tile-open'), as: 'open' },
      { eval: TILE('cfo-tile-coverage'), as: 'coverage' },
      { eval: TILE('cfo-tile-spend'), as: 'spend' },
      { eval: "(document.getElementById('main')||{}).innerText||''", as: 'main' },
      { eval: "[...document.querySelectorAll('#main th')].map(t => t.textContent.trim())", as: 'headers' },
    ]);
  } finally {
    srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  return { server, page };
}

async function run(crmDir) {
  const r = makeResult('cfo/view');

  const full = state(crmDir, 'full');
  const p = full.page, s = full.server;
  if (!s) {
    // a build with no CFO report: what the page shows is still checked
    r.check('full: the CFO tab opened', p.filter === 'cfo', JSON.stringify(p.__pageerrors));
    r.check('the server computes a CFO report for the seeded store', false, 'no cfo report');
    return r;
  }
  r.check('full: the page ran with no script error', (p.__pageerrors || []).length === 0,
    JSON.stringify(p.__pageerrors));
  r.check('full: the CFO tab opened', p.filter === 'cfo', p.filter);
  r.check("full: the cash tile equals the server's bank total",
    cents(p.cash) !== null && cents(p.cash) === s.tiles.cash_usd.value_cents,
    `${JSON.stringify(p.cash)} vs ${s.tiles.cash_usd.value_cents}`);
  r.check("full: the open receivable tile equals the server's QuickBooks open",
    cents(p.open) === s.tiles.open_receivable_usd.value_cents,
    `${JSON.stringify(p.open)} vs ${s.tiles.open_receivable_usd.value_cents}`);
  const cov = s.tiles.realized_margin_coverage;
  r.check("full: the realized coverage tile reads the server's counted of population",
    new RegExp(`\\b${cov.counted} of ${cov.population} jobs`).test(p.coverage || ''),
    `${JSON.stringify(p.coverage)} vs ${cov.counted}/${cov.population}`);
  r.check("full: the window spend tile equals the server's",
    cents(p.spend) === s.tiles.window_spend_usd.value_cents,
    `${JSON.stringify(p.spend)} vs ${s.tiles.window_spend_usd.value_cents}`);
  r.check('full: the four sections render', ['Cash', 'Receivables', 'Margin', 'Expenses']
    .every(h => (p.main || '').includes(h)), (p.main || '').slice(0, 200));
  r.check('full: the PO-costed COLUMN is labelled that it overstates margin',
    (p.headers || []).includes('PO-costed: excludes costs paid directly as expenses, so it overstates margin'),
    JSON.stringify(p.headers));
  r.check('full: an excluded margin shows its reason in words, not a code',
    /cost not billed yet/.test(p.main || '') && !/cost_not_billed_yet/.test(p.main || ''));
  r.check('full: nothing is stale', !/stale/i.test(p.main || ''));

  const none = state(crmDir, 'none');
  r.check('none: the page renders with no script error', (none.page.__pageerrors || []).length === 0
    && none.page.filter === 'cfo', JSON.stringify(none.page.__pageerrors));
  r.check('none: the cash tile says what to load -- the connector or a Balance Sheet export',
    /connector/.test(none.page.cash || '') && /Balance Sheet/.test(none.page.cash || ''),
    JSON.stringify(none.page.cash));
  r.check('none: no tile shows a dollar figure (a missing snapshot is not $0)',
    ['cash', 'open', 'spend'].every(k => cents(none.page[k]) === null),
    JSON.stringify([none.page.cash, none.page.open, none.page.spend]));
  r.check('none: the receivables and spend tiles name the export to load',
    /Invoice List by Date/.test(none.page.open || '') && /Transaction List by Vendor/.test(none.page.spend || ''),
    JSON.stringify([none.page.open, none.page.spend]));

  const stale = state(crmDir, 'stale');
  r.check('stale: the page renders, and a visible stale marker says how old',
    (stale.page.__pageerrors || []).length === 0 && /stale · 30 days old/i.test(stale.page.main || ''),
    (stale.page.main || '').slice(0, 300));

  const part = state(crmDir, 'partial');
  r.check('partial: invoices but no cash -- the cash tile says what to load',
    /connector/.test(part.page.cash || '') && cents(part.page.cash) === null, JSON.stringify(part.page.cash));
  r.check("partial: ... while the open receivable tile still reads the server's figure",
    cents(part.page.open) === part.server.tiles.open_receivable_usd.value_cents, JSON.stringify(part.page.open));
  r.check('partial: the coverage tile names what it counts -- jobs, each with its reason in words',
    /\b4 jobs: cost incomplete\b/.test(part.page.coverage || '') && /\b1 job: no qbo invoice\b/.test(part.page.coverage || ''),
    JSON.stringify(part.page.coverage));
  r.check('partial: no script error', (part.page.__pageerrors || []).length === 0,
    JSON.stringify(part.page.__pageerrors));
  return r;
}

module.exports = { run };

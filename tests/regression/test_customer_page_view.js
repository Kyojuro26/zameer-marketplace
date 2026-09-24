// G5 (0.1.43), through the real click path against a LIVE server.
//
// 1. A customer's Projects table: the footer used to be one "Total" that
//    summed every project -- lost and pending folded in with won. It is now
//    Won / Pending / Lost totals, each shown only when non-zero, computed from
//    the rows on the page (no server metric). Lost revenue is never inside
//    another total.
// 2. "Add lead": typing a name offers the existing customers and leads it
//    matches (case- and whitespace-insensitive; never a vendor, never an
//    archived company). Choosing one creates NO company: the drawer becomes
//    that company's new-project form with status pending. A name with no match
//    adds a lead as before, and the server's unique-name refusal is the
//    backstop when a matching name is saved anyway.
// A separate process re-reads the store after each save. Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const PY_SEED = `
import sys
sys.path.insert(0, sys.argv[1] + "/tests")
from lib.harness import load_server, Store, company, project
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3])
st.reset(companies=[company("ace-manufacturing", "Ace Manufacturing"),
                    company("beta-works", "Beta Works", role="lead"),
                    company("gamma-tooling", "Gamma Tooling", role="vendor"),
                    company("ace-parts", "Ace Parts", archived=True)],
         projects=[project("4521", "ace-manufacturing", status="won", revenue=1000),
                   project("4522", "ace-manufacturing", status="won", revenue=500),
                   project("4523", "ace-manufacturing", status="pending", revenue=2000),
                   project("4524", "ace-manufacturing", status="lost", revenue=4000),
                   project("4525", "ace-manufacturing", status="lost", revenue=None),
                   project("4526", "ace-manufacturing", status="Won ", revenue=250),
                   project("4600", "beta-works", status="pending", revenue=300)])
print("ok")
`;
const PY_READ = "import json,sys,os\n"
  + "d=sys.argv[1]\n"
  + "cs=json.load(open(os.path.join(d,'companies.json')))\n"
  + "ps=json.load(open(os.path.join(d,'projects.json')))\n"
  + "print(json.dumps({'companies':sorted([c['company_id'],c.get('role')] for c in cs),"
  + "'projects':sorted([str(p['project_no']),p.get('company_id'),p.get('status')] for p in ps)}))";
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

const FOOT = "[...document.querySelectorAll('#main tfoot tr[data-total]')].map(t => t.getAttribute('data-total') + '=' + (t.querySelector('td.num')||{}).innerText)";
const FOOTTEXT = "((document.querySelector('#main tfoot')||{}).innerText||'')";
const TYPE = (v) => `(() => { const e = document.getElementById('c_name'); e.value = ${JSON.stringify(v)};
  e.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`;
const MATCHES = "[...document.querySelectorAll('#c_matches [data-match-cid]')].map(b => b.getAttribute('data-match-cid'))";
const OPEN_ADD_LEAD = [{ click: '#filters button[data-f="all"]' }, { wait: 200 },
  { click: '#addrow button[aria-haspopup]' }, { click: '#addrow button[role="menuitem"]:nth-child(3)' }, { wait: 200 }];

async function run(crmDir) {
  const r = makeResult('customer-page/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmcpv-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  let a = {}, b = {}, c = {}, d = {}, d0, d1, d2, d3;
  let srv;
  try {
    execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store], { encoding: 'utf8' });
    const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
    const url = `http://127.0.0.1:${port}/`;
    srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                            '--port', port, '--no-browser'], { stdio: 'ignore' });
    const disk = () => JSON.parse(execFileSync('python3', ['-c', PY_READ, store], { encoding: 'utf8' }));
    execFileSync('python3', ['-c', PY_WAIT, url]);
    d0 = disk();

    // 1. footers
    a = driveUrl(url, [{ wait: 1000 }, { click: '#filters button[data-f="all"]' }, { wait: 200 },
      { eval: "select('ace-manufacturing'), true", as: 's1' }, { wait: 300 },
      { eval: FOOT, as: 'acme' }, { eval: FOOTTEXT, as: 'acmeText' },
      { eval: "select('beta-works'), true", as: 's2' }, { wait: 300 },
      { eval: FOOT, as: 'beta' },
    ]);

    // 2a. typing offers matches; choosing one opens the new-project form, creates no company
    b = driveUrl(url, [{ wait: 1000 }].concat(OPEN_ADD_LEAD, [
      { eval: "(document.getElementById('dtitle')||{}).textContent", as: 'title0' },
      { eval: TYPE('  ace   MANUF'), as: 't1' }, { eval: MATCHES, as: 'm1' },
      { eval: TYPE('gamma'), as: 't2' }, { eval: MATCHES, as: 'mVendor' },
      { eval: TYPE('ace parts'), as: 't3' }, { eval: MATCHES, as: 'mArchived' },
      { eval: TYPE('BETA'), as: 't4' }, { eval: MATCHES, as: 'mLead' },
      { eval: TYPE('Ace'), as: 't5' },
      { click: '#c_matches [data-match-cid="ace-manufacturing"]' }, { wait: 300 },
      { eval: "(document.getElementById('dtitle')||{}).textContent", as: 'title' },
      { eval: "(document.getElementById('n_status')||{}).value", as: 'status' },
      { eval: "!!document.getElementById('n_cid')", as: 'picker' },
    ]));
    d1 = disk();
    c = driveUrl(url, [{ wait: 1000 }].concat(OPEN_ADD_LEAD, [
      { eval: TYPE('Ace'), as: 't' },
      { click: '#c_matches [data-match-cid="ace-manufacturing"]' }, { wait: 300 },
      { fill: '#n_pno', value: '4901' },
      { click: '#saveBtn' }, { wait: 800 },
    ]));
    d2 = disk();

    // 2b. no match: a lead as before; a matching name saved anyway: the server refuses
    d = driveUrl(url, [{ wait: 1000 }].concat(OPEN_ADD_LEAD, [
      { eval: TYPE('Zeta Fabrication'), as: 't1' }, { eval: MATCHES, as: 'mNone' },
      { click: '#saveBtn' }, { wait: 800 },
    ], OPEN_ADD_LEAD, [
      { eval: TYPE('Ace Manufacturing'), as: 't2' },
      { click: '#saveBtn' }, { wait: 800 },
      { eval: "((document.getElementById('savedMsg')||{}).textContent||'')", as: 'dupMsg' },
    ]));
    d3 = disk();
  } catch (err) {
    r.check('the store seeded and the server started', false, String(err).slice(0, 300));
  } finally {
    if (srv) srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const errs = [].concat(a.__pageerrors || [], b.__pageerrors || [], c.__pageerrors || [], d.__pageerrors || []);
  r.check('the page ran with no script error', errs.length === 0, JSON.stringify(errs));

  r.check('the Projects footer shows Won, Pending and Lost separately (a raw "Won " counts as won)',
    JSON.stringify(a.acme) === JSON.stringify(['won=$1,750', 'pending=$2,000', 'lost=$4,000']), JSON.stringify(a.acme));
  r.check('... and no single Total folding them together', !/\bTotal\b/.test(a.acmeText || ''), a.acmeText);
  r.check('a status with nothing in it is not shown (only pending here)',
    JSON.stringify(a.beta) === JSON.stringify(['pending=$300']), JSON.stringify(a.beta));

  r.check('the Add lead form opened', /Add lead/.test(b.title0 || ''), b.title0);
  r.check('typing matches existing companies ignoring case and spacing',
    JSON.stringify(b.m1) === JSON.stringify(['ace-manufacturing']), JSON.stringify(b.m1));
  r.check('a vendor is never offered', JSON.stringify(b.mVendor) === '[]', JSON.stringify(b.mVendor));
  r.check('an archived company is never offered', JSON.stringify(b.mArchived) === '[]', JSON.stringify(b.mArchived));
  r.check('a lead is offered', JSON.stringify(b.mLead) === JSON.stringify(['beta-works']), JSON.stringify(b.mLead));
  r.check("choosing a match opens that company's new-project form, with no picker",
    /New project — Ace Manufacturing/.test(b.title || '') && b.picker === false, JSON.stringify([b.title, b.picker]));
  r.check('... status preset to pending', b.status === 'pending', b.status);
  r.check('... and no company was created by choosing', JSON.stringify(d1 && d1.companies) === JSON.stringify(d0 && d0.companies),
    JSON.stringify(d1 && d1.companies));
  r.check('saving that form creates the project under the existing company, pending',
    d2 && d2.projects.some(p => JSON.stringify(p) === JSON.stringify(['4901', 'ace-manufacturing', 'pending']))
      && JSON.stringify(d2.companies) === JSON.stringify(d0.companies), JSON.stringify(d2));

  r.check('a name with no match offers nothing', JSON.stringify(d.mNone) === '[]', JSON.stringify(d.mNone));
  r.check('... and adds a lead as before', d3 && d3.companies.some(x => JSON.stringify(x) === JSON.stringify(['zeta-fabrication', 'lead'])),
    JSON.stringify(d3 && d3.companies));
  r.check("an existing name saved anyway is refused by the server", /already exists/.test(d.dupMsg || '')
    && d3 && d3.companies.filter(x => x[0] === 'ace-manufacturing').length === 1, JSON.stringify([d.dupMsg, d3 && d3.companies]));
  return r;
}

module.exports = { run };

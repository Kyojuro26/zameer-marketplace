// "+ New project" on the Projects and Live tabs, through the real click path
// against a LIVE server (0.1.43 G3).
//
// local_server.py serves a temp store; headless Chromium opens the new-project
// form from each tab, picks a customer and saves. A SEPARATE process re-reads
// projects.json after each save. What is asserted:
//   * the button is on both tabs, and the "+ Add customer/vendor/lead" row is
//     still hidden there;
//   * the picker lists live customers and leads only -- never a vendor, never
//     an archived company -- sorted by display name, narrowed by typing;
//   * a save lands with the picked company_id; from the Live tab it carries
//     the bucket (default: the legend's first), or none when set to none, and
//     the message says where the job will appear;
//   * a number that already exists is refused with the server's message, and
//     the form keeps what was typed;
//   * a company whose id is 'constructor' works.
// Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const PY_SEED = `
import json, sys
sys.path.insert(0, sys.argv[1] + "/tests")
from pathlib import Path
from lib.harness import load_server, Store, company, project
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3])
st.reset(companies=[company("acme", "Ace Manufacturing"),
                    company("beta", "Beta Works", role="lead"),
                    company("gamma", "Gamma Tooling", role="vendor"),
                    company("delta", "Delta Parts", archived=True),
                    company("constructor", "Constructor Co")],
         projects=[project("4521", "acme", tracker_status="action_admin", description="Guarding")])
(Path(sys.argv[3]) / "tracker_buckets.json").write_text(json.dumps([
    {"key": "action_admin", "label": "Waiting on the office"},
    {"key": "action_owner", "label": "With the rep"},
    {"key": "awaiting_materials", "label": "Waiting on materials"}]))
print("ok")
`;
const PY_READ = "import json,sys,os\n"
  + "ps=json.load(open(os.path.join(sys.argv[1],'projects.json')))\n"
  + "print(json.dumps([[str(p.get('project_no')),p.get('company_id'),p.get('tracker_status')] for p in ps]))";
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

const NEW = '#main button[data-act="new-project"]';
const OPTS = "[...document.querySelectorAll('#n_cid option')].filter(o => o.value).map(o => o.value)";
const SHOWN = "[...document.querySelectorAll('#n_cid option')].filter(o => o.value && !o.hidden).map(o => o.value)";
const TOAST = "((document.getElementById('noticeToast')||{}).textContent||'')";
const MSG = "((document.getElementById('savedMsg')||{}).textContent||'')";
const ADDROW = "(document.getElementById('addrow')||{style:{}}).style.display";
const LIVE_IDS = "[...document.querySelectorAll('#main .lt-card[id]')].map(c => c.id.slice(3))";
const TYPE = (sel, v) => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); e.value = ${JSON.stringify(v)};
  e.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`;

async function run(crmDir) {
  const r = makeResult('new-project/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmnewp-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  let a = {}, b = {}, c = {}, d = {}, e = {}, d1, d2, d3, d4;
  let srv;
  try {
    execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store], { encoding: 'utf8' });
    const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
    const url = `http://127.0.0.1:${port}/`;
    srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                            '--port', port, '--no-browser'], { stdio: 'ignore' });
    const disk = () => JSON.parse(execFileSync('python3', ['-c', PY_READ, store], { encoding: 'utf8' }));
    execFileSync('python3', ['-c', PY_WAIT, url]);
    const projects = [{ wait: 1000 }, { click: '#filters button[data-f="project"]' }, { wait: 300 }];
    const live = [{ wait: 1000 }];

    // 1. Projects tab: the picker, typing to narrow it, a save with a lead
    a = driveUrl(url, projects.concat([
      { eval: ADDROW, as: 'addrowProj' },
      { click: NEW },
      { eval: OPTS, as: 'opts' },
      { eval: TYPE('#n_cfind', 'bet'), as: 't' },
      { eval: SHOWN, as: 'shown' },
      { eval: TYPE('#n_cfind', ''), as: 't2' },
      { click: '#saveBtn' }, { wait: 300 },
      { eval: MSG, as: 'noCustomerMsg' },
      { select: '#n_cid', value: 'beta' },
      { fill: '#n_pno', value: '4901' },
      { click: '#saveBtn' }, { wait: 800 },
      { eval: TOAST, as: 'toast' },
    ]));
    d1 = disk();

    // 2. Live tab: default bucket, a company whose id is 'constructor'
    b = driveUrl(url, live.concat([
      { eval: ADDROW, as: 'addrowLive' },
      { click: NEW },
      { eval: "(document.getElementById('n_bucket')||{}).value", as: 'bucketDefault' },
      { select: '#n_cid', value: 'constructor' },
      { fill: '#n_pno', value: '4902' },
      { click: '#saveBtn' }, { wait: 800 },
      { eval: TOAST, as: 'toast' },
      { eval: LIVE_IDS, as: 'live' },
    ]));
    d2 = disk();

    // 3. Live tab, bucket set to none
    c = driveUrl(url, live.concat([
      { click: NEW },
      { select: '#n_bucket', value: '' },
      { select: '#n_cid', value: 'acme' },
      { fill: '#n_pno', value: '4903' },
      { click: '#saveBtn' }, { wait: 800 },
      { eval: TOAST, as: 'toast' },
      { eval: LIVE_IDS, as: 'live' },
    ]));
    d3 = disk();

    // 4. a number that exists (at another customer) is refused; the form keeps its input
    d = driveUrl(url, projects.concat([
      { click: NEW },
      { select: '#n_cid', value: 'beta' },
      { fill: '#n_pno', value: '4521' },
      { fill: '#n_desc', value: 'Second guarding job' },
      { click: '#saveBtn' }, { wait: 800 },
      { eval: MSG, as: 'msg' },
      { eval: "!!(document.getElementById('drawer')||{classList:{contains:()=>false}}).classList.contains('open')", as: 'open' },
      { eval: "[document.getElementById('n_cid').value, document.getElementById('n_pno').value, document.getElementById('n_desc').value]", as: 'kept' },
    ]));
    d4 = disk();

    // 5. the company page's own button still opens the form for that company, no picker
    e = driveUrl(url, [{ wait: 1000 }, { click: '#filters button[data-f="all"]' }, { wait: 300 },
      { eval: "select('acme'), true", as: 's' }, { wait: 300 },
      { click: '#main button[onclick^="openNewProject(\'acme\'"]' },
      { eval: "!!document.getElementById('n_cid')", as: 'picker' },
      { eval: "(document.getElementById('dtitle')||{}).textContent||''", as: 'title' },
    ]);
  } catch (err) {
    r.check('the store seeded and the server started', false, String(err).slice(0, 300));
  } finally {
    if (srv) srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const errs = [].concat(a.__pageerrors || [], b.__pageerrors || [], c.__pageerrors || [],
                         d.__pageerrors || [], e.__pageerrors || []);
  r.check('the page ran with no script error', errs.length === 0, JSON.stringify(errs));
  const has = (xs, row) => (xs || []).some(x => JSON.stringify(x) === JSON.stringify(row));

  r.check('the "+ Add customer / vendor / lead" row stays hidden on the Projects and Live tabs',
    a.addrowProj === 'none' && b.addrowLive === 'none', JSON.stringify([a.addrowProj, b.addrowLive]));
  r.check('the picker lists live customers and leads, sorted by display name -- no vendor, no archived company',
    JSON.stringify(a.opts) === JSON.stringify(['acme', 'beta', 'constructor']), JSON.stringify(a.opts));
  r.check('typing narrows the picker', JSON.stringify(a.shown) === JSON.stringify(['beta']), JSON.stringify(a.shown));
  r.check('saving with no customer picked says so', /pick a customer/.test(a.noCustomerMsg || ''), a.noCustomerMsg);

  r.check('from the Projects tab: saved under the picked lead, not on the Live screen',
    has(d1, ['4901', 'beta', null]), JSON.stringify(d1));
  r.check('... and the message says it is not on the Live screen', /not on the Live screen/.test(a.toast || ''), a.toast);

  r.check("from the Live tab the bucket defaults to the legend's first", b.bucketDefault === 'action_admin', b.bucketDefault);
  r.check("from the Live tab: saved under 'constructor', in that bucket", has(d2, ['4902', 'constructor', 'action_admin']),
    JSON.stringify(d2));
  r.check('... the message says where it appears', /on the Live screen under Waiting on the office/.test(b.toast || ''), b.toast);
  r.check('... and it is on the Live screen', (b.live || []).includes('constructor::4902'), JSON.stringify(b.live));
  r.check('from the Live tab with the bucket set to none: saved with no bucket', has(d3, ['4903', 'acme', null]),
    JSON.stringify(d3));
  r.check('... the message says so, and it is not on the Live screen',
    /not on the Live screen/.test(c.toast || '') && !(c.live || []).includes('acme::4903'), JSON.stringify([c.toast, c.live]));

  r.check("an existing number at another customer is refused with the server's message",
    /project '4521' already exists/.test(d.msg || ''), d.msg);
  r.check('... the form stays open with what was typed',
    d.open === true && JSON.stringify(d.kept) === JSON.stringify(['beta', '4521', 'Second guarding job']), JSON.stringify(d.kept));
  r.check('... and nothing was written', (d4 || []).filter(x => x[0] === '4521').length === 1, JSON.stringify(d4));

  r.check("the company page's button still opens the form for that company, with no picker",
    e.picker === false && /Ace Manufacturing/.test(e.title || ''), JSON.stringify([e.picker, e.title]));
  return r;
}

module.exports = { run };

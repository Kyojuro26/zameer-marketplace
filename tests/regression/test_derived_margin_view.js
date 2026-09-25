// The project drawer shows profit and margin as the server works them out
// (0.1.44 H4), through the real click path against a LIVE server.
//
// The server now recomputes gross_profit and margin whenever revenue or cost
// changes, and refuses a disagreeing value sent in the same write. The drawer
// used to send all four on every save, so changing revenue there would have
// sent the OLD profit and been refused. It now shows profit and margin
// read-only, sends neither, and shows what the server stored after a save.
// H4b: a stale project opened and saved WITHOUT an edit is corrected -- the
// drawer re-sends revenue and cost, and the server recomputes from them.
// A separate process re-reads projects.json. Generic names only.
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
st.reset(companies=[company("acme", "Ace Manufacturing")],
         projects=[project("4521", "acme", revenue=1000, total_cost=600, gross_profit=400, margin=0.4),
                   project("4522", "acme", revenue=1000, total_cost=600, gross_profit=999, margin=0.9)])
print("ok")
`;
const PY_READ = "import json,sys,os\n"
  + "p=[x for x in json.load(open(os.path.join(sys.argv[1],'projects.json'))) if x['project_no']==sys.argv[2]][0]\n"
  + "print(json.dumps([p.get('revenue'),p.get('gross_profit'),p.get('margin')]))";
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";
const VAL = (id) => `(document.getElementById('${id}')||{}).value`;
const RO = (id) => `!!(document.getElementById('${id}')||{}).readOnly`;

async function run(crmDir) {
  const r = makeResult('derived-margin/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmdm-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  let a = {}, d1, d2, srv;
  try {
    execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store], { encoding: 'utf8' });
    const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
    const url = `http://127.0.0.1:${port}/`;
    srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                            '--port', port, '--no-browser'], { stdio: 'ignore' });
    execFileSync('python3', ['-c', PY_WAIT, url]);
    a = driveUrl(url, [{ wait: 1000 },
      { eval: "openProject('4521','acme'), true", as: 'o' }, { wait: 300 },
      { eval: RO('f_gp'), as: 'roGp' }, { eval: RO('f_margin'), as: 'roMargin' },
      { eval: VAL('f_gp'), as: 'gp0' }, { eval: VAL('f_margin'), as: 'm0' },
      { fill: '#f_revenue', value: '2000' },
      { click: '#saveBtn' }, { wait: 900 },
      { eval: "((document.getElementById('savedMsg')||{}).textContent||'')", as: 'msg' },
      { eval: VAL('f_gp'), as: 'gp1' }, { eval: VAL('f_margin'), as: 'm1' },
      { eval: "closeDrawer(), openProject('4522','acme'), true", as: 'o2' }, { wait: 300 },
      { eval: VAL('f_gp'), as: 'gp2' }, { eval: VAL('f_margin'), as: 'm2' },
      { click: '#saveBtn' }, { wait: 900 },
      { eval: "((document.getElementById('savedMsg')||{}).textContent||'')", as: 'msg3' },
      { eval: VAL('f_gp'), as: 'gp3' }, { eval: VAL('f_margin'), as: 'm3' },
    ]);
    d1 = JSON.parse(execFileSync('python3', ['-c', PY_READ, store, '4521'], { encoding: 'utf8' }));
    d2 = JSON.parse(execFileSync('python3', ['-c', PY_READ, store, '4522'], { encoding: 'utf8' }));
  } catch (err) {
    r.check('the store seeded and the server started', false, String(err).slice(0, 300));
  } finally {
    if (srv) srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  r.check('the page ran with no script error', (a.__pageerrors || []).length === 0, JSON.stringify(a.__pageerrors));
  r.check('profit and margin are shown read-only: the server works them out', a.roGp === true && a.roMargin === true,
    JSON.stringify([a.roGp, a.roMargin]));
  r.check('... showing the stored values', a.gp0 === '400' && a.m0 === '40', JSON.stringify([a.gp0, a.m0]));
  r.check('changing revenue in the drawer saves, not refused', /Saved/.test(a.msg || ''), a.msg);
  r.check('on disk, read by a separate process: profit and margin recomputed',
    JSON.stringify(d1) === JSON.stringify([2000, 1400, 0.7]), JSON.stringify(d1));
  r.check('... and the drawer shows the recomputed values', a.gp1 === '1400' && a.m1 === '70',
    JSON.stringify([a.gp1, a.m1]));
  r.check('a stale project opens showing its stale profit and margin', a.gp2 === '999' && a.m2 === '90',
    JSON.stringify([a.gp2, a.m2]));
  r.check('saving it without an edit saves', /Saved/.test(a.msg3 || ''), a.msg3);
  r.check('... and on disk, read by a separate process, profit and margin are recomputed',
    JSON.stringify(d2) === JSON.stringify([1000, 400, 0.4]), JSON.stringify(d2));
  r.check('... and the drawer shows the recomputed values', a.gp3 === '400' && a.m3 === '40',
    JSON.stringify([a.gp3, a.m3]));
  return r;
}

module.exports = { run };

// Linking a customer to the vendor record of the same business, through the
// real click path against a LIVE server (0.1.39, Phase C).
//
// local_server.py is started on a temp store; headless Chromium clicks the
// company in the sidebar, opens "Edit company", picks the vendor in the
// linked-vendor control and saves. The company page then shows the vendor as a
// clickable cross-reference, and the vendor page the company. A second company
// trying to link the same vendor sees the server's refusal in the drawer. Then
// a SEPARATE python process re-reads companies.json and changelog.jsonl: the
// link is on disk once, vendors.json untouched, and the refused save wrote
// nothing. Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

function seed(store) {
  fs.mkdirSync(store, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(store, n + '.json'), JSON.stringify(v, null, 2));
  const co = (company_id, display_name, role) => ({ company_id, display_name, role,
    domains: [], locations: [], archived: false });
  w('companies', [co('hmart', 'Harbor Mart', 'customer'), co('beta', 'Beta Works', 'customer'),
                  co('hmart-v', 'Harbor Mart LLC', 'vendor')]);
  w('vendors', [{ company_id: 'hmart-v', display_name: 'Harbor Mart LLC', archived: false }]);
  w('projects', []); w('invoices', []); w('contacts', []); w('shipments', []); w('needs_review', []);
}

const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";
// the separate process that reads what is on disk after the browser is done
const PY_READ = "import json,sys,os\n"
  + "d=sys.argv[1]\n"
  + "cos={c['company_id']:c for c in json.load(open(os.path.join(d,'companies.json')))}\n"
  + "log=[json.loads(l) for l in open(os.path.join(d,'changelog.jsonl'))] if os.path.exists(os.path.join(d,'changelog.jsonl')) else []\n"
  + "print(json.dumps({'hmart':cos['hmart'].get('linked_vendor_id'),'beta':cos['beta'].get('linked_vendor_id'),"
  + "'vendors':open(os.path.join(d,'vendors.json')).read(),"
  + "'log':[[e.get('entity'),e.get('key'),(e.get('fields') or {}).get('linked_vendor_id')] for e in log]}))";

async function run(crmDir) {
  const r = makeResult('entity-links/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmlinkv-'));
  const store = path.join(tmp, 'store');
  seed(store);
  const vendorsBefore = fs.readFileSync(path.join(store, 'vendors.json'), 'utf8');
  const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
  const url = `http://127.0.0.1:${port}/`;
  const srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                                '--port', port, '--no-browser'], { stdio: 'ignore' });
  let got = {};
  try {
    try { execFileSync('python3', ['-c', PY_WAIT, url]); }
    catch (e) { r.check('the live server came up', false, String(e).slice(0, 200)); return r; }
    const LINK_V = "(document.getElementById('xref-vendor')||{}).innerText||''";
    const LINK_C = "(document.getElementById('xref-company')||{}).innerText||''";
    got = driveUrl(url, [
      { wait: 800 },                                        // CRM.detect() reaches the bridge
      { eval: 'CRM.mode', as: 'mode' },
      { click: '#filters button[data-f="all"]' },
      { fill: '#q', value: 'harbor' },
      { click: '#clist .citem >> nth=0' },                  // "Harbor Mart" sorts first
      { eval: "selected", as: 'sel1' },
      { click: '#main .more > button' },
      { click: '#main .more-menu >> text=Edit company' },
      { eval: "[...document.querySelectorAll('#e_co_vendor option')].map(o=>o.value)", as: 'opts' },
      { select: '#e_co_vendor', value: 'hmart-v' },
      { click: '#saveBtn' },
      { wait: 800 },
      { eval: "(document.getElementById('savedMsg')||{}).innerText||''", as: 'msg1' },
      { eval: LINK_V, as: 'xrefVendor' },
      { click: '#xref-vendor' },                            // the cross-reference is clickable
      { wait: 300 },
      { eval: "selected", as: 'sel2' },
      { eval: LINK_C, as: 'xrefCompany' },
      { click: '#xref-company' },
      { wait: 300 },
      { eval: "selected", as: 'sel3' },
      // a second company tries to take the same vendor
      { fill: '#q', value: 'beta' },
      { click: '#clist .citem >> nth=0' },
      { click: '#main .more > button' },
      { click: '#main .more-menu >> text=Edit company' },
      { select: '#e_co_vendor', value: 'hmart-v' },
      { click: '#saveBtn' },
      { wait: 800 },
      { eval: "(document.getElementById('savedMsg')||{}).innerText||''", as: 'msg2' },
      { eval: LINK_V, as: 'betaXref' },
    ]);
  } finally {
    srv.kill();
  }
  await new Promise(res => setTimeout(res, 300));
  const disk = JSON.parse(execFileSync('python3', ['-c', PY_READ, store], { encoding: 'utf8' }));
  fs.rmSync(tmp, { recursive: true, force: true });

  r.check('the page ran with no script error', (got.__pageerrors || []).length === 0,
    JSON.stringify(got.__pageerrors));
  r.check('the page talks to the live server, not embedded data', got.mode === 'http', got.mode);
  r.check('clicking the company in the list opened it', got.sel1 === 'hmart', got.sel1);
  r.check('the drawer offers the vendor records, and "none"',
    JSON.stringify(got.opts) === JSON.stringify(['', 'hmart-v']), JSON.stringify(got.opts));
  r.check('the save went through', /Saved/.test(got.msg1 || ''), JSON.stringify(got.msg1));
  r.check('the company page shows the linked vendor', /Harbor Mart LLC/.test(got.xrefVendor || ''),
    JSON.stringify(got.xrefVendor));
  r.check('... as a link that opens the vendor', got.sel2 === 'hmart-v', got.sel2);
  r.check('the vendor page shows the linked company', /Harbor Mart/.test(got.xrefCompany || '')
    && !/LLC/.test(got.xrefCompany || ''), JSON.stringify(got.xrefCompany));
  r.check('... as a link back to the company', got.sel3 === 'hmart', got.sel3);
  r.check("a second company's save shows the server's refusal, naming the company that holds the vendor",
    /already linked/.test(got.msg2 || '') && /Harbor Mart/.test(got.msg2 || ''), JSON.stringify(got.msg2));
  r.check('... and its page shows no link', !(got.betaXref || ''), JSON.stringify(got.betaXref));
  r.check('on disk, read by a separate process: the link is on the company',
    disk.hmart === 'hmart-v', JSON.stringify(disk.hmart));
  r.check('... the refused company holds none', disk.beta == null, JSON.stringify(disk.beta));
  r.check('... vendors.json is untouched (the vendor side is never stored)',
    disk.vendors === vendorsBefore);
  r.check('... the changelog records the link once, and nothing for the refused save',
    JSON.stringify(disk.log.filter(e => e[0] === 'company')) === JSON.stringify([['company', 'hmart', 'hmart-v']]),
    JSON.stringify(disk.log));
  return r;
}

module.exports = { run };

// The Quotes tab, through the real click path against a LIVE server (0.1.41 E2).
//
// local_server.py serves a temp store seeded with test_quotes.py's fixture;
// headless Chromium opens the Quotes tab. Each list's rows, in order, must equal
// the server's own report, computed by a separate process on the same store.
// Then the inline actions are used as the operator would -- mark a request
// sent, mark an open revision sent, log a revision request with a note, set a
// follow-up -- and after each a separate process re-reads projects.json and the
// changelog. Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const PY_SEED = `
import json, sys
sys.path.insert(0, sys.argv[1] + "/tests"); sys.path.insert(0, sys.argv[1] + "/tests/regression")
from lib.harness import load_server, Store
import test_quotes as T
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3])
T.seed(st)
got = st.call("crm_metrics", report="quotes")
json.dump(((got.get("reports") or {}).get("quotes")) or None, sys.stdout)
`;
const PY_READ = "import json,sys,os\n"
  + "d=sys.argv[1]\n"
  + "ps={p['project_no']:p for p in json.load(open(os.path.join(d,'projects.json')))}\n"
  + "cl=os.path.join(d,'changelog.jsonl')\n"
  + "log=[json.loads(l) for l in open(cl)] if os.path.exists(cl) else []\n"
  + "print(json.dumps({'p':{k:{f:v.get(f) for f in ('quote_sent_on','quote_revisions','next_action_on','next_action','status')} for k,v in ps.items()},"
  + "'log':[[e.get('entity'),e.get('key'),sorted((e.get('fields') or {}).keys())] for e in log]}))";
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";
const KEYS = (list) => `[...document.querySelectorAll('#q-${list} tr[data-key]')].map(t => t.getAttribute('data-key'))`;
const FLAGS = (list) => `[...document.querySelectorAll('#q-${list} tr[data-key]')].map(t => t.getAttribute('data-key') + '=' + (t.querySelector('.q-flag') ? 1 : 0))`;

function isoToday(off) {
  const d = new Date(); d.setDate(d.getDate() + (off || 0));
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

async function run(crmDir) {
  const r = makeResult('quotes/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmqv-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  const server = JSON.parse(execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store],
                                         { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
  const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
  const url = `http://127.0.0.1:${port}/`;
  const srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                                '--port', port, '--no-browser'], { stdio: 'ignore' });
  const disk = () => JSON.parse(execFileSync('python3', ['-c', PY_READ, store], { encoding: 'utf8' }));
  const today = isoToday(0), later = isoToday(10);
  let a = {}, d1, d2, d3, d4;
  try {
    execFileSync('python3', ['-c', PY_WAIT, url]);
    const open = [{ wait: 800 }, { click: '#filters button[data-f="quotes"]' }, { wait: 800 }];
    a = driveUrl(url, open.concat([
      { eval: 'filter', as: 'filter' },
      { eval: KEYS('waiting'), as: 'waiting' },
      { eval: KEYS('sent'), as: 'sent' },
      { eval: KEYS('stale'), as: 'stale' },
      { eval: "(document.getElementById('main')||{}).innerText||''", as: 'main' },
      { click: 'tr[data-key="5001|acme|quote|"] button[data-act="sent"]' },
      { wait: 800 },
      { eval: KEYS('waiting'), as: 'waitingAfter' },
    ]));
    d1 = disk();
    const b = driveUrl(url, open.concat([
      { click: 'tr[data-key="5003|acme|revision|1"] button[data-act="sent"]' }, { wait: 800 },
    ]));
    d2 = disk();
    const c = driveUrl(url, open.concat([
      { fill: 'tr[data-key="5004|acme"] input[data-note]', value: 'four options' },
      { click: 'tr[data-key="5004|acme"] button[data-act="revision"]' }, { wait: 800 },
      { eval: KEYS('waiting'), as: 'waitingRev' },
    ]));
    d3 = disk();
    const e = driveUrl(url, open.concat([
      { fill: 'tr[data-key="5005|acme"] input[data-follow]', value: later },
      { click: 'tr[data-key="5005|acme"] button[data-act="follow"]' }, { wait: 800 },
      { eval: FLAGS('sent'), as: 'sentFlags' },
    ]));
    d4 = disk();
    a.errors = [].concat(a.__pageerrors || [], b.__pageerrors || [], c.__pageerrors || [], e.__pageerrors || []);
    a.waitingRev = c.waitingRev; a.sentFlags = e.sentFlags;
  } finally {
    srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }

  r.check('the page ran with no script error', (a.errors || []).length === 0, JSON.stringify(a.errors));
  r.check('the Quotes tab opened', a.filter === 'quotes', a.filter);
  if (!server) { r.check('the server computes a quotes report', false, 'no quotes report'); return r; }
  const key = (x, withKind) => withKind ? `${x.project_no}|${x.company_id}|${x.kind}|${x.revision_index == null ? '' : x.revision_index}`
                                        : `${x.project_no}|${x.company_id}`;
  r.check("waiting to send: the page's rows, in order, are the server's",
    JSON.stringify(a.waiting) === JSON.stringify(server.waiting_to_send.rows.map(x => key(x, true))),
    JSON.stringify([a.waiting, server.waiting_to_send.rows.map(x => key(x, true))]));
  r.check("sent, awaiting decision: the page's rows, in order, are the server's",
    JSON.stringify(a.sent) === JSON.stringify(server.sent_awaiting_decision.rows.map(x => key(x))),
    JSON.stringify([a.sent, server.sent_awaiting_decision.rows.map(x => key(x))]));
  r.check("stale pending: the page's rows, in order, are the server's",
    JSON.stringify(a.stale) === JSON.stringify(server.stale_pending.rows.map(x => key(x))),
    JSON.stringify([a.stale, server.stale_pending.rows.map(x => key(x))]));
  r.check('the turnaround and win rate are shown with their denominators',
    /measured on \d+ of \d+ quotes/.test(a.main || '') && /won \/ \(won \+ lost\)/.test(a.main || ''),
    (a.main || '').slice(0, 300));

  r.check("'Mark sent' on a request writes today's date as quote_sent_on",
    d1 && d1.p['5001'].quote_sent_on === today, JSON.stringify(d1 && d1.p['5001']));
  r.check('... and the row leaves the waiting list', !(a.waitingAfter || []).includes('5001|acme|quote|'),
    JSON.stringify(a.waitingAfter));
  const revs = (d2 && d2.p['5003'].quote_revisions) || [];
  r.check("'Mark sent' on an open revision dates THAT revision, and leaves the earlier one as it was",
    revs.length === 2 && revs[1].sent_on === today && revs[0].sent_on === '2026-03-31'
      && revs[0].note === 'two more options', JSON.stringify(revs));
  const r4 = (d3 && d3.p['5004'].quote_revisions) || [];
  r.check("'Log revision request' appends a revision requested today, with its note",
    JSON.stringify(r4) === JSON.stringify([{ requested_on: today, note: 'four options' }]), JSON.stringify(r4));
  r.check('... and it appears in the waiting list', (a.waitingRev || []).includes('5004|acme|revision|0'),
    JSON.stringify(a.waitingRev));
  r.check("'Set follow-up' writes next_action_on", d4 && d4.p['5005'].next_action_on === later,
    JSON.stringify(d4 && d4.p['5005']));
  r.check('... and the row is no longer flagged', (a.sentFlags || []).includes('5005|acme=0'),
    JSON.stringify(a.sentFlags));
  const upd = (d4 ? d4.log : []).filter(e => e[0] === 'project');
  r.check('every action went through the server: four project edits in the changelog',
    JSON.stringify(upd.map(e => [e[1], e[2]])) === JSON.stringify([
      ['5001', ['quote_sent_on']], ['5003', ['quote_revisions']],
      ['5004', ['quote_revisions']], ['5005', ['next_action', 'next_action_on']]]),
    JSON.stringify(upd));
  return r;
}

module.exports = { run };

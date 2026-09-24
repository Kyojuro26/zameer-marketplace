// Mark complete, the Completed list and Reopen, through the real click path
// against a LIVE server (0.1.43 G2).
//
// local_server.py serves a temp store; headless Chromium drives the Live
// screen as the operator would. After each action a SEPARATE process re-reads
// projects.json. What is asserted:
//   * Mark complete opens a date defaulting to today; confirming saves it
//     through update_project, and the card leaves the Live screen at once --
//     main pane AND sidebar AND the Live count;
//   * the job appears under Completed, most recent first, with its date, leg
//     stages and collection status, and a count;
//   * Reopen puts it back in its bucket (completed_on null on disk);
//   * a refused date (tomorrow) leaves the card where it was, with the
//     server's error in words;
//   * two customers holding 4521 are completed independently;
//   * a numberless job offers no Mark complete and says why;
//   * the edit drawer shows completed_on;
//   * in demo (embedded) mode the button works for the session.
// Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { buildBundle, makeResult } = require('../lib/view.js');
const { drive, driveUrl } = require('../lib/browser.js');

const PY_SEED = `
import json, sys
sys.path.insert(0, sys.argv[1] + "/tests")
from pathlib import Path
from lib.harness import load_server, Store, company, project, shipment
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3])
st.reset(companies=[company("acme", "Ace Manufacturing"), company("beta", "Beta Works")],
         projects=[project("4521", "acme", tracker_status="action_admin", description="Guarding"),
                   project("4521", "beta", tracker_status="action_admin", description="Frames"),
                   project("4600", "acme", tracker_status="action_owner", description="Conveyor",
                           collection_status="open"),
                   project("4700", "acme", tracker_status="action_admin", description="Retrofit",
                           completed_on="2026-09-01", collection_status="paid"),
                   project("", "acme", tracker_status="action_admin", open_orders_notes="No number yet"),
                   project("4800", "acme", tracker_status="action_admin", description="Blank date",
                           completed_on="  "),
                   project("4810", "acme", tracker_status="action_admin", completed_on=[]),
                   project("4811", "acme", tracker_status="action_admin", completed_on=20260919),
                   project("4812", "acme", tracker_status="action_admin", completed_on="\\ufeff"),
                   project("4813", "acme", tracker_status="action_admin", completed_on=" \\t\\n"),
                   project("4900", None, tracker_status="action_admin", description="No customer")],
         shipments=[shipment("4600-L1", "4600", "acme", stage="Delivered"),
                    shipment("4700-L1", "4700", "acme", stage="Installed")])
(Path(sys.argv[3]) / "tracker_buckets.json").write_text(json.dumps([
    {"key": "action_admin", "label": "Waiting on the office"},
    {"key": "action_owner", "label": "With the rep"},
    {"key": "awaiting_materials", "label": "Waiting on materials"}]))
print("ok")
`;
const PY_READ = "import json,sys,os\n"
  + "d=sys.argv[1]\n"
  + "ps=json.load(open(os.path.join(d,'projects.json')))\n"
  + "print(json.dumps({(p.get('company_id') or '')+'::'+str(p.get('project_no')):"
  + "{'completed_on':p.get('completed_on','<absent>'),'tracker_status':p.get('tracker_status')} for p in ps}))";
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

const CARD = (cid, pno) => `[id="lt-${cid}::${pno}"]`;
const LIVE_IDS = "[...document.querySelectorAll('#main .lt-card[id]')].map(c => c.id.slice(3))";
const SIDE_IDS = "[...document.querySelectorAll('#clist [data-live-key]')].map(c => c.getAttribute('data-live-key'))";
const DONE_IDS = "[...document.querySelectorAll('#lt-completed [data-completed-key]')].map(c => c.getAttribute('data-completed-key'))";
const DONE_HEAD = "((document.querySelector('#lt-completed .lt-head')||{}).innerText||'')";
const COUNT = "((document.getElementById('fc_live')||{}).textContent||'')";
const TEXT = (sel) => `((document.querySelector(${JSON.stringify(sel)})||{}).innerText||'')`;
const BUCKET_OF = (cid, pno) => `(() => { const c = document.querySelector('[id="lt-${cid}::${pno}"]');
  const s = c && c.closest('.lt-section'); return s ? ((s.querySelector('h2')||{}).innerText||'') : null; })()`;

function isoToday(off) {
  const d = new Date(); d.setDate(d.getDate() + (off || 0));
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

async function run(crmDir) {
  const r = makeResult('completed/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmdone-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  const today = isoToday(0), tomorrow = isoToday(1);
  let a = {}, b = {}, c = {}, e = {}, f = {}, emb = {}, d1, d2, d3, d4, d5;
  let srv;
  try {
    execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store], { encoding: 'utf8' });
    // the embedded build first, from the store as seeded
    const bdir = path.join(tmp, 'built');
    fs.mkdirSync(bdir);
    buildBundle(crmDir, store, bdir);
    const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
    const url = `http://127.0.0.1:${port}/`;
    srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                            '--port', port, '--no-browser'], { stdio: 'ignore' });
    const disk = () => JSON.parse(execFileSync('python3', ['-c', PY_READ, store], { encoding: 'utf8' }));
    execFileSync('python3', ['-c', PY_WAIT, url]);
    const open = [{ wait: 1000 }];

    // 1. the screen as it opens; then mark 4600 complete with the default date
    a = driveUrl(url, open.concat([
      { eval: 'filter', as: 'filter' },
      { eval: LIVE_IDS, as: 'live0' }, { eval: SIDE_IDS, as: 'side0' },
      { eval: DONE_IDS, as: 'done0' }, { eval: COUNT, as: 'count0' },
      { eval: TEXT('#lt-completed'), as: 'doneText0' },
      { eval: TEXT(CARD('acme', '')) + " || [...document.querySelectorAll('#main .lt-card')].map(c=>c.innerText).find(t=>t.includes('No number yet')) || ''", as: 'numberless' },
      { eval: `[...document.querySelectorAll('#main .lt-card')].filter(c=>c.innerText.includes('No number yet')).map(c=>!!c.querySelector('button[data-act="complete"]'))`, as: 'numberlessBtn' },
      { eval: `[...document.querySelectorAll('#main .lt-card')].filter(c=>c.innerText.includes('No number yet')).map(c=>!!c.querySelector('.lt-done, [data-act="confirm-complete"]'))`, as: 'numberlessBox' },
      { click: `${CARD('acme', '4600')} button[data-act="complete"]` },
      { eval: `(document.querySelector('${CARD('acme', '4600')} input[data-done]')||{}).value||''`, as: 'defaultDate' },
      { click: `${CARD('acme', '4600')} button[data-act="confirm-complete"]` },
      { wait: 800 },
      { eval: LIVE_IDS, as: 'live1' }, { eval: SIDE_IDS, as: 'side1' },
      { eval: DONE_IDS, as: 'done1' }, { eval: DONE_HEAD, as: 'doneHead1' },
      { eval: COUNT, as: 'count1' },
      { eval: TEXT('[data-completed-key="acme::4600"]'), as: 'row4600' },
      { eval: TEXT('[data-completed-key="acme::4700"]'), as: 'row4700' },
    ]));
    d1 = disk();

    // 2. a refused date: tomorrow, on Ace Manufacturing's 4521
    b = driveUrl(url, open.concat([
      { click: `${CARD('acme', '4521')} button[data-act="complete"]` },
      { fill: `${CARD('acme', '4521')} input[data-done]`, value: tomorrow },
      { click: `${CARD('acme', '4521')} button[data-act="confirm-complete"]` },
      { wait: 800 },
      { eval: LIVE_IDS, as: 'live' },
      { eval: TEXT(CARD('acme', '4521')), as: 'cardText' },
    ]));
    d2 = disk();

    // 3. Beta Works' 4521, completed today; Ace Manufacturing's stays live
    c = driveUrl(url, open.concat([
      { click: `${CARD('beta', '4521')} button[data-act="complete"]` },
      { click: `${CARD('beta', '4521')} button[data-act="confirm-complete"]` },
      { wait: 800 },
      { eval: LIVE_IDS, as: 'live' }, { eval: DONE_IDS, as: 'done' },
    ]));
    d3 = disk();

    // 4. Reopen 4600 from the Completed list: back to its bucket
    e = driveUrl(url, open.concat([
      { click: '[data-completed-key="acme::4600"] button[data-act="reopen"]' },
      { wait: 800 },
      { eval: LIVE_IDS, as: 'live' }, { eval: DONE_IDS, as: 'done' },
      { eval: BUCKET_OF('acme', '4600'), as: 'bucket' },
    ]));
    d4 = disk();

    // 5. the drawer shows completed_on, from the Completed list
    f = driveUrl(url, open.concat([
      { click: '[data-completed-key="acme::4700"] a[data-open]' },
      { wait: 500 },
      { eval: "(document.getElementById('f_done')||{}).value||''", as: 'drawerDone' },
      { fill: '#f_done', value: '2026-08-31' },
      { click: '#saveBtn' },
      { wait: 800 },
    ]));
    d5 = disk();

    // 6. demo mode: the built page, no server behind it
    emb = drive(path.join(bdir, 'view.html'), [
      { wait: 500 },
      { eval: "CRM.mode", as: 'mode' },
      { click: `${CARD('acme', '4600')} button[data-act="complete"]` },
      { click: `${CARD('acme', '4600')} button[data-act="confirm-complete"]` },
      { wait: 400 },
      { eval: LIVE_IDS, as: 'live' }, { eval: DONE_IDS, as: 'done' },
      // review round 2: a project with no customer, and a shared number named without one
      { click: '[id="lt-::4900"] button[data-act="complete"]' },
      { click: '[id="lt-::4900"] button[data-act="confirm-complete"]' },
      { wait: 300 },
      { eval: DONE_IDS, as: 'doneNoCo' },
      { eval: "(() => { const r = embeddedCall('update_project', {project_no: '4521', fields: {notes: 'x'}}); return r; })()", as: 'sharedNoCo' },
      // review round 1: two customers' 4521 in demo mode
      { click: `${CARD('beta', '4521')} button[data-act="complete"]` },
      { click: `${CARD('beta', '4521')} button[data-act="confirm-complete"]` },
      { wait: 400 },
      { eval: LIVE_IDS, as: 'live2' }, { eval: DONE_IDS, as: 'done2' },
    ]);
  } catch (err) {
    r.check('the store seeded, the page built and the server started', false, String(err).slice(0, 300));
  } finally {
    if (srv) srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const errs = [].concat(a.__pageerrors || [], b.__pageerrors || [], c.__pageerrors || [],
                         e.__pageerrors || [], f.__pageerrors || [], emb.__pageerrors || []);
  r.check('the page ran with no script error', errs.length === 0, JSON.stringify(errs));
  r.check('the app opens on the Live screen', a.filter === 'live', a.filter);
  const has = (xs, k) => (xs || []).includes(k);

  // as it opens
  r.check('a completed job (4700) is not on the Live screen', !has(a.live0, 'acme::4700'), JSON.stringify(a.live0));
  const same = (x, y) => JSON.stringify([...(x || [])].sort()) === JSON.stringify([...(y || [])].sort());
  r.check('the Live sidebar lists exactly the main pane\'s numbered jobs', (a.live0 || []).length === 8
    && same(a.side0, a.live0), JSON.stringify([a.side0, a.live0]));
  r.check('... and it is listed under Completed', JSON.stringify(a.done0) === JSON.stringify(['acme::4700', 'acme::4812']),
    JSON.stringify(a.done0));
  r.check('the Live count matches the main pane', String((a.live0 || []).length + 1) === a.count0,
    `${a.count0} vs ${(a.live0 || []).length} numbered cards + 1 numberless`);
  r.check('the numberless job offers no Mark complete', JSON.stringify(a.numberlessBtn) === '[false]',
    JSON.stringify(a.numberlessBtn));
  r.check('... nor a hidden confirm with an empty number behind it', JSON.stringify(a.numberlessBox) === '[false]',
    JSON.stringify(a.numberlessBox));
  r.check('... and says why', /mark(ed)? complete/i.test(a.numberless || ''), a.numberless);
  r.check('a raw completed_on that is not a string (a list, a number) is not a completion, as on the server',
    has(a.live0, 'acme::4810') && has(a.live0, 'acme::4811') && !has(a.done0, 'acme::4810') && !has(a.done0, 'acme::4811'),
    JSON.stringify([a.live0, a.done0]));
  r.check('a completed_on of blanks is not a completion: 4800 is live, not under Completed',
    has(a.live0, 'acme::4800') && !has(a.done0, 'acme::4800'), JSON.stringify([a.live0, a.done0]));

  // mark complete
  r.check('Mark complete opens a date defaulting to today', a.defaultDate === today, a.defaultDate);
  r.check('on disk, read by a separate process: 4600 completed today',
    d1 && d1['acme::4600'].completed_on === today, JSON.stringify(d1 && d1['acme::4600']));
  r.check('... its bucket is kept as provenance', d1 && d1['acme::4600'].tracker_status === 'action_owner');
  r.check('the card leaves the Live screen at once', !has(a.live1, 'acme::4600'), JSON.stringify(a.live1));
  r.check('... and the sidebar still lists exactly the main pane\'s jobs', same(a.side1, a.live1)
    && !has(a.side1, 'acme::4600'), JSON.stringify([a.side1, a.live1]));
  r.check('... and the Live count drops by one', Number(a.count1) === Number(a.count0) - 1,
    `${a.count0} -> ${a.count1}`);
  r.check('Completed lists it first, most recent first',
    JSON.stringify(a.done1) === JSON.stringify(['acme::4600', 'acme::4700', 'acme::4812']), JSON.stringify(a.done1));
  r.check('the Completed heading carries the count', /3 completed/.test(a.doneHead1 || ''), a.doneHead1);
  r.check('a Completed row shows its customer, description and date',
    /Ace Manufacturing/.test(a.row4700 || '') && /Retrofit/.test(a.row4700 || '') && /1 Sep 2026/.test(a.row4700 || ''),
    a.row4700);
  r.check('... its leg stages and its collection status, beside it, not merged',
    /Installed/.test(a.row4700 || '') && /paid/i.test(a.row4700 || ''), a.row4700);

  // refused
  r.check('a refused date leaves the card on the Live screen', has(b.live, 'acme::4521'), JSON.stringify(b.live));
  r.check("... with the server's error in words", /after today/.test(b.cardText || ''), b.cardText);
  r.check('... and nothing on disk', d2 && d2['acme::4521'].completed_on === '<absent>',
    JSON.stringify(d2 && d2['acme::4521']));

  // shared number
  r.check("Beta Works' 4521 completed; Ace Manufacturing's is not",
    d3 && d3['beta::4521'].completed_on === today && d3['acme::4521'].completed_on === '<absent>',
    JSON.stringify(d3 && [d3['beta::4521'], d3['acme::4521']]));
  r.check("... and the screen agrees: Ace Manufacturing's 4521 is live, Beta Works' completed",
    has(c.live, 'acme::4521') && !has(c.live, 'beta::4521') && has(c.done, 'beta::4521'),
    JSON.stringify([c.live, c.done]));

  // reopen
  r.check('Reopen clears completed_on on disk', d4 && d4['acme::4600'].completed_on === null,
    JSON.stringify(d4 && d4['acme::4600']));
  r.check('... and the job is back on the Live screen, in its own bucket',
    has(e.live, 'acme::4600') && e.bucket === 'With the rep' && !has(e.done, 'acme::4600'),
    JSON.stringify([e.bucket, e.done]));

  // drawer
  r.check('the edit drawer shows completed_on', f.drawerDone === '2026-09-01', f.drawerDone);
  r.check('... and corrects it: the saved date is on disk', d5 && d5['acme::4700'].completed_on === '2026-08-31',
    JSON.stringify(d5 && d5['acme::4700']));

  // demo
  r.check('demo mode: the built page runs embedded', emb.mode === 'embedded', emb.mode);
  r.check('demo mode: Mark complete moves the card to Completed for the session',
    !has(emb.live, 'acme::4600') && has(emb.done, 'acme::4600'), JSON.stringify([emb.live, emb.done]));
  r.check('demo mode: a project with no customer can be marked complete', has(emb.doneNoCo, '::4900'),
    JSON.stringify(emb.doneNoCo));
  r.check('demo mode: a shared number named without a customer is refused, as on the server',
    emb.sharedNoCo && emb.sharedNoCo.ok === false, JSON.stringify(emb.sharedNoCo));
  r.check('whitespace is read alike on server and page: a BOM-only value is complete, blanks and tabs are not',
    has(a.done0, 'acme::4812') && !has(a.live0, 'acme::4812') && has(a.live0, 'acme::4813'),
    JSON.stringify([a.live0, a.done0]));
  r.check("demo mode: completing Beta Works' 4521 completes that one, not Ace Manufacturing's",
    has(emb.done2, 'beta::4521') && !has(emb.done2, 'acme::4521') && has(emb.live2, 'acme::4521'),
    JSON.stringify([emb.live2, emb.done2]));
  return r;
}

module.exports = { run };

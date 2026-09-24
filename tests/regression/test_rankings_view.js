// The Rankings tab, through the real click path against a LIVE server (0.1.42 F2).
//
// local_server.py serves a temp store seeded with test_rankings.py's fixture
// and its QuickBooks snapshots; headless Chromium opens the Rankings tab and
// drives every combination of the four selects -- metric x group-by x status
// x year -- by changing the select the way the operator does. After each, the
// table's top row and the concentration line must equal the server's figures
// for that combination, computed by a separate process on the same store. The
// page never ranks: each change must be a new crm_metrics call. Then a
// project row and a customer row are clicked through to their drawers.
// Generic names only.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');
const { makeResult } = require('../lib/view.js');
const { driveUrl } = require('../lib/browser.js');

const METRICS = ['quoted_revenue', 'quoted_gross_profit', 'quoted_margin_pct',
                 'qbo_invoiced', 'po_costed_margin_pct', 'project_count'];
const GROUPS = ['customer', 'project', 'year', 'owner'];
const STATUSES = ['won', 'pending', 'lost', 'all'];
const YEARS = ['', '2026', '2025'];

const PY_SEED = `
import json, sys
sys.path.insert(0, sys.argv[1] + "/tests"); sys.path.insert(0, sys.argv[1] + "/tests/regression")
from lib.harness import load_server, Store
import test_rankings as T
srv = load_server(sys.argv[2]); st = Store(srv, sys.argv[3])
T.seed(st)
if callable(getattr(srv, "_save_qbo_snapshot", None)):
    T.snapshots(srv)
out = {}
for m in json.loads(sys.argv[4]):
    for g in json.loads(sys.argv[5]):
        for s in json.loads(sys.argv[6]):
            for y in json.loads(sys.argv[7]):
                kw = dict(report="rankings", metric=m, group_by=g, status=s)
                if y:
                    kw["year"] = int(y)
                rk = (st.call("crm_metrics", **kw).get("reports") or {}).get("rankings")
                if not rk:
                    continue
                top = (rk.get("rows") or [None])[0]
                sh = (top or {}).get(m) or {}
                c = rk.get("concentration") or {}
                out["|".join([m, g, s, y])] = {
                    "key": top and str(top.get("key")),
                    "value": None if sh.get("value") is None
                             else (sh.get("value_cents") if sh.get("unit") == "usd" else sh.get("value")),
                    "rows": len(rk.get("rows") or []),
                    "top5": c.get("top5_share"), "top10": c.get("top10_share")}
json.dump(out, sys.stdout)
`;
const PY_PORT = "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()";
const PY_WAIT = "import sys,time,urllib.request\n"
  + "for _ in range(100):\n"
  + "    try:\n"
  + "        urllib.request.urlopen(sys.argv[1], timeout=1); sys.exit(0)\n"
  + "    except Exception: time.sleep(0.2)\n"
  + "sys.exit(1)";

// In the page: count crm_metrics calls, then walk every combination, changing
// only the selects that differ and waiting for the server's answer to land.
const DRIVE = (combos) => `(async () => {
  const calls = [];
  const orig = CRM.call.bind(CRM);
  CRM.call = (tool, args) => { if (tool === 'crm_metrics') calls.push(JSON.stringify(args)); return orig(tool, args); };
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const ids = {metric: 'rk-metric', group_by: 'rk-group', status: 'rk-status', year: 'rk-year'};
  const out = {}, missing = [];
  for (const [m, g, s, y] of ${JSON.stringify(combos)}) {
    const want = {metric: m, group_by: g, status: s, year: y};
    for (const k of ['metric', 'group_by', 'status', 'year']) {
      const el = document.getElementById(ids[k]);
      if (!el) { missing.push(ids[k]); continue; }
      if (el.value === want[k]) continue;
      const before = calls.length;
      el.value = want[k];
      el.dispatchEvent(new Event('change', {bubbles: true}));
      // until the server's answer for the page's current selection has landed
      let landed = false;
      for (let i = 0; i < 200; i++) {
        const R = DATA.rankings;
        if (calls.length > before && R && R.metric === RK.metric && R.group_by === RK.group_by
            && R.status === RK.status && String(R.year == null ? '' : R.year) === String(RK.year)) { landed = true; break; }
        if (calls.length === before && i >= 60) break;   // no call went out: nothing to wait for
        await sleep(15);
      }
      // a change that never asked the server is already a failure; stop here
      if (calls.length === before) return {out, calls: calls.length, missing: [...new Set(missing)],
                                           silent: [m, g, s, y, k].join('|')};
      // an answer that never matches the selection is a failure too; stop here
      if (!landed) return {out, calls: calls.length, missing: [...new Set(missing)],
                           stuck: [m, g, s, y, k].join('|')};
    }
    const tr = document.querySelector('#rk-table tbody tr[data-key]');
    const td = tr && tr.querySelector('td[data-value]');
    const c = document.getElementById('rk-conc');
    const num = (v) => v === '' || v == null ? null : Number(v);
    out[[m, g, s, y].join('|')] = {
      key: tr ? tr.getAttribute('data-key') : null,
      value: td ? num(td.getAttribute('data-value')) : null,
      rows: document.querySelectorAll('#rk-table tbody tr[data-key]').length,
      top5: c ? num(c.getAttribute('data-top5')) : null,
      top10: c ? num(c.getAttribute('data-top10')) : null,
      shown: [...document.querySelectorAll('.rk-toggles select')].map(x => x.value).join('|')};
  }
  return {out, calls: calls.length, missing: [...new Set(missing)]};
})()`;

async function run(crmDir) {
  const r = makeResult('rankings/view');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmrv-'));
  const store = path.join(tmp, 'm', 'store');
  const repo = path.resolve(__dirname, '..', '..');
  const combos = [];
  for (const m of METRICS) for (const g of GROUPS) for (const s of STATUSES) for (const y of YEARS) combos.push([m, g, s, y]);
  const server = JSON.parse(execFileSync('python3', ['-c', PY_SEED, repo, crmDir, store,
    JSON.stringify(METRICS), JSON.stringify(GROUPS), JSON.stringify(STATUSES), JSON.stringify(YEARS)],
    { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }));
  const port = execFileSync('python3', ['-c', PY_PORT], { encoding: 'utf8' }).trim();
  const url = `http://127.0.0.1:${port}/`;
  const srv = spawn('python3', [path.join(crmDir, 'mcp', 'local_server.py'), '--store', store,
                                '--port', port, '--no-browser'], { stdio: 'ignore' });
  let a = {}, p = {}, c = {};
  try {
    execFileSync('python3', ['-c', PY_WAIT, url]);
    const open = [{ wait: 800 }, { click: '#filters button[data-f="rankings"]' }, { wait: 800 }];
    a = driveUrl(url, open.concat([
      { eval: 'filter', as: 'filter' },
      { eval: DRIVE(combos), as: 'drive' },
    ]));
    // click-through: a project row opens the project drawer, a customer row the company
    p = driveUrl(url, open.concat([
      { select: '#rk-group', value: 'project' }, { wait: 800 },
      { click: '#rk-table tr[data-key="4600|beta"] a' }, { wait: 500 },
      { eval: "(document.getElementById('dtitle')||{}).textContent||''", as: 'title' },
    ]));
    c = driveUrl(url, open.concat([
      { click: '#rk-table tr[data-key="beta"] a' }, { wait: 800 },
      { eval: '[filter, selected]', as: 'where' },
    ]));
  } finally {
    srv.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  const errors = [].concat(a.__pageerrors || [], p.__pageerrors || [], c.__pageerrors || []);
  r.check('the page ran with no script error', errors.length === 0, JSON.stringify(errors));
  r.check('the Rankings tab opened', a.filter === 'rankings', a.filter);
  const d = a.drive || {};
  r.check('the four selects are on the page', d.out && (d.missing || []).length === 0,
    JSON.stringify(d.missing));
  if (!Object.keys(server).length) {
    r.check('the server computes a rankings report', false, 'no rankings report'); return r;
  }
  const got = d.out || {};
  const close = (x, y) => (x == null && y == null) || (x != null && y != null && Math.abs(x - y) < 1e-9);
  let bad = [];
  for (const k of Object.keys(server)) {
    const s = server[k], g = got[k] || {};
    if (!(g.key === s.key && close(g.value, s.value) && g.rows === s.rows
          && close(g.top5, s.top5) && close(g.top10, s.top10) && g.shown === k)) bad.push([k, s, g]);
  }
  r.check(`every one of the ${combos.length} combinations was driven`, Object.keys(got).length === combos.length
    && Object.keys(server).length === combos.length,
    `${Object.keys(got).length} / ${Object.keys(server).length}` + (d.stuck ? `; the answer for ${d.stuck} never matched the selection` : ''));
  r.check("for every combination, the table's top row, its row count and the concentration line are the server's",
    bad.length === 0, JSON.stringify(bad.slice(0, 3)));
  r.check('each change asked the server again -- the page ranks nothing itself',
    !d.silent && (d.calls || 0) >= combos.length - 1,
    d.silent ? `changing ${d.silent} sent no crm_metrics call` : `${d.calls} crm_metrics calls for ${combos.length} combinations`);
  r.check('a project row opens that project', /Project 4600/.test(p.title || ''), p.title);
  r.check("a customer row opens that customer's page",
    JSON.stringify(c.where) === JSON.stringify(['all', 'beta']), JSON.stringify(c.where));
  return r;
}

module.exports = { run };

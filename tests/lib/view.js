// Build the real HTML bundle from a scratch store and run it under node.
//
// Drives the SHIPPED artifact, not the Python source: build_view.py generates
// the page, and several defects lived in the generated JS rather than in the
// template. DATA/CRM/selected are lexical consts inside that bundle, so
// anything a test needs to poke is reached with `ctx.eval(...)`, not by
// assigning onto the sandbox.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { createDocument } = require('./dom.js');

function buildBundle(crmDir, storeDir, outDir) {
  const html = path.join(outDir, 'view.html');
  execFileSync('python3', [path.join(crmDir, 'view', 'build_view.py'),
    '--store', storeDir, '--out', html], { stdio: 'pipe' });
  const src = fs.readFileSync(html, 'utf8');
  const m = /<script[^>]*>([\s\S]*?)<\/script>/.exec(src);
  if (!m) throw new Error('no <script> block in the generated page');
  return { js: m[1], html: src };
}

/**
 * @param {object} opts
 *   crmDir, storeDir, outDir  - paths
 *   mode                      - 'http' (live) or leave unset
 *   onCall(tool, args)        - what CRM.call should resolve to; if omitted,
 *                               calls are recorded and resolve {ok:true}
 */
function launch(opts) {
  const { js } = buildBundle(opts.crmDir, opts.storeDir, opts.outDir);
  const document = createDocument();
  const sandbox = {
    document, console, JSON, Math, Date, String, Number, Array, Object, RegExp,
    Promise, Set, Map, isNaN, parseFloat, parseInt, encodeURIComponent,
    decodeURIComponent, setTimeout: (fn) => { if (opts.runTimers) fn(); },
    clearTimeout, alert: (m) => sandbox.__alerts.push(String(m)),
    confirm: () => (opts.confirm === undefined ? true : opts.confirm),
    window: {
      addEventListener() {}, location: { href: '', search: '' },
      matchMedia: () => ({ matches: false, addEventListener() {} }),
    },
    fetch: () => new Promise(() => {}),          // never resolves by default
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    __alerts: [],
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox, { filename: 'crm-view.js' });

  // Record every tool call and answer it. Patched inside the context because
  // CRM is a lexical const.
  vm.runInContext(`
    globalThis.__calls = [];
    ${opts.mode ? `CRM.mode = ${JSON.stringify(opts.mode)};` : ''}
    CRM.call = function(tool, args){
      globalThis.__calls.push({tool: tool, args: JSON.parse(JSON.stringify(args))});
      return globalThis.__respond(tool, args);
    };
  `, sandbox);
  sandbox.__respond = (tool, args) => {
    if (opts.onCall) {
      const r = opts.onCall(tool, args);
      if (r && typeof r.then === 'function') return r;
      return Promise.resolve(r);
    }
    return Promise.resolve({ ok: true });
  };

  return {
    sandbox,
    el: (id) => document._els[id],
    els: document._els,
    alerts: () => sandbox.__alerts,
    calls: () => sandbox.__calls,
    resetCalls: () => { sandbox.__calls.length = 0; },
    eval: (code) => vm.runInContext(code, sandbox),
    fn: (name) => sandbox[name],          // function declarations are globals
  };
}

// ------------------------------------------------------------------ report --
function makeResult(name) {
  const passed = [], failed = [];
  return {
    name,
    check(label, cond, detail) {
      if (cond) passed.push(label); else failed.push([label, detail || '']);
      return !!cond;
    },
    report() {
      const ok = failed.length === 0;
      console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}  (${passed.length} checks)`);
      for (const [l, d] of failed) console.log(`        x ${l}${d ? '  --  ' + d : ''}`);
      return ok;
    },
  };
}

module.exports = { launch, buildBundle, makeResult };

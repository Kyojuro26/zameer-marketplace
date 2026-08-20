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
    // Prompts are recorded and the answer is settable mid-test, so a test can
    // assert both "was the operator asked?" and "was the answer obeyed?".
    // A confirm that is never asked is the failure mode that matters here.
    confirm: (m) => {
      sandbox.__confirms.push(String(m));
      return sandbox.__confirmReturn;
    },
    // window listeners are RECORDED for the same reason element ones are: a
    // swallowed beforeunload makes its test pass on code that never binds it
    window: {
      _listeners: Object.create(null),
      addEventListener(type, fn) {
        (sandbox.window._listeners[type] || (sandbox.window._listeners[type] = [])).push(fn);
      },
      location: { href: '', search: '' },
      matchMedia: () => ({ matches: false, addEventListener() {} }),
    },
    fetch: () => new Promise(() => {}),          // never resolves by default
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    __alerts: [],
    __confirms: [],
    __confirmReturn: opts.confirm === undefined ? true : opts.confirm,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox, { filename: 'crm-view.js' });

  // Record every tool call and answer it. Patched inside the context because
  // CRM is a lexical const.
  //
  // keepCall: stub the TRANSPORT instead, so the real CRM.call runs. Replacing
  // CRM.call outright means its own dispatch and error handling are never
  // executed by any test -- which is how a version where one rejecting call
  // discarded five good answers passed the suite. Anything asserting how the
  // app behaves when a call FAILS has to take this path; the default is fine
  // for tests that only care which tools were asked for.
  vm.runInContext(`
    globalThis.__calls = [];
    ${opts.mode ? `CRM.mode = ${JSON.stringify(opts.mode)};` : ''}
    ${opts.keepCall ? '' : `CRM.call = function(tool, args){
      globalThis.__calls.push({tool: tool, args: JSON.parse(JSON.stringify(args))});
      return globalThis.__respond(tool, args);
    };`}
  `, sandbox);
  if (opts.keepCall) {
    // http mode's transport. Rejecting here is what a server that does not
    // have the tool actually does to the cowork path, and what a dropped
    // connection does to this one.
    sandbox.fetch = (url, init) => {
      const body = JSON.parse((init && init.body) || '{}');
      sandbox.__calls.push({ tool: body.tool, args: body.args || {} });
      const r = opts.onCall ? opts.onCall(body.tool, body.args || {}) : { ok: true };
      return Promise.resolve(r).then(v => ({ status: 200, json: async () => v }));
    };
  }
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
    confirms: () => sandbox.__confirms,
    resetConfirms: () => { sandbox.__confirms.length = 0; },
    answerConfirm: (v) => { sandbox.__confirmReturn = v; },
    doc: document,
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

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

  // Answer every tool call by stubbing the TRANSPORT, never by replacing
  // CRM.call.
  //
  // Replacing CRM.call was the old approach and it meant CRM.call's own
  // dispatch and error handling were executed by no test at all. A version
  // where one rejecting call discarded five good answers passed the whole
  // suite, because the stub -- not the product -- decided what a failure did.
  // The stub and the app then drifted apart precisely on the behaviour being
  // changed, and the tests kept measuring the stub.
  //
  // Stubbing the transport instead means the real CRM.call runs in every mode,
  // and a rejecting onCall reaches the app exactly as a dead socket or an
  // unknown tool name would. There is no opt-in, because an opt-in is a thing
  // the next person under time pressure forgets to pass.
  vm.runInContext(`
    globalThis.__calls = [];
    ${opts.mode ? `CRM.mode = ${JSON.stringify(opts.mode)};` : ''}
  `, sandbox);

  const respond = (tool, args) => {
    sandbox.__calls.push({ tool, args: JSON.parse(JSON.stringify(args || {})) });
    if (!opts.onCall) return Promise.resolve({ ok: true });
    // A thrown or rejected onCall becomes a rejected transport, which is what
    // the product must survive -- not a resolved {ok:false}.
    let r;
    try { r = opts.onCall(tool, args || {}); } catch (e) { return Promise.reject(e); }
    return Promise.resolve(r);
  };

  // http: CRM.call's own fetch. The one branch every current test exercises.
  sandbox.fetch = (url, init) => {
    const u = String(url || '');
    const body = (() => { try { return JSON.parse((init && init.body) || '{}'); }
                          catch (e) { return {}; } })();
    const tool = u.endsWith('/health') ? 'crm_info' : body.tool;
    // `__status` lets a test drive the HTTP status, which is the only way to
    // reach CRM.call's own 401 branch -- and reaching it is also the proof
    // that the REAL CRM.call ran rather than a stand-in.
    return respond(tool, body.args).then(v => ({
      status: (v && v.__status) || 200, json: async () => v }));
  };
  // cowork and embedded, so onCall is never silently inert in a mode the
  // harness cannot observe. Installed only for the mode under test: `window
  // .cowork` existing at load time would send CRM.detect() down a path no
  // caller asked for.
  if (opts.mode === 'cowork') {
    // TOOL_PREFIX is `let TOOL_PREFIX = null` and is normally set by
    // probeCowork, which never runs here. Pin it to '' so the name the app
    // sends is the tool name -- guessing it back out of a prefixed string is
    // how the recorder ends up logging "nullcrm_info".
    vm.runInContext("TOOL_PREFIX = '';", sandbox);
    sandbox.window.cowork = {
      callMcpTool: (name, args) =>
        respond(String(name), args).then(v => ({ structuredContent: v })),
    };
  } else if (!opts.mode || opts.mode === 'embedded') {
    // embeddedCall is a top-level function declaration, so it is a property of
    // the vm global and can be re-pointed.
    sandbox.__respondEmbedded = (tool, args) => respond(tool, args);
    vm.runInContext('embeddedCall = (t, a) => globalThis.__respondEmbedded(t, a);',
                    sandbox);
  }
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

// The instrument, tested.
//
// Every other module here measures the product. This one measures the thing
// doing the measuring, because a harness that cannot model a behaviour makes
// every test of that behaviour unfalsifiable -- and this suite has now shipped
// two defects that way:
//
//   * the DOM shim recorded only id/type/value, so a data-* baseline read as
//     null and both sides of a send-only-if-changed guard were always equal.
//     The guard shipped broken with a green test.
//   * launch() replaced CRM.call outright, so its dispatch and error handling
//     were executed by NO test. A version where one rejecting call discarded
//     five good answers passed the whole suite, because the stub -- not the
//     product -- decided what a failure did.
//
// Both are the repo's SHAPE 2 (a verifier sharing the bug it should catch),
// one level up. The checks below are the ones that go red if either hole is
// reopened; without them the harness fix is unfalsifiable in exactly the way
// the harness was.
const path = require('path');
const os = require('os');
const fs = require('fs');
const { launch, makeResult } = require('../lib/view.js');

function seedStore(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, v) => fs.writeFileSync(path.join(dir, n + '.json'), JSON.stringify(v));
  w('companies', [{ company_id: 'acme', display_name: 'Ace Manufacturing',
                    role: 'customer', domains: [], locations: [], archived: false }]);
  // po_flag true -> the drawer renders <input type="checkbox" ... checked>,
  // which is the boolean-attribute case
  w('projects', [{ company_id: 'acme', project_no: '4521', status: 'won',
                   year: 2026, archived: false, po_flag: true, revenue: 1000 }]);
  w('shipments', []); w('contacts', []); w('invoices', []);
  w('vendors', []); w('needs_review', []);
  w('tracker_buckets', []); w('tracker_unlinked', []);
  return dir;
}

async function run(crmDir) {
  const r = makeResult('harness');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmharn-'));
  const store = seedStore(path.join(tmp, 'store'));
  const mk = (o) => launch(Object.assign(
    { crmDir, storeDir: store, outDir: tmp }, o));

  // ---- 1. a rejecting transport must reach the PRODUCT ---------------------
  // If the harness answers calls itself, the app's own failure handling is
  // never executed and any assertion about it measures the stub.
  {
    const app = mk({ mode: 'http',
      onCall: (t) => t === 'update_project'
        ? Promise.reject(new Error('socket is dead'))
        : { ok: true } });
    app.eval("openProject('4521');");
    let threw = '';
    try { await app.eval("saveProject('4521')"); }
    catch (e) { threw = String(e).slice(0, 120); }
    r.check('a rejecting transport is handled by the app, not thrown at the test',
      !threw, threw + ' -- CRM.call must be able to reject AND the product '
      + 'must survive it; a throw here means neither was exercised');
    r.check("and the app's own error message is what appears",
      /socket is dead/.test(app.doc.getElementById('savedMsg').textContent),
      `got ${JSON.stringify(app.doc.getElementById('savedMsg').textContent)}`);
  }

  // ---- 2. the REAL CRM.call runs, not a stand-in ---------------------------
  // The 401 branch lives inside CRM.call and nowhere else, so its message can
  // only appear if the product's own dispatch executed.
  {
    const app = mk({ mode: 'http', onCall: () => ({ __status: 401 }) });
    const res = await app.eval("CRM.call('crm_info', {})");
    r.check("CRM.call's own 401 branch is reachable",
      res && res.ok === false && /bridge auth/.test(String(res.error)),
      `got ${JSON.stringify(res)} -- if the harness replaced CRM.call, this `
      + 'branch can never run and every test of a failing call measures a stub');
  }

  // ---- 3. onCall is consulted in EVERY mode -------------------------------
  // Silent inertness is the trap: a mode the harness cannot observe leaves
  // calls() empty while the app mutates anyway, so every negative assertion
  // ("it did NOT call archive_project") passes for free.
  //
  // Each mode is probed inside try/catch ON PURPOSE. If an unobserved mode
  // throws, the module dies before printing a verdict and the runner scores it
  // "harness error -- NO checks were evaluated" -- which is not detection.
  // run_all.py already draws that line for the positive control; the same
  // standard has to hold here, or a hole that manifests as a crash looks
  // indistinguishable from one nothing tests at all.
  for (const mode of [undefined, 'http', 'cowork']) {
    const name = mode || 'embedded (default)';
    let calls = [], err = '';
    try {
      const app = mk({ mode, onCall: () => ({ ok: true }) });
      await app.eval("CRM.call('crm_info', {})");
      calls = app.calls();
    } catch (e) { err = String(e).slice(0, 140); }
    r.check(`onCall is consulted in ${name} mode`,
      !err && calls.some(c => c.tool === 'crm_info'),
      err ? `threw: ${err}` : `calls() = ${JSON.stringify(calls)} -- an `
      + 'unobserved mode leaves calls() empty while the app mutates anyway, so '
      + 'every negative assertion passes vacuously');
  }

  // ---- 4. boolean attributes reach the app as PROPERTIES -------------------
  // The app reads el.checked, never getAttribute('checked'). Parsing the
  // attribute but not setting the property leaves the control just as
  // untestable as before.
  {
    const app = mk({ mode: 'http', onCall: () => ({ ok: true }) });
    app.eval("openProject('4521');");
    const cb = app.el('f_poflag');
    r.check('a checkbox rendered `checked` reads as checked',
      cb && cb.checked === true,
      `got ${cb && JSON.stringify(cb.checked)} -- undefined here puts the `
      + 'PO-on-file flag outside test reach entirely');
    app.resetCalls();
    await app.eval("saveProject('4521')");
    const sent = app.calls().find(c => c.tool === 'update_project');
    r.check('and its true value reaches the payload',
      !!sent && sent.args.fields.po_flag === true,
      `got ${JSON.stringify(sent && sent.args.fields.po_flag)}`);
  }

  // ---- 5. <select> selectedness, both halves of the HTML rule -------------
  {
    const app = mk({ mode: 'http' });
    const d = app.doc.getElementById('probe');
    d.innerHTML = '<select id="s1"><option value="a">a</option>'
                + '<option value="b" selected>b</option>'
                + '<option value="c" selected>c</option></select>'
                + '<select id="s2"><option value="" disabled>choose</option>'
                + '<option value="x">x</option></select>'
                + '<select id="s3"><option>plain</option></select>'
                + '<select id="s4"><option value="a">a</option>'
                + '<option data-note="selected by import" value="b">b</option></select>';
    r.check('the LAST selected option wins, not the first',
      app.el('s1').value === 'c',
      `got ${JSON.stringify(app.el('s1').value)}`);
    r.check('with none selected, the first NON-DISABLED option is chosen',
      app.el('s2').value === 'x',
      `got ${JSON.stringify(app.el('s2').value)} -- "first option" is wrong `
      + 'the moment a disabled placeholder exists, which is one edit away');
    r.check('an option with no value attribute takes its text',
      app.el('s3').value === 'plain',
      `got ${JSON.stringify(app.el('s3').value)} -- two shipped drawers use `
      + 'this form, and "" is a value the server refuses');
    r.check('"selected" inside another attribute\'s VALUE selects nothing',
      app.el('s4').value === 'a',
      `got ${JSON.stringify(app.el('s4').value)} -- matching the whole `
      + 'attribute string lets data-note="selected by import" win');
  }

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

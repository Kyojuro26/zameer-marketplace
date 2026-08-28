// refreshData: what the operator is told when a refresh is not clean.
//
// PRODUCT behaviour, deliberately not in test_harness.js. These checks were
// written there because the harness fix that made them possible landed in the
// same commit -- launch() used to replace CRM.call outright, so a rejecting
// transport never reached the product and nothing here could have been
// asserted at all.
//
// They do not belong there. test_harness.js's subject is the instrument, and
// --positive-control runs the old PLUGIN against the CURRENT tests: the
// instrument is the same one in both runs, so varying the product cannot
// exercise an instrument check. That module is therefore NOT positive-
// controllable, and its evidence is the manual four-defect mutation protocol
// in tests/README.md.
//
// These checks are the opposite -- they fail against BASELINE_REF, which is
// exactly what the positive control is for. Left inside test_harness.js they
// put the name `harness` in the detected list, and a reader takes that as a
// guarantee about the module rather than about six checks inside it. A README
// paragraph cannot outvote a name emitted by the runner. One subject per
// module makes the detected list mean what it says.
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
  const r = makeResult('refresh');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'crmrefresh-'));
  const store = seedStore(path.join(tmp, 'store'));
  const mk = (o) => launch(Object.assign(
    { crmDir, storeDir: store, outDir: tmp }, o));

  // Written middle-case FIRST -- see below.
  //
  // Written middle-case FIRST, because it is the one both previous behaviours
  // got wrong in opposite directions: "any failure discards everything and
  // warns", then "any failure keeps going and says nothing".
  const ALL = {
    list_companies: { ok: true, companies: [{ company_id: 'acme',
      display_name: 'REFRESHED', role: 'customer', archived: false }] },
    find_contacts: { ok: true, contacts: [] },
    list_projects: { ok: true, projects: [{ company_id: 'acme',
      project_no: 'REFRESHED', status: 'won', year: 2026, archived: false }] },
    list_shipments: { ok: true, shipments: [] },
    list_invoices: { ok: true, invoices: [] },
    list_tracker: { ok: true, tracker_buckets: [], tracker_unlinked: [] },
  };
  const pillOf = (a) => a.doc.getElementById('modePill').textContent;

  {   // SOME fail
    const app = mk({ mode: 'http',
      onCall: (t) => t === 'list_projects'
        ? Promise.reject(new Error('socket died'))
        : (ALL[t] || { ok: true }) });
    await app.eval('refreshData()');
    r.check('a partial failure still applies the answers that DID arrive',
      app.eval("String((DATA.companies||[]).map(c=>c.display_name))") === 'REFRESHED',
      'discarding five good answers because one failed was the pre-facb583 '
      + 'behaviour, and it is half of what this is meant to end');
    r.check('and leaves the failed section on its last known data',
      app.eval("String((DATA.projects||[]).map(p=>p.project_no))") !== 'REFRESHED',
      'a failed call must not be applied as though it succeeded');
    r.check('and the pill NAMES what did not refresh',
      /list_projects/.test(pillOf(app)),
      `got ${JSON.stringify(pillOf(app))} -- saying nothing was the 8ec5cac `
      + 'behaviour: seven stale sections under a pill claiming edits persist');
  }

  {   // ALL fail
    const app = mk({ mode: 'http',
      onCall: () => Promise.reject(new Error('transport is dead')) });
    const before = app.eval("String((DATA.companies||[]).map(c=>c.display_name))");
    await app.eval('refreshData()');
    r.check('a total failure updates nothing',
      app.eval("String((DATA.companies||[]).map(c=>c.display_name))") === before,
      'nothing arrived, so nothing may be applied');
    r.check('and says so rather than reporting success',
      /refresh failed|could not refresh/i.test(pillOf(app)),
      `got ${JSON.stringify(pillOf(app))}`);
  }

  {   // NONE fail
    const app = mk({ mode: 'http', onCall: (t) => ALL[t] || { ok: true } });
    await app.eval('refreshData()');
    r.check('a clean refresh applies everything',
      app.eval("String((DATA.companies||[]).map(c=>c.display_name))") === 'REFRESHED');
    r.check('and shows no warning at all',
      !/fail|could not/i.test(pillOf(app)),
      `got ${JSON.stringify(pillOf(app))} -- a warning after a clean refresh `
      + 'trains the operator to ignore the one that matters');
  }

  fs.rmSync(tmp, { recursive: true, force: true });
  return r;
}

module.exports = { run };

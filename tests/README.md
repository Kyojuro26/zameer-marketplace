# Unrivaled CRM test suite

```bash
python3 tests/run_all.py                     # everything; exit 0 only if all green
python3 tests/run_all.py --positive-control  # prove the suite can FAIL
python3 tests/run_all.py -k identifiers      # one module
```

Never shipped: `publish.sh` only rsyncs into `plugins/unrivaled-solutions/`, so
nothing here reaches the plugin package.

## Read this before trusting a green run

The suite this replaced scored **59/59 on a tree with ~40 known defects, and
59/59 after they were fixed**. It could not distinguish the two, so its green
run carried no information.

`--positive-control` extracts the last published release (`BASELINE_REF` in
`run_all.py`) into a temp dir and runs this suite against it. The run
**succeeds only if the suite fails there**. It writes `.positive-control-ran`;
until that file exists, `run_all.py` prints a warning that a green result is
not evidence. Re-run it after any change to the harness, and bump
`BASELINE_REF` only when a version actually ships.

## Layout

| Path | What it protects |
|---|---|
| `lib/harness.py` | scratch stores, real `mcp.call_tool` dispatch, fixtures |
| `lib/dom.js` | DOM shim — `<input type=date>` sanitization, all attributes (valued and boolean), `<select>` selectedness |
| `lib/view.js` | builds the real bundle and runs it under node |
| `regression/test_identifiers.py` | `_key`/`_canon`/`_resolve`; mint vs lookup |
| `regression/test_visibility.py` | what archiving hides, and must never hide |
| `regression/test_integrity.py` | links, cascades, identity, the store layer |
| `regression/test_view.js` | render robustness, date preservation, saves, and what the app offers as clickable. Mutated by `mutate_view.py` (its own decisions) and `mutate_failure.py` (the failure class) |
| `regression/test_livetracker.py` | the fill-colour decode, the legend boundary, unlinked rows, re-import |
| `regression/test_livetracker.js` | the Live screen: lateness flags, adoption, the note |
| `regression/test_project_identity.py` | a project is `(project_no, company_id)`: the optional `company_id` narrows a shared number BEFORE the ambiguity test and only narrows -- number-only calls still refuse, the other customer's twin stays byte-identical, a customer without the number gets "not found", a same-customer duplicate still refuses. Mutated by `mutate_project_identity.py` |
| `regression/test_next_action.py` | the operator's "by when": `next_action` / `next_action_on` round-trip as given, a wrong type or an unreadable date is refused, `list_projects(next_action_due=true)` takes today and earlier and never a lost or archived project, and a re-import (changelog or add-only) leaves both fields untouched. Clock frozen at 2026-08-09. Mutated by `mutate_next_action.py` |
| `regression/test_vendor_match.py` | the vendor a leg's PO text names, by one rule shared by the backfill script and the importer: the LAST non-payment parenthetical is the token ("(70% Paid)", "(PAID)", "(30%)" are skipped), a match is exact on the normalised name or an alias the operator wrote in `vendor_aliases.json`, never a prefix or a guess; a colliding name is ambiguous, an alias naming nobody is reported; report mode lists every leg without a vendor, never one that has one, tables the unmatched tokens, and writes nothing. Mutated by `mutate_vendor_match.py` |
| `regression/test_metrics.py` | every derived number's shape: `counted + Σexcluded == population`, `null` iff nothing counted, a closed exclusion vocabulary, "quoted" on anything profit-shaped, never persisted. Clock frozen at 2026-09-01; every expected figure hand-derived. Mutated by `mutate_metrics.py` |
| `regression/test_harness.js` | **the instrument itself** — the four ways it has been unable to fail, and refreshData's three failure states |
| `shapes/test_shape_*.py` | the three recurring failure shapes |

### Two-fifths of this suite was never in the reported total

Until this was found, `run_all.py`'s summary line read `python: N/N` and the
node modules — **319 checks, 41% of the suite** — were run but not counted.
Every "Suite 430/430", "441/441", "454/454" in this project's history is a
python-only number that was reported as a suite total, including baselines
confirmed on a fresh clone. The JS side could have eroded at any point with the
number never moving.

The lesson is the distinction, not the arithmetic: the existing guard catches a
module that evaluates **nothing** (it is scored "harness error — NO checks were
evaluated"), and catches nothing about a module that quietly evaluates
**less**. A count that is displayed but not totalled is a count nobody is
actually watching.

The headline now reads `python: N/N   node: N/N` with a combined `TOTAL`.

`mutate_failure.py` runs **three** passes over one class rather than one file:
what the app does when a call to the server does not come back. It exists
because of what the audit found — the two call sites that already caught a
rejection were the two that had tests, and the seven that did not were the
seven that had none. **The guarded half was the tested half**, so "which sites
are guarded" was never an independent fact; it was a restatement of which ones
anybody had looked at. Its `test_view.js` pass therefore asserts what the
OPERATOR sees, never that a `catch` exists: one mutant catches the rejection
and reports success, and it must still be killed.

`mutate_livetracker.py` runs **four** passes — normalize.py and merge.py and
server.py against the python module, build_view.py against the node one. The
Live Tracker spans all four files, and a single pass would leave whichever it
did not name resting on its author's confidence.

Two things that pass have to be re-earned, not assumed:

- The node modules **cannot be positive-controlled**. Against `BASELINE_REF`
  the whole bundle dies before any check runs, so `run_all.py` scores them
  "NOT COUNTED" rather than counting a crash as detection. Their evidence is
  the mutation suites, which is why every JS behaviour asserted here has a
  mutant.
- `test_harness.js` **cannot be positive-controlled at all**, and this is
  structural rather than a gap to be closed. `--positive-control` checks out
  the old *plugin* and runs it against the *current* `tests/`, so the
  instrument is the same one in both runs: varying the product cannot exercise
  a check whose subject is the harness. Every check in that module — the DOM
  shim, the transport stub — passes against `BASELINE_REF` and always will,
  and a green result there is not evidence of anything in either direction.
  `harness` must therefore never appear in the positive control's detected
  list; if it does, something that is not an instrument check has been added
  to it.

  This was briefly untrue. The refreshData checks were written into this
  module because the harness fix that made them possible landed in the same
  commit, and they assert PRODUCT behaviour that the baseline fails — so
  `harness` did appear in the detected list, and the guarantee above had to be
  softened to "half". A README paragraph explaining that only part of a module
  is positive-controlled cannot outvote a module NAME emitted by the runner,
  so the fix is the file boundary, not the prose: those checks are now
  `test_refresh.js` and the list says `refresh`. One subject per module is what
  makes the detected list readable as a guarantee.

  This module's evidence is the mutation protocol instead: each of the four
  harness defects it was written for is reintroduced into `lib/dom.js` or
  `lib/view.js`, the suite is run, and each must produce a NAMED red check
  rather than a crash — the same standard `run_all.py` applies when it scores
  a crashing module NOT COUNTED. That protocol is this module's only real
  positive control. Re-run it after any change to `lib/`, and do not take a
  green `--positive-control` as a substitute.
- `test_refresh.js` holds refreshData's three states (some fail, all fail, none
  fail). Product behaviour, positive-controllable, and mutation-covered by the
  REFRESH pass of `mutate_failure.py`.
- The Live Tracker's lateness answers are computed against **today**, so
  `test_livetracker.js` freezes the clock. A test whose expected answers drift
  with the wall clock stops asserting anything the week after it is written.

Two harness rules, both learned expensively:

- Tests drive `server.mcp.call_tool`, not the Python functions underneath.
  Real defects lived in argument validation *ahead* of the function body — a
  `str = None` annotation rejected an explicit `null`, which a direct call
  cannot see.
- `lib/dom.js` implements the HTML date-sanitization algorithm. A shim that
  stores whatever you assign makes every date-wipe test **unable to fail**,
  because the baseline is snapshotted from the control after insertion. An
  earlier harness had exactly that hole and its date tests were decorative.
- The same hole has since appeared twice more, which is why `test_harness.js`
  exists: the shim read only `id`/`type`/`value`, so a `data-*` baseline came
  back `null` and both sides of a send-only-if-changed guard were always equal
  — that guard shipped broken with a green test; and `launch()` replaced
  `CRM.call` outright, so the product's own dispatch and error handling were
  executed by no test, and a version where one rejecting call discarded five
  good answers passed the suite.
- `launch()` stubs the **transport**, never `CRM.call`. `onCall` is consulted
  in every mode, and a rejecting `onCall` reaches the app exactly as a dead
  socket would. There is no opt-in: an opt-in is what the next person under
  time pressure forgets to pass. Return `{__status: 401}` to drive the HTTP
  status, which is the only way to reach `CRM.call`'s bridge-auth branch.

## The three shapes

Nearly every serious defect in this system has been one of three. The
`shapes/` tests assert the *shape*, so a new instance fails here rather than in
the operator's store.

**1 — a guard applied to one entity and not its twin.** Projects got liveness,
ambiguity and falsy-key guards; companies got none. `rename_invoice` grew an
empty-key guard; `rename_project` did not, and its cascade repointed every
unlinked record in the store. `test_shape_parity.py` asserts that *analogous
operations behave the same way*. **Adding a guard to one half of a pair without
the other fails here.**

**2 — a verifier that shares the bug it is meant to catch.** The importer reads
`"NOT PAID"` as paid; the audit built to check it uses the same regex, the same
row caps, and never opens `invoices.json`, so it certified the mistake for five
releases. The PII sweep cannot read the formats a leak arrives in.
`test_shape_verifiers.py` feeds every checking tool something it **must**
reject.

**3 — a stated guarantee nothing enforces.** *"DRAFTS ONLY — nothing here can
send mail"* (a crafted `message_id` sends). *"Anything ambiguous is flagged,
never dropped"* (four silent drop paths). *"Every comparison MUST go through
`_key`"* (nineteen didn't). `test_shape_guarantees.py` turns each promise into
an assertion. If a guarantee is deliberately softened, delete its test in the
same commit — deliberately, rather than finding out later it had quietly
stopped being true.

## Adding tests

- A regression test names the defect and the version it was found in, and must
  fail under `--positive-control`.
- A new guard means a new pair in `test_shape_parity.py`.
- A new checking tool means a new known-bad fixture in
  `test_shape_verifiers.py`.
- A new promise in a docstring means a new assertion in
  `test_shape_guarantees.py` — or don't make the promise.
- Fixtures use generic names only. This repo is **public** and the whole tree
  is swept for client-identifying content.

## Current status

**Green.** The worklist this file used to describe — the receivables file
silently recreated empty, no company-side liveness guard, `archived` writable
as free text, the importer's paid-parsing, the PII sweep's blindness to binary
and UTF-16, the unencoded `message_id` — is closed. Those checks are still
here; they are now regression tests rather than a to-do list.

Green on its own is still not the claim. What makes it mean something:

```bash
python3 tests/run_all.py --positive-control   # must FAIL against BASELINE_REF
python3 tests/mutate_drawer.py                # and the other seven
```

`--positive-control` writes `.positive-control-ran`; until it exists,
`run_all.py` says so and a green result is not evidence. Bump `BASELINE_REF`
only when a version actually ships — not when one is merely tagged in source.

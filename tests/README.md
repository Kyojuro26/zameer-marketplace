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
| `lib/dom.js` | DOM shim — **emulates `<input type=date>` sanitization** |
| `lib/view.js` | builds the real bundle and runs it under node |
| `regression/test_identifiers.py` | `_key`/`_canon`/`_resolve`; mint vs lookup |
| `regression/test_visibility.py` | what archiving hides, and must never hide |
| `regression/test_integrity.py` | links, cascades, identity, the store layer |
| `regression/test_view.js` | render robustness, date preservation, saves |
| `regression/test_livetracker.py` | the fill-colour decode, the legend boundary, unlinked rows, re-import |
| `regression/test_livetracker.js` | the Live screen: lateness flags, adoption, the note |
| `shapes/test_shape_*.py` | the three recurring failure shapes |

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
python3 tests/mutate_drawer.py                # and the other three
```

`--positive-control` writes `.positive-control-ran`; until it exists,
`run_all.py` says so and a green result is not evidence. Bump `BASELINE_REF`
only when a version actually ships — not when one is merely tagged in source.

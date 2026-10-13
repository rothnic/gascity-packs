# Workspace acceptance fixture

This order calculator gives source-composition tests a behavioral oracle. A adds
quantity-aware pricing and B adds shipping costs from the same base. Integration
must retain both. C combines them into a quote, then D formats the receipt.

[requirements.json](requirements.json) contains expected values.
[requirements.py](requirements.py) runs the assertions outside the project
under test. Assertion hashes were frozen before the contribution implementations in
[frozen-requirements.json](frozen-requirements.json). The harness checks those
hashes before and after running the assertions. It never copies the oracle into
an editable worktree.

| Stage | Assertions |
| --- | --- |
| A | Quantity-aware subtotal and empty basket |
| B | Domestic and international shipping |
| AB | All A and B behavior, required before C |
| C | All AB behavior plus domestic, international and empty quotes |
| D | All C behavior plus formatted domestic and international receipts |

The seed project deliberately misses these requirements. Files under `changes/`
are predetermined contributions for deterministic Git tests. Actual worker
acceptance must execute the workflow's workers against the same frozen oracle.

## Commands

Run from the pack checkout with Python 3 and Git. The record helper uses the
repository's existing `jsonschema` dependency. Supply an absolute, new, owned root
on disk-backed scratch. The harness refuses and preserves an existing root.

```sh
python3 gascity/assets/scripts/workspace_acceptance_fixture.py seed --root /abs/new-seed
python3 gascity/assets/scripts/workspace_acceptance_fixture.py exercise --root /abs/new-exercise
python3 gascity/assets/scripts/workspace_acceptance_fixture.py exercise --root /abs/new-bare --topology bare-root
python3 gascity/assets/scripts/workspace_acceptance_fixture.py exercise --root /abs/new-control --topology bare-control-root
```

`seed` creates an ordinary project and, for either bare layout, a local bare
clone. It captures `base_oid`, advances the default branch independently, and
returns the rig and common Git directory. `exercise` adds detached worktrees at
explicit OIDs, merges A then B, and commits C and D in one integration worktree.
Its Git commands use explicit repository paths and isolated Git configuration.
No Git operation uses a source chosen from the caller's current directory.

An actual driver can seed this project, run its own implementation flow, then
call the same oracle against its observed workspace:

```sh
python3 gascity/assets/scripts/workspace_acceptance_fixture.py check --project /abs/worker-workspace --stage D
python3 gascity/assets/scripts/workspace_acceptance_fixture.py check --project /abs/review-workspace --stage D --reviewed-oid "$REVIEWED_OID"
```

`--expected-oid` and `--reviewed-oid` require full lowercase commit OIDs. `check`
reports the observed HEAD, assertion results and before/after cleanliness. Dirty
or changed source, a different expected input or a different reviewed OID fails.
The underlying assertion command's exit code is recorded separately: successful
behavior checks cannot authorize a stale review. Python bytecode writes are
disabled. A failed fixture remains under its root for inspection. The harness
performs no reset, repair or cleanup.

## Refusal canaries

| Case | Required observed failure |
| --- | --- |
| Default-branch bypass | Wrong exact input and missing A/B behavior |
| Premature readiness | A survives, but B shipping is absent before C |
| Ancestry-valid semantic revert | B remains an ancestor, but reverting its behavior breaks shipping, quotes and receipts |
| Stale review | A later commit passes behavior assertions but differs from the reviewed OID |

A canary reports `status: "pass"` only when its specified refusal is observed.
Its `observed.status` remains `"fail"`, with the exact failed assertion names.
The exercise also checks isolated outputs, ordered integration, C/D inputs,
unchanged checkpoints, detached review and record replay/version refusals.

## Evidence and acceptance

The JSON report consumes all 23 names and oracles from the accepted
[scenario catalog](../../../schemas/workspace/scenario-coverage.v1.json).
Cases distinguish `component`, `deterministic-git`, `store-concurrency`,
`native-controller` and `native-worker` evidence. Each group retains named
required native cases with `status: "unrun"` and its needed driver. Explicit
legacy completion and unclassified-asset refusal remain separate cases.

This package runs component and deterministic Git cases. It supplies no metadata
store, lifecycle simulator, formula dispatcher, controller or model worker.
The store race/stress cases need an authorized disposable store and selected
backend/binary qualification. Native cases need actual workspace actions,
formula callers and controllers. The seven end-to-end paths additionally need
authorized real workers. A real Git bare-layout result does not prove native
placement or detached provisioning support.

Results use `pass`, `fail`, `skip` or `unrun`. Failed, skipped, missing-driver or
unrun required cases earn no full-scenario acceptance. A normal exercise exits
zero for its fixture checks. `--require-acceptance` exits nonzero while any
required native case is unrun. `fixture_checks_passed` and `acceptance_passed`
state these separate outcomes.

Reports record the actual pack HEAD and dirty state, fixture/harness/catalog
hashes, Python/Git versions and exact project OIDs. Optional `--core-oid` records
a declared source pin. The declared pin supplies no native execution evidence.
Reports mark native evidence unrun. An actual driver must bind core binary/source,
loaded pack, fixture and store/controller/worker receipts to earn native acceptance. The callable
`seed`, `check_project` and `exercise` functions use the same assertions as the
CLI and are available to that later driver.

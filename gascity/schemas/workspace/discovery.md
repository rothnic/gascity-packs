# Workspace source discovery

The workspace inventory declares the formulas, prompts and helper that own source
work in the five build packs. The discovery command checks the inventory
declarations against the supplied source tree. An added asset or changed binding requires an
explicit migration decision.

The existing contract tests cover `.formula.toml` and Markdown workflow files.
Native formula lookup also accepts canonical `.toml` and legacy `.formula.json`
files. A higher-priority layer can replace a description or check script while
the original formula remains present. The command includes each native format and
explicitly supplied override roots.

## Run the check

From the repository root:

```sh
python3 gascity/assets/scripts/workspace_discovery.py --root .
```

The default [version 1 inventory](affected-surfaces.v1.json) covers Gas City,
Compound Engineering, Superpowers, BMAD and gstack. Supply additional pack or
override roots under the repository root with repeated `--layer` arguments:

```sh
python3 gascity/assets/scripts/workspace_discovery.py --root . \
  --layer local-overrides --layer company-methodology
```

Each layer uses the native `formulas/` and `assets/` layout. In the five default
packs, discovery scans formulas, workflow assets and declared helper paths,
including helper shadows in another pack. Other scripts outside
`assets/workflows/` are outside that default scope. The command checks all assets
in an explicitly supplied layer, including independent scripts. Passing a default
pack again with `--layer` adds that broader asset check.

Missing roots and paths that escape the repository fail. Formula and asset
directory symlinks, including a symlinked `formulas/` root, and dangling links
fail as unresolved inputs. Supply their source directories explicitly.
`--manifest PATH` selects an explicit version 1 inventory.

The JSON report lists `inspected_roots`, `unresolved_inputs`, classification
counts and errors with migration guidance. Success exits 0. Discovery or input
errors exit 1. Invalid CLI arguments exit 2.

Only supplied source roots enter this check. The report keeps
`runtime_verified: false` because the command does not inspect installed layers,
select their priority or launch a workflow. Native composition validation and
workflow acceptance remain separate checks.

## Supported declarations

| Declaration | Result |
| --- | --- |
| `new` | Validate the declared source bindings. |
| `reference` | Validate a planning-only surface. |
| `legacy`, missing or unknown | Reject with explicit migration guidance. |

Owning assets require `new`. A planning reference cannot replace an
implementation, review, fix, publication or continuation owner. The final
Stage B check is the default; `--stage b` is accepted explicitly. Historical
Stage A checks and legacy successes remain evidence only at their original
qualified source. Use that source for historical inspection rather than
relabelling an old run or disabling the final check.

A classification or content hash does not prove runtime migration. Preserve
old runs and follow [migration guidance](../../docs/worktree-dependencies.md#migrate-existing-work).

## Binding checks

For each implementation item formula, the checker retains the source writers
and final commit/checkpoint step.
The bindings cover separate and shared drains in all five packs. Child steps
replace inherited steps as whole steps, as the native formula contract specifies.
Nested children and expansion templates retain their declared prompt paths.

Direct delegators must reach the declared leaf with the matching drain context.
Bare names and native `.toml`, `.formula.toml` and `.formula.json` aliases
identify the same leaf. Inheritance lookup uses those aliases too. Ambiguous
source layers fail, with the supplied name preserved in the diagnostic.
Inherited continuation entrypoints must retain that route. Owning-step bindings
also cover review fixes, direct publish steps and inherited shared-item contracts.
The inventory records an explicit final commit/checkpoint contract for each
separate and shared source owner.

When an asset changes, update its classification, responsibility and hash together
with the affected owning steps and source-owner bindings. Read the actual final
source step before choosing its checkpoint. A newly declared override needs a
matching source binding and native composition review.

This command supplies the closed-inventory check for
[design scenario 18](https://github.com/gastownhall/gascity-packs/issues/209) and
the unclassified-asset check in scenario 19. Scenario 19 requires refusal of
legacy execution at the final source. Historical Stage A legacy success remains
bound to its original source; it is not final-source runtime credit.

Entry formulas declare that selector separately and check their declared source
lifecycle at preflight. The [record contract](README.md) supplies pure mode and
replay validation. Discovery still does not inspect installed priority, capture
run state or prove an end-to-end new run or native legacy-refusal case.

Run the focused regression tests:

```sh
python3 -m unittest discover -s gascity/tests -p test_workspace_discovery.py -v
```

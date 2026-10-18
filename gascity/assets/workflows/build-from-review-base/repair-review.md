This is the `build-from-review-base` repair-review stage.

Read the review report, review verdict, unresolved findings, fix attempt count,
review_mode={{review_mode}}, interaction_mode={{interaction_mode}},
review_fix_formula={{review_fix_formula}}, implementation_target={{implementation_target}},
implementation_formula={{implementation_formula}}, implementation_item_formula={{implementation_item_formula}},
and max_iterations={{max_iterations}} from the workflow root metadata and
artifacts.

If the review verdict is approved, do not mutate code. Record
`gc.build.repair_status=not_needed`, preserve the approved review metadata, and
close this step successfully.

If the review verdict is `changes_required` and review_mode=report, do not
mutate code. Write a repair handoff artifact that names the selected
review_fix_formula, affected requirements, target files or work items when
known, current review report path, and the exact continuation entrypoint to
restart from. Record at least:

- `gc.build.repair_status=repairable`
- `gc.restart.entrypoint=build-from-review`
- `gc.restart.reason=review_changes_required`
- `gc.restart.review_report_path=<review report path>`
- `gc.restart.review_fix_formula={{review_fix_formula}}`
- `gc.restart.implementation_target={{implementation_target}}`
- `gc.restart.worktree_lifecycle={{worktree_lifecycle}}`

Then close this step with failure metadata so the workflow cannot finalize as a
pass without an explicit restart.

If the review verdict is `changes_required` and review_mode is agent or
interactive, run or dispatch the selected review_fix_formula against the
recorded review findings and implementation evidence until one of these happens:

- the implementation is approved;
- review or repair returns blocked;
- max_iterations is exhausted.

For each explicit fix launch and continuation restart, pass
`--var worktree_lifecycle="{{worktree_lifecycle}}"` and retain
`gc.restart.worktree_lifecycle={{worktree_lifecycle}}` in the handoff metadata.
An unsupported source lifecycle blocks repair; never switch modes to proceed.

Record every attempt on the workflow root metadata and in artifacts. On
approval, record `gc.build.repair_status=approved` and the final review report
path. On blocked or exhausted attempts, record `gc.build.repair_status=blocked`
or `gc.build.repair_status=exhausted`, `gc.outcome=fail`,
`gc.failure_class=review_repair_failed`, and restart metadata with
`gc.restart.entrypoint=build-from-review`.

If any prerequisite review artifact, implementation evidence, or selected
formula is missing, do not invent a pass. Record `gc.build.repair_status=blocked`,
`gc.outcome=fail`, `gc.failure_class=review_repair_blocked`,
`gc.restart.entrypoint=build-from-review`, and `gc.restart.reason` with the
machine-readable blocked reason.

Do not close the workflow root with `gc.outcome=pass` from this stage.

Before any explicit child launch, read `WORKTREE_BASE_REF` and `WORKTREE_CHECKS`
from the original native root's `gc.var.worktree_base_ref` and
`gc.var.worktree_checks`. Preserve the exact strings as quoted argument values:
`--var worktree_base_ref="$WORKTREE_BASE_REF"` and
`--var worktree_checks="$WORKTREE_CHECKS"`, together with the recorded lifecycle.
An omitted initial base uses `@default`; an explicitly empty base refuses.
Keep `gc.restart.worktree_base_ref` and `gc.restart.worktree_checks` in any restart
handoff. A child consumes its proven inherited run rather than capturing another base.

Also read the original root's layout and pass it on explicit child launches:

- `WORKTREE_PARENT` from `gc.var.worktree_parent`: `--var worktree_parent="$WORKTREE_PARENT"`.
- `WORKTREE_NAME_PREFIX` from `gc.var.worktree_name_prefix`: `--var worktree_name_prefix="$WORKTREE_NAME_PREFIX"`.
- `WORKTREE_ALLOW_EXTERNAL_PARENT` from `gc.var.worktree_allow_external_parent`: `--var worktree_allow_external_parent="$WORKTREE_ALLOW_EXTERNAL_PARENT"`.

Default only absent parent/prefix keys to empty strings and an absent external
permission key to `false`. Do not substitute rig settings or the child formula's
defaults.

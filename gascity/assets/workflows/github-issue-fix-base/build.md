
Execute the durable implementation and post-implementation review loop for the
generated implementation convoy.

Selected methodology formulas:

- implementation_formula: {{implementation_formula}}
- implementation_item_formula: {{implementation_item_formula}}
- code_review_formula: {{code_review_formula}}
- review_fix_formula: {{review_fix_formula}}

On every explicit implementation, review or fix launch, pass
`--var worktree_lifecycle="{{worktree_lifecycle}}"`. Treat an unsupported
source lifecycle as blocked; never omit or replace the selected value to make
a launch proceed. Native drains retain it through parent runtime variables.

Selector compatibility was validated at the snapshot gate; the effective
interaction mode is recorded as `gc.var.interaction_mode` on the workflow
root. The requested review mode is {{review_mode}}.

The GitHub issue-fix adapter owns run identity, status comments, human gates,
PR publication, and finalization. The selected methodology formulas own only
how implementation work is drained, how code review is produced, and how failed
review findings are fixed.

Start or reuse `{{implementation_formula}}` against the generated
implementation convoy, passing through drain policy {{drain_policy}},
implementation target {{implementation_target}},
implementation_item_formula {{implementation_item_formula}}, and the
normalized interaction mode when the selected formula accepts them. After
implementation completes, launch `{{code_review_formula}}` with the issue-fix
subject and report paths, passing through review_mode {{review_mode}} and the
normalized interaction mode when the selected formula accepts them. If the
review blocks the fix, run `{{review_fix_formula}}` until the review passes or
the workflow reaches its max iteration limit. In `headless` interaction mode,
never ask questions; on missing required input, stop blocked with a
machine-readable `gc.blocked_reason` instead of waiting on a human.

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

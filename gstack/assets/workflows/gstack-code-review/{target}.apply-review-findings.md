Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply
only to explicit `legacy`; the managed instructions govern an admitted `new`
run. Unknown modes or failed reads never authorize legacy fallback.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` fix, read the current canonical and commit-bound
findings through `workspace_outputs.referenced_record`. Report mode cannot
apply fixes. A no-op retains the exact canonical OID and matching approval.
Source or test changes require `workspace_review.fix_plan(canonical, findings,
previous_plan, writer_step_id=..., source_plan_owner_id=..., nodes=...,
terminal_owner_id=..., max_iterations=...)`. Use native IDs and the configured
bounded retry policy. Publish the declared source-plan using
`workspace_source_plan.declare_plan` and `publish_plan` under the current
admitted claim/owner grant. Retain the exact parent generation/OID; do not edit
the accepted canonical checkout in place or replace a newer parent.

Run the selected methodology's native implementation/fix lanes against that
recorded generation. Use the common checkout, result and canonical APIs for
its tested commit and independent review. A changed pass returns `iterate`;
only a later independent review of the new canonical commit can approve.
Preserve artifacts for both generations. Do not rewrite the old accepted
summary, review or receipt. Any missing native route, grant or helper blocks
with original state retained. Existing raw artifact edits below are legacy only.

Apply gstack code-review findings.

Use implementation target {{implementation_target}} for any code changes. Read
the review synthesis from workflow root `gc.build.code_review_report_path`. If
all required review lanes approve, write a no-op review-fix artifact. If
required fixes or missing evidence remain, make the smallest focused changes
and run proof commands. Write the review-fix artifact under the artifact root
and record it on the workflow root as `gc.build.review_fix_summary_path`.

Set `code_review.verdict=done` only when staff, QA evidence, security, and gap
analysis approve, and update workflow root metadata with
`gc.build.code_review_status=approved`. Set `code_review.verdict=iterate` when
required fixes remain, and update workflow root metadata with
`gc.build.code_review_status=draft`.

Always close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<review-fix artifact path>`, and
`code_review.output_path=<review-fix artifact path>`.

Keep edited build artifacts schema-valid. Stage checks and the build gate's final artifact check validate these
Markdown build artifacts, so any edit you make to one must leave it valid:

- The implementation summary at workflow root metadata `gc.build.implementation_summary_path`, schema `gc.build.implementation-summary.v1`:
  front-matter `status` must be one of `draft`, `approved`, `blocked`, or `superseded`.
- The synthesized review report at workflow root metadata `gc.build.code_review_report_path`, schema `gc.build.review.v1`:
  front-matter `status` must be one of `draft`, `questions`, `approved`, `changes_required`, `blocked`, or `superseded`.

When you edit one of them:

- Edit it in place and preserve its YAML front matter: keep `schema`,
  `workflow`, `methodology`, `producer`, and `trace` intact, and keep
  `trace.coverage` and the Markdown `ID`/`Status` coverage table in sync.
- Use only the allowed `status` values listed above. Do not invent statuses
  such as `reviewed`; record review progress in the apply summary and bead
  metadata, not in the artifact's front matter.
- Before closing with `gc.outcome=pass`, from `$GC_RIG_ROOT`, re-run the
  validator on every build artifact you edited and fix every reported error:
  `python3 .gc/scripts/validate_build_artifact.py --schema gc.build.implementation-summary.v1 --path "<implementation summary path>"`.
  `python3 .gc/scripts/validate_build_artifact.py --schema gc.build.review.v1 --path "<review report path>"`.
- On a repeated attempt (`gc.attempt` greater than 1), first read the validator
  errors from `gc.attempt_log` on the loop control bead and repair the
  artifact in place.

Do not invoke provider-native subagents. This Gas City graph lane is the delegation
mechanism for fixes.

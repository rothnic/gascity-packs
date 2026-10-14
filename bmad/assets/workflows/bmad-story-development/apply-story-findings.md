For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
The legacy instructions below retain their existing behavior.

Apply required BMAD story findings.

Retain `worktree_lifecycle` {{worktree_lifecycle}}. `new` requires the composed native helpers and captured policy. For an admitted managed run,
reload the exact run/source-plan/workspace using the imported Gas City
`workspace_checkout.load_workspace_context` API. Retain the verified path
from clean first entry. The clean `workspace_checkout.manage_workspace` path
verifier cannot admit an intermediate committed HEAD. Require recognized
same-member continuation evidence for implement-story and fix commits; if the
composed contract is absent, block with that source preserved. Require
the native claim, admitted owner grant and active `gc.drain_member_id` at the
recorded position/generation. Preserve unexpected dirty state, HEAD drift or
owner mismatch as a blocker. Never fall back to raw `work_dir` metadata.

Apply findings in that workspace. A changed pass makes a focused commit and
returns `iterate` so BMAD self-check and acceptance-audit inspect the changed
commit in the next graph attempt. It cannot accept its own repairs. On the
clean final pass, freeze the actual full `output_oid`; for `no_change` retain
the member's `input_oid` without an empty commit. Include all actual commits
from that input through this final output, including implement-story and fixes.
Construct `workspace_outputs.result_binding(run, plan, workspace,
store_ref=..., member_id=..., output_oid=...)`, then run
`workspace_outputs.execute_checks` for frozen requirement IDs/argv and actual
producer step/session/attempt. Hash the summary under {{artifact_root}}.

The inherited `independent-acceptance` and `record-result` stages consume the
final apply-story-findings commit after the BMAD loop approves. They require
independent review of that exact tested output and use
`workspace_outputs.make_member_result` and `prepare_member_result` with an
admitted recorder. The final shared member also needs an accepted owner-output.
Only committed/replayed native readback permits checkpoint or later closure.
An absent stage, claim, check or review blocks with evidence retained.

The source-anchor procedure below applies only to explicit `legacy`.
Unknown modes and failed managed reads never select legacy.

Make the smallest implementation and test changes needed to resolve required self-check or acceptance-audit findings. If no required findings exist, record a no-op fix result and preserve the review artifact path.

Resolve the source anchor as the workflow root's stamped `gc.source_anchor_id`;
only when the root has none, use the same rules as the do-work `prepare-worktree`
step (for a shared-drain item, the drain member in `gc.drain_member_id`), read
`work_dir` from the source anchor, validate that it is an absolute existing git
worktree, set `WORKTREE` to that path, and `cd "$WORKTREE"` before reading or
editing source files. This step may run in a different session from
implement-story, so resolve the worktree here. If `work_dir` is missing,
invalid, or points at the launcher checkout, fail before editing. `gc.work_dir`
is the launcher rig root, not the implementation worktree; do not edit, test,
or commit in the launcher checkout.

Read the BMAD story self-check and acceptance-audit reports from the current
attempt. Write the fix summary under
`{{artifact_root}}/bmad-story-development/`.

If there are no required findings, perform a no-op pass and close with
`gc.outcome=pass`, `bmad_story.verdict=done`, and
`bmad_story.report_path=<fix summary path>`. Also set
`code_review.verdict=done` and `code_review.report_path=<fix summary path>` so
the inherited implementation-review check can approve the BMAD story loop.

Make any code or test changes in `$WORKTREE`, the same source-anchor worktree
the implement-story step committed in, and commit them there as a focused
commit (`git add` the changed files and `git commit`) so `close-source-anchor`
verifies the fixed code, not only the first attempt. Commit only when
`git status --porcelain` shows changes; on the no-op path do not commit, and
never use `git commit --allow-empty`. Record the fix commit hash in the fix
summary.

If required findings were present and you changed and committed code or tests
to address them, close with `gc.outcome=pass`, `bmad_story.verdict=iterate`, and
`bmad_story.report_path=<fix summary path>`. Also set
`code_review.verdict=iterate` and `code_review.report_path=<fix summary path>`
so the Gas City loop reruns the BMAD self-check and acceptance audit on the
changed worktree. If required findings remain unresolved, close with
`gc.outcome=fail`.

Do not invoke provider-native subagents. This Gas City lane owns the story-fix pass.

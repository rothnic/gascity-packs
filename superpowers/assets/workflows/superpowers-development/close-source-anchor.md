For retained new mode, run `gc gc workspace flow close-source` through the shared native runtime recipe.

Close the Superpowers implementation source anchor.

For retained `worktree_lifecycle` {{worktree_lifecycle}} `new`, require the
exact accepted member-result from `record-result`. Load it through the imported
Gas City `workspace_outputs.referenced_record` API and use
`workspace_outputs.validate_accepted_result` with the exact run/source-plan,
native store, required checks, artifact hashes and current native qualification.
The reviewed full `output_oid` must still equal clean HEAD in the recorded
workspace. Require final owner-output when this is the owner's last member.
The active member must equal `gc.drain_member_id`. Missing, partial, stale,
foreign or unaccepted evidence blocks without closing any source bead.
Close only that original member after committed/replayed result readback.
An already closed member still requires the same evidence on replay.
Preserve unknown state outside worktrees and never adopt raw metadata or
recapture a base.

The fallback rules below apply only to explicit `legacy`.

Resolve `<source-anchor-id>` from the workflow ROOT, which is the SINGLE SOURCE
OF TRUTH for every step of this lane: read the claimed step bead's
`gc.root_bead_id`, then read that root's `gc.source_anchor_id` metadata. The
inherited `prepare-worktree` resolved the anchor deterministically and stamped
it there, so DO NOT re-derive it — close EXACTLY that id.

FALLBACK — only if the root has NO `gc.source_anchor_id` (the shared-drain
`superpowers-development-item` lane, which has no `prepare-worktree`; a
workflow started before the stamp existed; or a hand-run step): read the root's
`gc.input_convoy_id` (if it is missing too, fail this step without closing any
bead) and that convoy with `gc bd show <input-convoy-id> --json`, unwrapping a
one-element list. If the convoy has `gc.synthetic_kind=drain-unit-convoy` use
its `gc.drain_member_id`; else if it has `gc.synthetic=true` use its single
tracked member from `gc convoy status <input-convoy-id> --json` (hard-fail
unless `.children` has exactly one entry); otherwise use the input convoy id
itself. When such an unstamped single-item member has no `work_dir`, a
pre-stamp `prepare-worktree` persisted it on the `gc.synthetic=true` input
convoy: read `work_dir` from that convoy, but still close the member. Never
infer the anchor from dependency ids such as the `prepare-worktree` or
implementation step bead.

Before closing anything, fail this step without closing any bead unless the
resolved source anchor lacks `gc.synthetic=true` and, when the root has
`gc.drain_member_id`, equals it. If the source anchor is already closed with
`gc.outcome=pass` (a retry), do not close it again.

Read `work_dir`, verify the task summary exists, verify the expected task commit
or clean working-tree evidence exists, and confirm the source anchor still
matches the current drained item.

On success, close only the source anchor with `gc.outcome=pass`. Read the
source anchor back and verify it is closed before closing this step. Do not close
the drain-unit convoy, parent convoy, workflow root, or post-implementation
review steps.

Do not invoke provider-native subagents or upstream plugin runtime commands.

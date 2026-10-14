Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply only
to explicit `legacy`; the managed instructions govern an admitted `new` run.
Unknown modes and failed managed reads never authorize legacy fallback.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` decomposition, first validate the captured run
with `workspace_entry.read_entry`. Keep original run input/source anchor
separate from the new implementation convoy. Translate this methodology's
approved source work into the shared tasks.md contract and use the imported
`create_beads_from_tasks.py` managed route with explicit --worktree-lifecycle
new, --city, --store-ref, --workflow-root, --claimed-step, --generation and
native --source-plan-record-id/--authority-id values. Preserve its actual
native IDs, ownership and scheduling dependencies. Source predecessor order
is declared separately in the source-plan; do not infer it from a `needs` edge.

The common `workspace_source_plan.declare_plan` / `publish_plan` APIs publish
one exact source-plan and implementation-convoy binding under an admitted
claim/grant. Require committed/replayed receipt and readback before drain.
Reuse exact records on continuation; artifact text or a closed bead cannot
substitute for accepted output. Unknown creation/publication outcomes require
inspection of the original native request, never duplicate expansion or raw
lifecycle metadata patches. Preserve all methodology approvals/readiness gates.

Create the Superpowers implementation convoy from the approved plan.

Read the approved requirements artifact, the approved Superpowers plan, and any
existing decomposition artifact path. The plan may contain the stock
Superpowers task structure with checkbox steps for test writing, verification,
implementation, and commit. Treat those checkbox steps as execution procedure,
not as task-bead content.

For each `### Task N` section, create one implementation bead containing only
the work unit scope:

- task title and plan section reference
- files to create, modify, or test
- behavior or acceptance criteria covered by this task
- dependencies on earlier tasks, when required
- links to the approved requirements and plan artifacts

Do not copy the plan checkbox steps into the implementation bead. The drained
Superpowers implementation workflow supplies that procedure for each convoy
member.

Hard scoping rule: do not create implementation beads for Superpowers build
lifecycle phases. Skip or reject task sections whose title or scope is prepare,
requirements, brainstorming, written spec, plan, plan-review, decompose,
implementation workflow plumbing, review, finalization, publish, or artifact
validation. Those phases are already upstream or downstream formula steps. If a
plan accidentally includes lifecycle phases as `### Task N` sections, create
beads only for actual source-code work from the original input task or convoy
member and record the skipped lifecycle sections in the decomposition artifact.

Create or update the implementation convoy with those beads and dependency
edges. Record the implementation convoy ID on the workflow root bead as
`gc.input_convoy_id=<implementation-convoy-id>` with
`gc bd update <workflow-root-id> --set-metadata gc.input_convoy_id=<implementation-convoy-id>`.

Write a decomposition artifact that maps every plan task to its bead ID and
dependency edges. Close this step only after the decomposition artifact exists,
the workflow root bead has `gc.input_convoy_id`, and the implementation convoy
is ready for drain before closing.

Do not invoke provider-native subagents or upstream plugin runtime commands.

Artifact validation: this stage is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the artifact recorded at `gc.build.decomposition_path` (fallback `gc.var.decomposition_path`) against schema `gc.build.decomposition.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.

Independently review the exact current output for this original source. Use
the actual `CLAIMED_BEAD_ID` and `GC_SESSION_ID`; your native session must differ
from the output producer. First run this formula's pack helper:
`python3 <pack-helper> verify --bead "$CLAIMED_BEAD_ID"`.

Read the root's pinned `gc.implementation.output_path` and `output_sha256`.
Review the exact receipt, changed files and verification evidence at its full
`output_commit`. Verify the integrated behavior at that exact HEAD using the
frozen `verification_command`; record what you observed. Any changed current
HEAD, input, parent output, receipt bytes, provenance or native attempt blocks
acceptance. Use a separate review worktree at the exact commit when needed; do
not edit the producer's source worktree or repair its output during this review.

Write a durable `gc.build.review.v1` artifact with `status: approved` only after
successful review. Include exact `## Verdict`, `## Findings`, `## Verification`
headings and the schema's coverage table. Front matter must use mappings:
`workflow: {id: <current-workflow-root-id>, formula: do-work}`,
`methodology: {pack: gascity, name: do-work}`, and
`producer: {formula: do-work, stage: independent-acceptance, attempt: <actual-positive-native-attempt>}`.
Its `trace.upstream` must contain exactly one entry for the current output
receipt's absolute path with `hash: sha256:<actual-output-receipt-hash>`.
Other trace entries may document findings. Do not approve a stale root, attempt,
output or merely schema-valid draft/blocked/changes_required report.

Run `python3 <pack-helper> record-acceptance --bead "$CLAIMED_BEAD_ID"
--report "<absolute-review-report-path>"`. The helper validates the existing
schema, approved status, exact output trace, native reviewer/root/stage/attempt,
distinct producer/reviewer sessions and unchanged tested HEAD. It pins an
immutable acceptance receipt and review report on the root.

If findings require changes, write an honest non-approved report and return the
native step's failure; do not record acceptance or publish the source. Close only
your claimed step with `gc.outcome=pass` after successful acceptance publication.
The controller's `managed-acceptance.sh` composes the receipt and schema checks on
the returned subject within the native bounded loop. Never reset budgets, move
branch tips, clean up worktrees or close the workflow root. Git merge needs
separate authority.

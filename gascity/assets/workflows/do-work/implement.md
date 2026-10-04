Before any source read, edit, test, hash or commit, run this formula's pack
helper: `python3 <pack-helper> verify --bead "$CLAIMED_BEAD_ID"`. Require the actual
native current claim and `GC_SESSION_ID`. Read the returned canonical worktree
path, then run `cd "$WORKTREE"` and verify `pwd -P` equals `$WORKTREE`.
Do not edit files in the launcher checkout. The helper revalidates original source
authority, frozen input bytes/location, every accepted parent, all managed source
ownership fields and the exact native provisioning attempt. Do not infer the
source anchor from dependency ids. Plain copied `work_dir` does not prove ownership.

Implement only the source boundary, commit the owned change in this worktree, and
run the frozen input's `verification_command` at the final exact HEAD. Record the
observed result in a durable absolute JSON file:
`{"tested_commit":"<full HEAD SHA>","result":"pass","command":"<exact frozen command>"}`.
Additional evidence fields are allowed. Do not substitute another passing command
or assert a result you did not observe. Recheck HEAD after verification.

Leave the source anchor open for independent acceptance and close-source-anchor.
Write a durable summary outside the disposable worktree. The summary must have
`status: approved`, this workflow root ID, producer formula `do-work`, stage
`implement`, and the actual positive native `gc.attempt`. Its `trace.upstream`
must include the frozen input's exact absolute path and `sha256:<input_sha256>`.

Write or update the task summary with these schema-required body sections,
using the exact `##` headings below in this order:

- `## Summary`
- `## Intended Behavior`
- `## Changed Files`
- `## Verification`
- `## Remaining Risks`

The `## Verification` section must include both the first verification command
and the final proof command, with the observed pass/fail result.

Write the summary as a `gc.build.implementation-summary.v1` artifact and record
its absolute path on the workflow root bead as `gc.implementation.summary_path`
before closing.
Include a Markdown coverage table. The validator only recognizes a table with
an `ID` column and a `Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.implementation-summary.v1`
- `workflow: {id: <workflow-root-id>, formula: do-work}`
- `methodology: {pack: gascity, name: do-work}`
- `producer: {formula: do-work, stage: implement, attempt: <positive integer>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- For the source anchor bead, use `path: beads/<source-anchor-id>` and
  `hash: bead:<source-anchor-id>`. For changed files or upstream build
  artifacts, use repo-relative paths and scheme-qualified hashes such as
  `sha256:<digest>` or `git:<revision>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.


Validate the summary with this pack's `validate_build_artifact.py` before publishing.
Run `python3 <pack-helper> publish-output --bead "$CLAIMED_BEAD_ID" --summary
"<absolute-summary-path>" --verification "<absolute-verification-json>"`.
The helper validates the original schema, approved status, native producer attempt,
exact input trace, tested HEAD, and frozen command; it writes an immutable output
receipt and pins its hash/location on the root. A repeated physical attempt may
publish only identical receipt bytes. A new native repair attempt has a new bead
and receipt; acceptance always names the current pinned output.

Close only this claimed step with `gc.outcome=pass`. The native controller runs
`managed-output.sh` on the returned closed/pass subject, composing exact receipt
checks with `build-artifact-valid.sh`. A failure supplies native `gc.attempt_log`
repair context, within the existing three-attempt bound. Never reset counters,
clean up worktrees, or skip the acceptance dependency. Git merge needs separate
authority. Do not ask questions in headless mode; record unresolved ambiguity and
return failure through the native step.

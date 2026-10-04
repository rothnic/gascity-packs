Prepare only this source's managed worktree. Do not edit source files in the
launcher checkout. Use this formula's resolved pack helper
`assets/scripts/managed_do_work.py`, beside its managed check assets.

1. Get the physical `CLAIMED_BEAD_ID` with `gc hook current --id-only`. Require
   `GC_SESSION_ID`; the helper verifies the current claim, native session and
   `prepare-worktree` stage. Read current step bead metadata `gc.root_bead_id`.
2. Run `python3 <pack-helper> prepare --bead "$CLAIMED_BEAD_ID" --input
   "<absolute-frozen-input-path>"`. Pass rendered `{{input_path}}` as one
   argument when nonempty. When empty, omit `--input`: only a proven original
   source's `gc.implementation.input_path` plus exact `input_sha256` can supply it.
   Missing frozen input fails closed; do not infer a tip, fetch, or use local HEAD.
3. The helper verifies the root's `gc.input_convoy_id` or native source link.
   A `gc.synthetic_kind=drain-unit-convoy` unwraps through `gc.drain_member_id`.
   A `gc.synthetic=true` singleton unwraps through
   `gc convoy status <input-convoy-id> --json`. Never use the synthetic wrapper
   convoy id as `<source-anchor-id>`. Root/source/intake store pins must agree.
   Existing `gc.source_anchor_id` and source `workflow_id` must agree with this
   native relationship; an absent initial link may be published only after proof.
4. The frozen parent set must equal the original source's native blocking
   dependencies, excluding only its proven current workflow root. Every parent
   must have exact native closed/shipped/pass output, an approved receipt from a
   distinct native reviewer, unchanged input/provenance/current HEAD, and commit
   containment in the frozen base. Unresolved or unreviewed blockers fail closed.
5. The helper calls `gc worktree ensure` under the original source ID, exact
   `base_sha`, workflow-root owner, frozen generation and deterministic path
   `<worktree_root>/<source-anchor-id>`. It publishes full managed provenance and
   equal `gc.work_dir`/`work_dir` only on the source. Generated steps do not acquire
   fake source ownership. Existing partial/conflicting ownership fails closed;
   repeat preparation must keep the same input bytes/location and native attempt.
6. Read the result and source/root metadata back. The helper verifies every
   publication. Close only the claimed physical step with `gc.outcome=pass`.
   `managed-prepare.sh` checks the returned closed/pass subject through the native
   bounded loop before implementation becomes ready.

Cancellation, a failed or held root/source, or any closed non-pass root blocks
entry. Never reset native attempts, counters or budgets; never clean up a failed
or canceled worktree to force a retry. Keep context {{context_path}} within the
owned boundary. Retain worktrees and receipts; Git merge needs separate authority.

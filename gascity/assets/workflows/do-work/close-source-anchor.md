Publish only this original source's independently accepted output. First run
this formula's pack helper `verify --bead "$CLAIMED_BEAD_ID"` under the actual
native current claim and `GC_SESSION_ID`. It reads `gc.root_bead_id`, proves the
root's source/intake relationship, and checks `gc.source_anchor_id`; it never
guesses an anchor from a frozen file or a copied plain path.

Run `python3 <pack-helper> close-source --bead "$CLAIMED_BEAD_ID"`.
The helper requires the current output and independent acceptance receipts,
approved schema artifacts, exact hashes/locations, producer and reviewer native
closed/pass returns, distinct sessions, unchanged physical attempts, original
source owner/store, frozen input/parents and current worktree HEAD. A bare
source closed/pass from a legacy caller does not satisfy this publication contract.

The helper uses one native `gc bd update <source-anchor-id> --status closed`
with `gc.outcome=pass`, `gc.work_outcome=shipped`, exact `gc.work_commit`,
`gc.work_verification=<acceptance-path>#sha256:<acceptance-hash>`, and pinned
acceptance path/hash. It reads the source back and requires every field to agree.
A repeat after publication must verify the same exact evidence; it does not
close it again with different output. Do not close this step with pass while the
source anchor remains open or has missing/mismatched publication fields.

Close only this claimed physical step with `gc.outcome=pass` after the readback.
The controller runs `managed-close.sh` on its returned closed/pass subject and
advances through native completion. Do not close the parent/drain convoy or broader
workflow root. Keep all worktrees and receipts. No merge, cleanup, branch reset,
counter edit, budget reset, or failed/canceled-parent exception is part of this
step; separate authority is required for Git merge.

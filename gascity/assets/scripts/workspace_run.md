# Capturing workflow inputs

`workspace_run.py capture` requires an explicit source selector and records the
selected rig, common Git directory, source task, base commit and `new` lifecycle
once. Explicit `@default` selects the verified registered checkout on first
capture; an omitted selector cannot infer the caller's HEAD or working directory.
Repeated capture uses the recorded commit even when a branch moves. Native
source, store and cooked-step checks must still match. Preserve older or
unclassified runs for [explicit migration](../../docs/worktree-dependencies.md#migrate-existing-work).

## Recovering an uncertain publication

- **Original request:** capture saves the exact guarded request before submitting
  it. Its public receipt includes `request_path`; the private packet can contain
  retained attempt credentials and must stay private.
- **Pending scope:** another capture or workflow entry refuses while that run's
  publication is unresolved, including when its record is already visible.
  Changing the working directory or diagnostic directory does not bypass this
  check. The journal belongs to the captured repository, city and store.
- **Readback:** use `workspace_requests.resolve_request(store, request_path)` or
  the installed workflow command's `resolve-write` action. Resolution reads the
  original request; it does not submit another write. Only exact committed or
  replayed readback clears the pending marker.

If readback still reports `unknown`, keep that scope stopped. Retain the
`request_path` and inspect the recorded workspace with `status`. Ask the native
store owner to investigate the original request and any changed rows. Resume
only after exact readback establishes the original result; a changed claim or
visible record alone cannot resolve an uncertain transaction.

## Native record allocation

Workflow entry records the original base commit, configuration and attempt in the
repository's private allocation journal before creating closed, unassigned native
records. A lost create reply blocks another creation in that run's scope, including
from another process or diagnostic directory.

- **Known ID:** supply the original physical ID with `--run-record-id` or
  `--authority-id`. Entry verifies the empty native record, its title and the
  unique description written by the original create command before proceeding.
- **Lost reply:** entry queries the selected native store for the original
  allocation's unique description. Exactly one matching empty, closed,
  unassigned record may be recovered. Missing, ambiguous or malformed results
  remain blocked; entry never repeats that create command.
- **Original source:** recovery keeps the captured base commit when the default
  branch moves. Changed configuration, store or native record identity refuses
  reuse. A completed allocation receipt retains the original row and revision;
  another read cannot replace it with a newer revision.
- **Replacement writer:** a new incarnation of the same physical workflow step
  may resume with its current native claim stamp and the original cooked writer
  map. The allocation intent, base, check policy and original writer provenance
  stay unchanged. The old incarnation is refused. Initial run publication cannot
  move to a different physical step.

These recovery rules apply to workflow entry's run and writer-grant allocation.
The standalone `allocate` action verifies a known native ID; fresh allocation
requires an admitted workflow entry.

## Result and review records

Result, review, canonical and publication records use the same retained native
allocation receipts. When a record already exists, replacement of its writer
grant joins the payload and reference in one guarded transaction. It requires
the exact preceding grant and native occurrence; a different physical writer
needs a closed, declared predecessor. Existing checks and review must still
qualify the exact source commit.

An unresolved original write blocks further allocation and publication in that
scope across process and attempt changes. Resolve its retained request before
continuing. Old allocation receipts without the original writer-map and native
row evidence remain blocked; recovery does not invent missing provenance.

# Capturing workflow inputs

`workspace_run.py capture` records the selected rig, common Git directory, source
task, base commit and lifecycle mode once. Repeated capture uses the recorded
commit even when the default branch moves. Native source, store and cooked-step
checks must still match.

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

## Native record allocation

Workflow entry records the original base commit, configuration and attempt in the
repository's private allocation journal before creating closed, unassigned native
records. A lost create reply blocks another creation in that run's scope, including
from another process or diagnostic directory.

- **Known ID:** supply the original physical ID with `--run-record-id` or
  `--authority-id`. Entry verifies the empty native record, its title and the
  unique description written by the original create command before proceeding.
- **Unknown ID:** inspect the original native creation and retained allocation
  packet. Entry refuses to create a replacement until the original physical ID
  can be identified. It does not manufacture IDs or search an unrelated store.
- **Original source:** recovery keeps the captured base commit when the default
  branch moves. Changed configuration, attempt or native record identity refuses
  reuse.

These recovery rules apply to workflow entry's run and writer-grant allocation.
The standalone `allocate` action verifies a known native ID; fresh allocation
requires an admitted workflow entry.

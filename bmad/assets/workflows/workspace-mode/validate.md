Validate the retained source lifecycle before source access.

Require `worktree_lifecycle` {{worktree_lifecycle}} to be `new` on the cooked
native root and captured run. The native check reads the exact claimed/check
bead and rejects missing, mixed, legacy or conflicting modes. Preserve rejected
state for explicit migration; do not relabel or clear records to bypass it.

Load the exact immutable run reference through the imported
`workspace_outputs.referenced_record` API and compare its retained mode/root
with `workspace_records.verify_run_mode`. Missing helpers, unknown reads or
conflicting references stop source access. Never recapture a base from the
current directory, artifact path or old `work_dir`.

Use the composed imported helpers, current native claim and owner grants.
Source checks do not establish runtime acceptance. Keep native routing and
existing owners intact.

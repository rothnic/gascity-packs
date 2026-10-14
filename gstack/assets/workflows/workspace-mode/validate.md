Validate the retained source lifecycle before source access.

Use `worktree_lifecycle` {{worktree_lifecycle}} from cooked native variables and
the captured run. The native check reads this exact claimed/check bead. Current
methodology source classification is `legacy`, so a request for `new` must fail
before source access. Missing, mixed or conflicting modes fail as well.
Do not change the classification or clear records to bypass the check.

When an immutable run reference is present, load that exact run through the
imported `workspace_outputs.referenced_record` API and compare its retained
mode/root with `workspace_records.verify_run_mode` before selecting either
route. Missing helpers or conflicting references block. Legacy without a run
reference is valid only when no managed workspace/result reference exists.
Do not recapture a base or reinterpret a managed run as legacy.

Managed mode requires the composed imported helpers, native claim/owner guards
and methodology acceptance before activation. A source or schema test supplies
no runtime acceptance. Leave existing native routing and owners intact.

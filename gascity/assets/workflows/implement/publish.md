For `new`, execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Legacy retains its publication policy below.

For a captured `new` run, direct publication requires the exact qualified terminal
result and canonical approval even though the legacy direct workflow has no review
loop. Reuse identical producer evidence through `workspace_review.py` where valid.
Use `workspace_publish.py` and shared publish preflight/push/open-pr steps for
positive existing authority, explicit OID effects and uncertain-response readback.
Missing review/guards blocks; new activation requires composed native acceptance.
For legacy, retain the direct caller-authorization policy below.

If push {{push}} or open_pr {{open_pr}} are explicit opt-ins, publish only
after the direct implementation summary has completed successfully. Resolve the
publish report from summary_path {{summary_path}} when set; otherwise read the
`gc.implementation.summary_path` value recorded by the summarize step in
workflow root metadata. Fail closed if no absolute summary report path is
available.

Direct implement does not run gap-analysis or review loops. Treat this as an
explicit caller authorization to publish the direct implementation result, and
use the same protected-branch, lease-safe push, sanitized PR title/body, and
collision checks as the pack publish helper. If neither push nor open_pr is an
explicit opt-in, close with `gc.outcome=pass` without mutating remotes.

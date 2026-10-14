For `new`, execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Legacy retains its publication policy below.

This is the `build-from-review-base` publish stage.

For a captured `new` run, publication consumes only the exact current canonical OID
approved through `workspace_review.py`. Use `workspace_publish.py` and shared
publish step files for existing authority, intent/readback and response-loss
reconciliation. X approval cannot publish fixed Y. Uncertain Git/PR state preserves
a blocker and never duplicates effects. Missing guards block; new activation still
requires complete native acceptance. Legacy retains the continuation policy below.

Read push {{push}}, open_pr {{open_pr}}, and the finalized continuation outcome
from the workflow root metadata. If neither publishing action is explicitly
authorized, no-op and record `not_published`.

Publishing disabled or no-op status must never convert a blocked, failed, or
repairable finalization into a passing workflow outcome. Preserve
`gc.outcome=fail`, `gc.build.status=blocked`, `gc.failure_class`, and
`gc.restart.*` metadata when finalize recorded them.

If publishing is authorized, publish only after the continuation finalized
successfully and the review stage approved or explicitly allowed publication.
Record push status, PR status, or a blocked publish reason on the workflow root
and publish step before closing.

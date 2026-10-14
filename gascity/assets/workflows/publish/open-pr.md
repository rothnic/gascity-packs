For `new`, execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Legacy retains its publication policy below.

For managed source, keep provider operations in the existing publication adapter.
Require current exact approved Git readback, then reserve one PR creation attempt
through `workspace_publish.reserve_pr_attempt`. Only its first atomic reservation
permits one provider effect. Reconcile lost responses with the same marker/repo/
base/authenticated actor/mode/head OID through `reconcile_publication`. Missing or
ambiguous state remains uncertain and must not create another PR. Persist observed
completion through `prepare_publication_record` with actual provider readback.
Legacy retains the policy below.

If open_pr is {{open_pr}}, create a PR only after push succeeds and sanitized
title/body from final report {{final_report}} pass policy.

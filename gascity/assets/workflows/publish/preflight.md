For `new`, execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Legacy retains its publication policy below.

For a managed `new` run, resolve exact current canonical, approved review and
accepted terminal result through the native adapter. Use
`workspace_publish.publication_intent` and `prepare_publication_record` with the
hashed existing authority decision, frozen remote URL/ref/expected OID and explicit
push/open_pr flags. Require actual project checks and independent approval at that
immutable OID; no dirty source, stale generation or changed artifacts may proceed.
Persist/read back the intent before effects. Missing guards or unresolved response
blocks; current new-mode activation still requires complete native acceptance.
Legacy retains the preflight below.

Validate auth, token scope, remote, branch names, PR base, collision policy,
protected/default targets, sanitized metadata, final report {{final_report}},
push authorization {{push}}, and open_pr authorization {{open_pr}}.

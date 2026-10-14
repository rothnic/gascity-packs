For `new`, execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Legacy retains its publication policy below.

Managed publication uses `workspace_publish.push_publication` with exact native
intent persistence/readback and current canonical lookup. It records uncertainty
before an explicit approved `OID:ref` push with the frozen lease, then observes that
same remote ref. Unknown readback keeps an immutable blocker. An uncertain intent
only reconciles; never push again or substitute a branch tip. No positive authority
means no effect. Preserve protected-target policy and the legacy behavior below.

If push is {{push}}, use create-if-absent or expected-object-id update only.
Fail closed if the remote cannot enforce atomic or lease-checked semantics.

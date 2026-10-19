Execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). It requires the
current approved canonical commit, retained artifacts and explicit authority
for the selected target. Persist the publish intent before effects. An uncertain
response reconciles that same intent and marker before any further action.

If push is {{push}}, use create-if-absent or expected-object-id update only.
Refuse when the remote cannot enforce atomic or lease-checked semantics.

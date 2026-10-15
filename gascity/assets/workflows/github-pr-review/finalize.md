Review only the explicitly identified subject and retained evidence. Artifact
paths describe inputs; they do not select a source checkout or grant source-write
authority. Any source access requires an existing `new` run and verified native
workspace references. Legacy or unclassified work requires explicit migration.
Keep report-only review read-only and preserve the exact reviewed OID.

Read workflow root metadata and write final run metadata containing source bead
id, head SHA, review subject path, review report path, rendered comment path,
GitHub comment id/url, mapped outcome, launch input URL {{github_pr_url}},
artifact root {{artifact_root}}, context path {{context_path}}, post mode
{{post_mode}}, and whether this run reused prior head-SHA output.

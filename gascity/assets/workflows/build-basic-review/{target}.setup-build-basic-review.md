Prepare the build-basic starter factory review.

Gather the requirements artifact, implementation plan, decomposition artifact,
implementation summary, changed-file summaries, task evidence, and verification
commands into one review context file under the build artifact root. Record that
path on the workflow root as `gc.build.code_review_context_path`.

Resolve the exact run, source plan, workspace, terminal accepted result, owner
output and canonical record through the imported `workspace_outputs` helpers.
Validate native qualification and the captured check policy before source access.
Use `workspace_review.begin_canonical_review` with the current native reviewer,
recorded workspace and exact binding; retain its canonical/result hashes and
source snapshot. Every lane reviews that same full canonical output OID.
Artifact paths and old `work_dir` fields do not establish source authority.
Missing or conflicting records stop review for explicit recovery or migration.

Include a `## Canonical Review Subject` section in the context with:

- Exact native run, source-plan, workspace and canonical record references.
- Canonical generation, full output OID and accepted summary hash.
- Verified workspace path and captured required checks.
- Requirements, task evidence, changed files and methodology review reports.

This context describes the validated subject. Each reviewer must revalidate the
current native references and retained snapshot before using its paths. Never
recover a missing checkout from an artifact, a directory name or the launcher.

When writing artifact excerpts, append the actual file contents with commands
such as `cat "$REQUIREMENTS_PATH"` outside any quoted heredoc. Do not write
literal command substitutions such as `$(cat ...)` or `$(date ...)` into the
review context. Before closing this setup bead, verify the generated context
does not contain literal shell substitutions, for example with
`rg -n '\$\((cat|date)' "$CONTEXT_PATH"`; any match is a setup failure to repair
before setting `gc.outcome=pass`.

This starter factory intentionally uses only three review lanes so new users can
see fanout/fanin without a large reviewer roster.

Do not invoke provider-native subagents. Gas City graph lanes are the
delegation mechanism.

Close this setup bead with `gc.outcome=pass` only after the review context path
is recorded.

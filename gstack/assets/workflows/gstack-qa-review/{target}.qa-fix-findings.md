Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` QA fix, read the current canonical OID and the
commit-bound QA findings. Report mode cannot modify source. Missing proof can
be re-run against the same exact commit, with new immutable evidence. Code or
test edits require `workspace_review.fix_plan` with the exact canonical parent,
a committed/replayed source-plan declaration and admitted native fix workspace.
Run the existing gstack implementation/result lanes on that generation. Obtain
its tested accepted owner-output, canonical and independent review before QA
retries. A changed pass returns `iterate`; earlier review, QA and release
reports cannot approve the replacement OID. Do not edit the canonical checkout
or rewrite old evidence. Missing native qualification/route blocks.

Apply gstack QA findings.

Use implementation target {{implementation_target}} for fixes. Fix behavior
defects first, then add or update regression tests. If the QA lane found only
missing evidence, run and record the missing proof instead of changing code.

Write a QA fix artifact under the artifact root.

Close with `gc.outcome=pass` and
`gstack.qa.fix_output_path=<QA fix artifact path>`.

Do not invoke provider-native subagents. This Gas City graph lane is the QA fix
delegation mechanism.

# Plan-review acceptance

The default build and planning review stages accept an approved current plan
only when a passing review names its exact subject. Recording unresolved
findings never authorizes decomposition. The native check allows three attempts;
it records validation errors on the control's `gc.attempt_log` for repair.

Read the native workflow root to locate `gc.build.plan_path` (fallback
`gc.var.plan_path`) and the current requirements path. Resolve relative paths
against the durable rig root, not a disposable worker directory. Locate the
helper relative to the real pack `description_file`: it is
`gascity/assets/scripts/validate_plan_review.py` in a source checkout or the
corresponding installed pack asset. Do not guess a path under the worker's cwd.

Review the original request, plan, and every upstream artifact. The plan must
validate as `gc.build.plan.v1`, belong to this native workflow, and have
`status: approved`. Each `trace.upstream` must name its current bytes with
`sha256:<digest>`, or a full immutable `git:<commit>` whose file content still
matches the current file. Unknown hash schemes, moving Git refs, unavailable
files, and a missing current requirements artifact refuse acceptance.

After reviewing those bytes, obtain their subject without changing them:

```sh
python3 <pack-scripts>/validate_plan_review.py subject \
  --plan <native-recorded-plan-path> \
  --workflow-root <native-workflow-root-id> --artifact-root <durable-rig-root>
```

Copy that JSON object as the YAML `subject` value in the review report. JSON is
valid YAML; preserve every path, hash, declared hash, and upstream entry. This
command captures identity; it does not decide whether the plan deserves approval.

```yaml
---
schema: gc.verdict-report.v1
kind: review
verdict: pass
severity: none
findings: []
subject:
  workflow_root_id: <native-workflow-root-id>
  plan: {path: <absolute-plan-path>, sha256: <current-plan-sha256>}
  upstream:
    - path: <absolute-requirements-path>
      sha256: <current-file-sha256>
      declared_hash: sha256:<current-file-sha256>
---
# Plan review

Describe the review and why the current plan is ready for decomposition.
```

A blocked report instead uses `verdict: fail`, a non-`none` severity, and
structured findings with `id`, `severity`, `title`, `evidence`, and
`required_fix`. Retain the actual findings. Never turn a blocked report into a
passing report just to make a stage close. Respect `review_mode`: report-only
review does not edit the plan, agent review can route authorized repairs, and
interactive review can apply only permitted fixes. Missing headless approval
remains blocked.

Record the absolute report path on the native workflow root:

```sh
gc bd update <native-workflow-root-id> \
  --set-metadata gc.build.plan_review_report_path=<absolute-report-path>
python3 <pack-scripts>/validate_plan_review.py check \
  --plan <native-recorded-plan-path> --report <absolute-report-path> \
  --workflow-root <native-workflow-root-id> --artifact-root <durable-rig-root>
```

Only a successful current-subject check permits `gc.outcome=pass` on the
claimed review step. A failing or unknown review must close with
`gc.outcome=fail` and its concrete reason. If a permitted repair changes the
plan or upstream files, review those new bytes and write their new subject;
old approval remains stale. The native gate repeats this validation using
native-recorded paths, and the task creator repeats it before its first
allocation when the cooked workflow declares the default review requirement.
It does not refresh pending allocation or publication requests.

Methodology-specific review expansions retain their existing native verdict
and repair contracts. Replacing the default review stage must supply equivalent
approval and subject validation; overriding a stage is not approval by itself.

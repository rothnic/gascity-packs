Apply only authorized plan-readiness repairs in this native `plan-review` loop.
This author child is routed to `gc.design-author`. The following independent
review child is routed to `gc.review-synthesizer`; it owns the verdict. Keep the
same logical three-attempt budget and the native claim/close/drain protocol.

Read the actual claimed row/root and the selected `{{review_mode}}`, current
request/context, native plan/requirements paths, your `gc.attempt` and the
control's `gc.attempt_log`. Do not guess paths or recover authority from an old
cohort. These are planning artifacts, not an implementation checkout.

On attempt one, make no edit and close this author child as a completed no-op.
The original plan author already ran. In report mode, make no edit on later
attempts either; the independent reviewer must retain real findings.

On attempts two and three in agent mode, read the preceding actual blocked
report and this request's explicit repair authority. Interactive mode also
requires its existing permission; missing headless permission remains blocked.
Before any edit, compare the blocked report with the current subject using the
existing pack modules. Resolve PACK_SCRIPTS from this real description's pinned
pack, and PLAN_PATH, REPORT_PATH, ROOT_ID, DURABLE_RIG_ROOT and REQUIREMENTS_PATH
from the native root; the last value is empty only when no native requirements
path is recorded.

```sh
python3 -B - "$PACK_SCRIPTS" "$PLAN_PATH" "$REPORT_PATH" "$ROOT_ID" \
  "$DURABLE_RIG_ROOT" "$REQUIREMENTS_PATH" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import validate_plan_review as review
root = Path(sys.argv[5])
report_path = review.artifact_path(sys.argv[3], root)
text = report_path.read_text(encoding="utf-8")
report = review.verdict.validate_report_text(text, expected_kind="review")
_, data, _ = review.build.parse_front_matter(text)
subject = review.current_subject(Path(sys.argv[2]), workflow_root_id=sys.argv[4],
    artifact_root=root, required_upstream=(sys.argv[6],) if sys.argv[6] else ())
review.require(data.get("subject") == subject, "repair report subject is stale or foreign")
review.require(report.verdict == "fail" and bool(report.findings), "repair needs real blocked findings")
print(json.dumps({"subject": subject, "report_sha256": review.digest(text.encode("utf-8"))}, sort_keys=True))
PY
```

A failed/missing subject, missing authority or required change outside the
approved requirements blocks this child before edits. Preserve its actual
diagnostic and the report. Do not manufacture approval or a different request.

Apply only the explicitly permitted fixes to the native-recorded plan, using
the original requirements and actual read-only source/context. Do not edit
requirements, implementation source, the review report, graph, oracle, source
pin, lifecycle, resource bounds or attempt count. Never allocate implementation
tasks here. Keep the plan artifact valid and its upstream hashes current without
changing those upstream files.

Under `{{artifact_root}}`, record a plan-review repair summary for this actual
native attempt: before/after plan hashes, addressed finding IDs, remaining
findings and the request authority used. Do not replace a retained attempt's
summary. Never set a verdict or an approval stamp from this author child.

Close only this claimed author child with its honest execution outcome. A
completed permitted repair or no-op may pass this child; blocked/unknown work
fails it with the actual reason. Do not classify a repairable readiness finding
as a hard failure to bypass the existing loop. The next native reviewer reads
the changed bytes independently, writes their new exact subject and runs the
unchanged approval check. Neither this child's closure nor a changed plan is
approval. Preserve genuine blockers and logical max-three exhaustion.

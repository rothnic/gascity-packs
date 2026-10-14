This is the `build-from-convoy-base` handoff into the inherited review suffix.

For a captured `new` run, read the source plan's single terminal owner-output and
qualified result, bind its accepted summary/OID with
`workspace_outputs.prepare_canonical`, and require exact native write/readback.
The review suffix consumes this current immutable canonical pointer, not a moving
branch or closed convoy. Missing/partial/wrong-generation results block. Preserve
the parent/current pointer guards; new activation requires composed acceptance.

Read the drain result for the implementation convoy and record the
implementation evidence path as `gc.implementation.summary_path` or
`gc.build.implementation_summary_path` on the workflow root. Then validate the
inputs required by `build-from-review-base`.

Do not review or fix code in this step. Close only after the review suffix can
consume the implementation evidence without inspecting drain internals.

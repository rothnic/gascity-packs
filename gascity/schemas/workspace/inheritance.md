# Native workflow continuations

A drain launches each source member in its own native workflow. That workflow
uses the original implementation run and source plan while retaining its own
physical root, steps and claims. We keep those identities separate when managing
the checkout.

- **Run identity:** workspace records keep the original workflow root and source
  generation. The run, source plan and required-check policy remain immutable.
- **Native identity:** the workspace owner and each launch reference use the
  child workflow root. Native steps keep their original root metadata.
- **Source membership:** the native drain unit connects the child to the exact
  implementation convoy, control and source member in the published plan.

## Read a continuation

The native entry reader supplies `NativeRunContinuation` and the original rows
used to prove it. The adapter validates the whole relationship, including the
run, source plan and captured required-check policy. Missing, conflicting or
partial relationships are refused.

Use explicit read-only cooked-map admission for a stage that needs the workspace
but has no record-writing responsibility. Read-only admission verifies the native
occurrence; it grants no lifecycle write permission.

```python
validate_cooked_writer_map(
    writer_map, rows,
    store_ref=store.store_ref,
    workflow_root_id=original_root_id,
    record_kind=None,
    claimed_step_id=current_step_id,
    read_only=True,
)
```

After publication, read a workspace with its retained child context:

```python
workspace = store.read_record(
    "workspace", workspace_record_id, expected_identity,
    continuation=retained_context,
)
```

This read takes one snapshot of the workspace and the complete native authority
relationship. An unbound next child cannot read the previous child's workspace
using its own context. Use the previous published context until the successor
commits.

## Publish or hand off a workspace

The first workspace publication includes `InheritedRunReference(context)` in the
same guarded batch as the payload, grant and references. It publishes the child's
reference to the existing run and its immutable continuation binding. Every
original native row participates in the revision guards.

- **Current writer:** native session, retained instance token, exact claim and
  designated record kind must agree. Each later write revalidates the native
  relationship and the published child binding.
- **Same member:** a new writer must follow the declared cooked dependency path
  from a closed predecessor, or prove a new incarnation of that exact step.
- **Shared chain:** a new child must be the immediate next member in the published
  source plan. Its replacement batch moves the native owner root and publishes
  its launch references together, preserving the Git owner, generation and
  provisioning attempt.
- **Uncertain acknowledgement:** resolve the original request by exact readback.
  Never submit that request again or allocate a replacement identity blindly.

Use `writer_map.sha256` when binding a grant to its cooked map. For an inherited
map, the digest includes the native continuation; hashing only the declaration
would omit that authority relationship.

These checks establish source and checkout ownership. Project checks and
independent review still determine whether a result is accepted, against the
exact output commit.

Use the imported [shared native recipe](../do-work/prepare-worktree.md) for retained `worktree_lifecycle=new`.
Run its `workspace_entry.py read --require-plan` discovery before dependency
preparation, retaining this item's actual claim and the returned native unit
convoy. The source-plan reference belongs to the discovered producer; its
absence on an item or original root does not establish a missing plan.
The legacy route keeps its existing behavior. Invoke the actual shared helper and require its exact native readback.

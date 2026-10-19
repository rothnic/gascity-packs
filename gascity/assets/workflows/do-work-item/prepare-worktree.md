Use the imported [shared native recipe](../do-work/prepare-worktree.md) for retained `worktree_lifecycle=new`.
Run its `workspace_entry.py read --require-plan` discovery before dependency
preparation, retaining this item's actual claim and the returned native unit
convoy. The source-plan reference belongs to the discovered producer; its
absence on an item or original root does not establish a missing plan.
Only the recorded `new` lifecycle is supported. Preserve legacy or unclassified
work for explicit migration. Invoke the shared helper and require its exact
native readback.

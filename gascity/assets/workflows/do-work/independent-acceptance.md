Run this acceptance step only for recorded `worktree_lifecycle=new`. Preserve
older or unclassified runs and their original checkouts for explicit migration.

Run the independent acceptance sequence in [the native runtime contract](../workspace-runtime.md).
Use `gc gc workspace runtime begin-review` and `complete-review` under this
physical reviewer occurrence. Read the captured policy and actual producer receipts.
Inspect source and required behavior. Only a passed independent review permits
record-result; preserve all other statuses and leave the member open.

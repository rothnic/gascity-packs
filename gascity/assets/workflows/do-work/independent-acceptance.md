For retained `worktree_lifecycle=new`, run this acceptance step. The legacy route skips it.

Run the independent acceptance sequence in [the native runtime contract](../workspace-runtime.md).
Use `gc gc workspace runtime begin-review` and `complete-review` under this
physical reviewer occurrence. Read the captured policy and actual producer receipts.
Inspect source and required behavior. Only a passed independent review permits
record-result; preserve all other statuses and leave the member open.

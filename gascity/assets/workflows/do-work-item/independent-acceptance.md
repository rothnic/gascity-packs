This stage runs only for retained `worktree_lifecycle=new`; the legacy graph skips it.

Run [native independent acceptance](../workspace-runtime.md) for this exact shared
member using `gc gc workspace runtime begin-review` and `complete-review`.
The actual final producer must complete before this occurrence. Verify the exact
checkpoint subject and preserved artifacts. Leave source closure to its owner.

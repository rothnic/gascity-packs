Run this recorder step only for recorded `worktree_lifecycle=new`. Preserve
older or unclassified runs and their original checkouts for explicit migration.

Run the recorder sequence in [the native runtime contract](../workspace-runtime.md).
Use `gc gc workspace flow record-result`, then the bridge's actual checkpoint
operation for that exact native result. The final owner member also calls
`gc gc workspace flow owner-output`; integration passes the actual bridge receipt.
Require exact committed/replayed result, checkpoint and output references before
closure. An uncertain operation retains its original allocation/request and blocks.

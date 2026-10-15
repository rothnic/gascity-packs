This stage requires recorded `worktree_lifecycle=new`. Preserve older or
unclassified runs and their original checkouts for explicit migration.

Run `gc gc workspace flow close-source` using [the native runtime arguments](../workspace-runtime.md)
and this exact original member ID. The command requires its accepted result,
completed workspace checkpoint and final owner output when applicable. Close this
physical step only after native source close readback succeeds. Synthetic or parent
convoys and the broader root remain outside this closure.

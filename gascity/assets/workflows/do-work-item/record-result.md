This stage requires recorded `worktree_lifecycle=new`. Preserve older or
unclassified runs and their original checkouts for explicit migration.

Run [the native recorder sequence](../workspace-runtime.md) for this shared member.
Use `gc gc workspace flow record-result` and the actual checkpoint bridge before
advancement. The final member calls `gc gc workspace flow owner-output` with all
contiguous native checkpoints. Readback must prove every publication. Leave the
original member open until the separate close-source-anchor stage.

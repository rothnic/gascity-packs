This stage runs only for retained `worktree_lifecycle=new`; the legacy graph skips it.

Run [the native recorder sequence](../workspace-runtime.md) for this shared member.
Use `gc gc workspace flow record-result` and the actual checkpoint bridge before
advancement. The final member calls `gc gc workspace flow owner-output` with all
contiguous native checkpoints. Readback must prove every publication. Leave the
original member open until the separate close-source-anchor stage.

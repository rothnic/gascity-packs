# Managed workspaces

`gc <binding> workspace <helper> <action> [arguments]` uses the imported pack's
own helpers. With the `gc` binding, use `gc gc workspace`.

- **entry:** capture or read the original native run and required check policy.
- **dependency:** select accepted inputs, prepare owned source and integrate predecessors.
- **checkout:** verify ownership and resume a recognized unfinished native member.
- **runtime:** run project checks and independent producer review with native identities.
- **flow:** record accepted results, owner outputs, canonical review and publication.
- **scripts-path:** print the imported pack's absolute `assets/scripts` directory; accepts no arguments.

For a helper without a workspace subcommand, resolve its path in the same shell:

```sh
PACK_SCRIPTS=$(gc gc workspace scripts-path) || exit "$?"
python3 "$PACK_SCRIPTS/formula_methodology.py" --help
```

Use normal `--city` and `--rig` selection for the intended workflow. The path
comes from the native import binding, including local checkouts and cached packs.
It does not depend on the worker directory or a formula `pack_root` variable.

Gas City handles `--help` before dispatching a workspace action. To list a
helper's arguments, run it directly:

```sh
PACK_SCRIPTS=$(gc gc workspace scripts-path) || exit "$?"
python3 "$PACK_SCRIPTS/workspace_entry.py" --help
```

Actions require explicit native
city, store, registered rig, root and claimed step. Start from a real intake task
or convoy. Source access requires recorded `worktree_lifecycle=new`, the captured
project policy and qualified core APIs. First capture needs an explicit configured
base selector. `@default` selects the verified registered checkout's current
commit and immediately records that exact commit. Continuations use the recorded
commit. Preserve legacy or unclassified records and checkouts for
[explicit migration](../../docs/worktree-dependencies.md#migrate-existing-work).

Unknown writes or effects require readback of the original operation. Keep the
private allocation journals and guarded requests outside source checkouts.

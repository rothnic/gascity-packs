The native integration tests require explicit local executables:

```sh
GC_MANAGED_DO_WORK_NATIVE_BIN=/path/to/pinned/gc \
GC_MANAGED_DO_WORK_FILE_BRIDGE=/path/to/native-file-store-bridge \
python3 -m unittest discover -s gascity/tests -p test_managed_do_work_native.py -v
```

Build `native_file_store_bridge.go` as `cmd/managed-do-work-fixture/main.go` inside
a disposable copy of the selected Gas City source revision, using that
revision's Go toolchain and cached dependencies. This preserves the module's
`internal/` import boundary. Build the native `gc` executable from the same
revision. Neither executable is installed.

The fixture adapts only the unsupported ordinary `gc bd` door for the file
provider; it uses the engine's real FileStore, generated IDs, file locking and
dependency operations. A fixture-only bd shim resolves its wrapper directory
first when native exec checks reconstruct PATH. The wrapper freezes test paths
and FileStore/fake/skip provider choices because those checks deliberately omit
fixture environment variables. Production PATH and environment rules are
unchanged. The resolved bd shim refuses execution; native reads use FileStore.
Init (`--no-start`), native formula cooking, native
claim readback, Ralph control checks and managed worktrees use the selected
native executable. The test seeds claimed sessions as deterministic worker
stand-ins and never launches a model. A fixture-only combined commit uses
`git commit-tree`; no Git merge or integration branch update runs.

This proves the pack contract and native plumbing in a disposable local scope.
It does not prove PM Delivery intake, installed BD compatibility, independent
model review, semantic integration of arbitrary parent changes, or result
return to the originating PM context.

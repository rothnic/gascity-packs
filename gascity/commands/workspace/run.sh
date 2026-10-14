#!/bin/sh
set -eu
: "${GC_PACK_DIR:?workspace requires native Gas City pack context}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        gc|gascity|workspace|--city=*|--rig=*) shift ;;
        --city|--rig) [ "$#" -ge 2 ] || exit 2; shift 2 ;;
        *) break ;;
    esac
done
case "${1:---help}" in
    --help|-h) cat "$GC_PACK_DIR/commands/workspace/help.md"; exit 0 ;;
    entry|dependency|checkout|runtime|flow) helper="$1"; shift ;;
    *) echo "workspace: choose entry, dependency, checkout, runtime or flow" >&2; exit 2 ;;
esac
exec python3 "$GC_PACK_DIR/assets/scripts/workspace_$helper.py" "$@"

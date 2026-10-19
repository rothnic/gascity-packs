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
    scripts-path)
        [ "$#" -eq 1 ] || exit 2
        case "$GC_PACK_DIR" in /*) ;; *) exit 2 ;; esac
        [ -f "$GC_PACK_DIR/assets/scripts/workspace_entry.py" ] || exit 2
        [ -f "$GC_PACK_DIR/schemas/workspace/records.v1.json" ] || exit 2
        printf '%s\n' "$GC_PACK_DIR/assets/scripts"
        exit 0 ;;
    entry|dependency|checkout|runtime|flow) helper="$1"; shift ;;
    *) echo "workspace: choose entry, dependency, checkout, runtime, flow or scripts-path" >&2; exit 2 ;;
esac
exec python3 "$GC_PACK_DIR/assets/scripts/workspace_$helper.py" "$@"

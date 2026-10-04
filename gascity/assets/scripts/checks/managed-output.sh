#!/usr/bin/env bash
set -euo pipefail

# Read-only native gate; the controller supplies the returned physical subject.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/../managed_do_work.py" check --bead "${GC_BEAD_ID:?GC_BEAD_ID is required}" --phase output
"$SCRIPT_DIR/build-artifact-valid.sh"

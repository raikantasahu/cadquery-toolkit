#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

eval "$(conda shell.bash hook 2>/dev/null)"
conda activate cadquery

python "$SCRIPT_DIR/mesh_step_model.py" "$@"

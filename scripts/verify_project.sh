#!/bin/bash
# Run all automated project verification checks.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

echo "==> Static + functional verification"
python -m src.main --verify

echo "==> Browser smoke test"
python -m src.main --smoke-browser

echo "==> All verification checks passed"

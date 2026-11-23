#!/usr/bin/env bash
# Run mechanical release gates, then publish one fail-closed result file.
# Usage: tools/run_release_gates.sh <release-output-dir> <verify-extract-dir> <result-json>
# The result JSON is the ONLY gate verdict consumed by workflows/AI review.
set -euo pipefail

RESULT="${3:-}"
if [ -z "$RESULT" ]; then
  echo "usage: $0 <release-output-dir> <verify-extract-dir> <result-json>" >&2
  exit 2
fi
RESULT_DIR="$(dirname "$RESULT")"
mkdir -p "$RESULT_DIR"
# Default to fail so any unexpected early exit keeps the verdict fail-closed.
write_result() {
  printf '{"result":"%s"}\n' "$1" > "$RESULT"
}
write_result fail

RC=0
bash tools/fork_gates.sh "$1" "$2" || RC=$?
if [ "$RC" -ne 0 ]; then
  echo "::error::release gates failed (exit=$RC); verdict=fail" >&2
  exit "$RC"
fi
write_result pass

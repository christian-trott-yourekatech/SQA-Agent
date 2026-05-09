#!/bin/bash
# Run quality-check tools (formatter, linter, type-checker, tests).
# Mirrors the pattern from v1.

set +e
ruff_format_status=0
ruff_status=0
pyrefly_status=0
pytest_status=0

echo "=== ruff format (check) ==="
uv run ruff format --check src tests
ruff_format_status=$?

echo "=== ruff check ==="
uv run ruff check src tests
ruff_status=$?

echo "=== pyrefly ==="
uv run pyrefly check src tests
pyrefly_status=$?

echo "=== pytest ==="
uv run pytest tests/
pytest_status=$?

echo
echo "=== Summary ==="
[ $ruff_format_status -eq 0 ] && echo "  format     PASS" || echo "  format     FAIL"
[ $ruff_status -eq 0 ]        && echo "  lint       PASS" || echo "  lint       FAIL"
[ $pyrefly_status -eq 0 ]     && echo "  type-check PASS" || echo "  type-check FAIL"
[ $pytest_status -eq 0 ]      && echo "  tests      PASS" || echo "  tests      FAIL"

[ $ruff_format_status -eq 0 ] && [ $ruff_status -eq 0 ] && \
    [ $pyrefly_status -eq 0 ] && [ $pytest_status -eq 0 ]

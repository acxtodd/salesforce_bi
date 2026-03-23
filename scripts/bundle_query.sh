#!/usr/bin/env bash
# Bundle the Query Lambda with shared modules for Docker build context.
# Copies lib/ modules and denorm_config.yaml into lambda/query/ so the
# Dockerfile can COPY them.  Run from project root: bash scripts/bundle_query.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QUERY_DIR="$PROJECT_ROOT/lambda/query"

echo "Bundling Query Lambda shared modules..."

# Clean previous copies
rm -rf "$QUERY_DIR/lib"

# Copy shared lib modules
mkdir -p "$QUERY_DIR/lib"
cp "$PROJECT_ROOT/lib/__init__.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/query_handler.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/search_backend.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/tool_dispatch.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/turbopuffer_backend.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/system_prompt.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/write_proposal.py" "$QUERY_DIR/lib/"
cp "$PROJECT_ROOT/lib/denormalize.py" "$QUERY_DIR/lib/"

# Copy denorm config
cp "$PROJECT_ROOT/denorm_config.yaml" "$QUERY_DIR/"

echo "Bundle ready at: $QUERY_DIR"
echo "Contents:"
find "$QUERY_DIR" -name '*.py' -o -name '*.yaml' -o -name 'Dockerfile' -o -name 'requirements.txt' | sort

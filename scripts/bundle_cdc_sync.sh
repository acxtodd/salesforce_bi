#!/usr/bin/env bash
# Bundle the CDC sync Lambda with shared modules for deployment.
# Creates lambda/cdc_sync/.bundle/ with handler + lib/ + common/ + config.
# Run from project root: bash scripts/bundle_cdc_sync.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_DIR="$PROJECT_ROOT/lambda/cdc_sync/.bundle"

echo "Bundling CDC sync Lambda..."

# Clean previous bundle
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/lib" "$BUNDLE_DIR/common"

# Copy handler
cp "$PROJECT_ROOT/lambda/cdc_sync/index.py" "$BUNDLE_DIR/"

# Copy shared lib modules
cp "$PROJECT_ROOT/lib/denormalize.py" "$BUNDLE_DIR/lib/"
cp "$PROJECT_ROOT/lib/turbopuffer_backend.py" "$BUNDLE_DIR/lib/"
cp "$PROJECT_ROOT/lib/search_backend.py" "$BUNDLE_DIR/lib/"
touch "$BUNDLE_DIR/lib/__init__.py"

# Copy shared lambda/common modules
cp "$PROJECT_ROOT/lambda/common/salesforce_client.py" "$BUNDLE_DIR/common/"
touch "$BUNDLE_DIR/common/__init__.py"

# Copy denorm config
cp "$PROJECT_ROOT/denorm_config.yaml" "$BUNDLE_DIR/"

# Install Python dependencies for Lambda (Linux x86_64 target)
pip3 install turbopuffer pyyaml \
  -t "$BUNDLE_DIR/" \
  --quiet --upgrade \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --python-version 3.11 \
  --implementation cp 2>/dev/null

echo "Bundle created at: $BUNDLE_DIR"
echo "Contents:"
find "$BUNDLE_DIR" -name '*.py' -o -name '*.yaml' | sort | head -20

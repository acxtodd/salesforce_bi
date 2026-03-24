#!/usr/bin/env bash
# Bundle the config_refresh Lambda with shared modules for deployment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_DIR="$PROJECT_ROOT/lambda/config_refresh/.bundle"

echo "Bundling config_refresh Lambda..."

rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/lib" "$BUNDLE_DIR/common" "$BUNDLE_DIR/scripts"

cp "$PROJECT_ROOT/lambda/config_refresh/index.py" "$BUNDLE_DIR/"
cp "$PROJECT_ROOT/lib/config_refresh.py" "$BUNDLE_DIR/lib/"
cp "$PROJECT_ROOT/lib/runtime_config.py" "$BUNDLE_DIR/lib/"
cp "$PROJECT_ROOT/lib/tool_dispatch.py" "$BUNDLE_DIR/lib/"
cp "$PROJECT_ROOT/lambda/common/salesforce_client.py" "$BUNDLE_DIR/common/"
cp "$PROJECT_ROOT/scripts/generate_denorm_config.py" "$BUNDLE_DIR/scripts/"
cp "$PROJECT_ROOT/lambda/schema_discovery/signal_harvester.py" "$BUNDLE_DIR/"
touch "$BUNDLE_DIR/lib/__init__.py" "$BUNDLE_DIR/common/__init__.py" "$BUNDLE_DIR/scripts/__init__.py"

pip3 install pyyaml \
  -t "$BUNDLE_DIR/" \
  --quiet --upgrade \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --python-version 3.11 \
  --implementation cp 2>/dev/null

echo "Bundle created at: $BUNDLE_DIR"

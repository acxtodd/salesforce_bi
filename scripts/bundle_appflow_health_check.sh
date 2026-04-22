#!/usr/bin/env bash
# Bundle the AppFlow health check Lambda for deployment.
# Creates lambda/appflow_health_check/.bundle/ with handler only.
# boto3 is provided by the Python 3.11 Lambda runtime; no extra deps needed.
# Run from project root: bash scripts/bundle_appflow_health_check.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_DIR="$PROJECT_ROOT/lambda/appflow_health_check/.bundle"

echo "Bundling AppFlow health check Lambda..."

rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

cp "$PROJECT_ROOT/lambda/appflow_health_check/index.py" "$BUNDLE_DIR/"

echo "Bundle created at: $BUNDLE_DIR"

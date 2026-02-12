#!/usr/bin/env bash
# Build the BYOD Local UI frontend for production.
# Output goes to src/byod_cli/ui/static/ and ships with the Python wheel.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../src/byod_cli/ui/frontend"

echo "Building BYOD Local UI..."
cd "$FRONTEND_DIR"

if [ ! -d "node_modules" ]; then
  echo "Installing dependencies..."
  npm ci
fi

echo "Running TypeScript check..."
npx tsc --noEmit

echo "Building for production..."
npm run build

echo ""
echo "Build complete! Static files are in src/byod_cli/ui/static/"
ls -lh ../static/index.html ../static/assets/ 2>/dev/null || true

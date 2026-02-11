#!/usr/bin/env bash
#
# Release script for byod-cli
#
# Usage:
#   ./scripts/release.sh patch    # 1.0.0 → 1.0.1
#   ./scripts/release.sh minor    # 1.0.0 → 1.1.0
#   ./scripts/release.sh major    # 1.0.0 → 2.0.0
#   ./scripts/release.sh 1.2.3    # Set exact version
#
set -euo pipefail

BUMP_TYPE="${1:-}"

if [ -z "$BUMP_TYPE" ]; then
    echo "Usage: ./scripts/release.sh <patch|minor|major|X.Y.Z>"
    exit 1
fi

# Get current version from pyproject.toml
CURRENT=$(grep -m1 '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "Current version: $CURRENT"

# Parse semver
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

# Calculate new version
case "$BUMP_TYPE" in
    patch) NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))" ;;
    minor) NEW_VERSION="$MAJOR.$((MINOR + 1)).0" ;;
    major) NEW_VERSION="$((MAJOR + 1)).0.0" ;;
    *)
        if [[ "$BUMP_TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            NEW_VERSION="$BUMP_TYPE"
        else
            echo "Error: Invalid bump type '$BUMP_TYPE'"
            echo "Use: patch, minor, major, or an exact version (e.g. 1.2.3)"
            exit 1
        fi
        ;;
esac

echo "New version:     $NEW_VERSION"
echo ""

# Confirm
read -p "Release v${NEW_VERSION}? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Check for clean working tree
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: Working tree is not clean. Commit or stash changes first."
    exit 1
fi

# Check we're on main
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
    echo "Warning: You're on '$BRANCH', not 'main'."
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# Run tests first
echo "Running tests..."
python -m pytest tests/ -q
echo ""

# Update version in pyproject.toml
sed -i "s/^version = \"$CURRENT\"/version = \"$NEW_VERSION\"/" pyproject.toml
echo "Updated pyproject.toml"

# Commit, tag, push
git add pyproject.toml
git commit -m "Release v${NEW_VERSION}"
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"

echo ""
echo "Pushing to origin..."
git push origin "$BRANCH"
git push origin "v${NEW_VERSION}"

echo ""
echo "Done! v${NEW_VERSION} released."
echo "GitHub Actions will publish to PyPI automatically."

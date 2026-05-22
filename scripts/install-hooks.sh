#!/usr/bin/env bash
# Activate the version-controlled git hooks in .githooks for this clone.
# Run once after cloning (also safe to re-run): bash scripts/install-hooks.sh
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true
echo "core.hooksPath -> $(git config --get core.hooksPath)"
echo "Hooks active. Pre-commit secret guard is on for this clone."

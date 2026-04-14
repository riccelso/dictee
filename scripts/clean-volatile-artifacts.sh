#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"

# Safe cleaning: only known volatile artifacts.
find "$ROOT_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$ROOT_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true
rm -f "$ROOT_DIR/dictee.plasmoid" 2>/dev/null || true

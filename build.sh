#!/bin/bash
set -e

FEATURES=""

case "${1:-}" in
  ""|"--cpu")
    ;;
  --cuda)
    FEATURES="cuda,sortformer"
    ;;
  *)
    echo "Usage: $0 [--cpu|--cuda]" >&2
    exit 2
    ;;
esac

if [ -n "$FEATURES" ]; then
  cargo build --release --features "$FEATURES"
else
  cargo build --release
fi

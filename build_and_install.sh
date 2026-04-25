#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Building Rust binaries (release)"
"$SCRIPT_DIR/build.sh" --cuda

echo "==> Syncing latest scripts into pkg/ artifacts"
cp -f "$SCRIPT_DIR/dictee" "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee"
cp -f "$SCRIPT_DIR/dictee-postprocess.py" "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-postprocess"
cp -f "$SCRIPT_DIR/dictee-ptt.py" "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-ptt"
cp -f "$SCRIPT_DIR/dictee-setup.py" "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-setup"
cp -f "$SCRIPT_DIR/dictee-tray.py" "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-tray"
chmod 755 \
  "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee" \
  "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-postprocess" \
  "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-ptt" \
  "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-setup" \
  "$SCRIPT_DIR/pkg/dictee/usr/bin/dictee-tray"

echo "==> Installing latest build to system"
sudo "$SCRIPT_DIR/install.sh"

#!/usr/bin/env bash
set -euo pipefail

PREFIX=${PREFIX:-/opt/user-widget-mvp}
AUTOSTART_DIR=${AUTOSTART_DIR:-/etc/xdg/autostart}
PYTHON_BIN=${PYTHON_BIN:-/usr/bin/python3}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

mkdir -p "$PREFIX/bin"
install -m 0755 "$ROOT_DIR/bin/user_widget_mvp.py" "$PREFIX/bin/user_widget_mvp.py"
install -m 0755 "$ROOT_DIR/bin/quota_cli.py" "$PREFIX/bin/quota_cli.py"
install -m 0755 "$ROOT_DIR/bin/quota-status" "$PREFIX/bin/quota-status"

mkdir -p "$PREFIX/icons"
install -m 0644 "$ROOT_DIR"/icons/*.svg "$PREFIX/icons/"

mkdir -p "$AUTOSTART_DIR"
sed "s#Exec=/usr/bin/python3 /opt/user-widget-mvp/bin/user_widget_mvp.py#Exec=${PYTHON_BIN} ${PREFIX}/bin/user_widget_mvp.py#g" \
  "$ROOT_DIR/autostart/user-widget-mvp.desktop" > "$AUTOSTART_DIR/user-widget-mvp.desktop"

cat <<EOF
Installed:
  gui script: $PREFIX/bin/user_widget_mvp.py
  cli script: $PREFIX/bin/quota_cli.py
  shortcut: $PREFIX/bin/quota-status
  autostart: $AUTOSTART_DIR/user-widget-mvp.desktop

Run a quick test in GUI session:
  $PYTHON_BIN $PREFIX/bin/user_widget_mvp.py

Run a quick test in headless/CLI mode:
  $PYTHON_BIN $PREFIX/bin/quota_cli.py
  $PREFIX/bin/quota-status
EOF

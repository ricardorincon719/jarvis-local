#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_DIR/deploy/systemd/pearl-hub.service.in"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/pearl-home"
CONFIG_FILE="$CONFIG_DIR/hub.env"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pearl-home/scene-memory"
SERVICE_FILE="$SYSTEMD_DIR/pearl-hub.service"
PYTHON_BIN="$REPO_DIR/venv/bin/python"

if systemctl is-active --quiet jarvis-orchestrator.service 2>/dev/null; then
    printf 'Servicio de sistema existente detectado: jarvis-orchestrator.service\n'
    printf 'Se mantiene activo para evitar una segunda instancia en el puerto 5006.\n'
    printf 'La aplicacion ya informa identidad PEARL Hub mediante /api/v1/status.\n'
    exit 0
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$SYSTEMD_DIR" "$CONFIG_DIR" "$DATA_DIR"

if [[ ! -f "$CONFIG_FILE" ]]; then
    printf '%s\n' \
        'PEARL_PRODUCT=PEARL Hub' \
        'PEARL_EDITION=hub' \
        'PEARL_VERSION=0.7.0-beta.1' \
        'PEARL_HUB_HOST=0.0.0.0' \
        'PEARL_HUB_PORT=5006' > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
fi

sed \
    -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@PYTHON_BIN@|$PYTHON_BIN|g" \
    -e "s|@DATA_DIR@|$DATA_DIR|g" \
    -e "s|@CONFIG_FILE@|$CONFIG_FILE|g" \
    "$TEMPLATE" > "$SERVICE_FILE"

systemctl --user daemon-reload
systemctl --user enable --now pearl-hub.service

printf 'PEARL Hub instalado: %s\n' "$SERVICE_FILE"
printf 'Memoria privada: %s\n' "$DATA_DIR"
printf 'Estado: systemctl --user status pearl-hub.service\n'
printf 'Para iniciar sin sesion grafica: loginctl enable-linger %s\n' "$USER"

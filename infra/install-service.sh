#!/bin/bash
# Installs the arke systemd service after .env is in place.
# Usage: bash install-service.sh

set -euo pipefail

INSTALL_DIR="/opt/arke"

cat > /etc/systemd/system/arke.service << EOF
[Unit]
Description=Arke Prediction Market Intelligence Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=arke
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python agent/scheduler.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable arke
systemctl start arke
systemctl status arke --no-pager
echo "=== Arke agent started ==="
echo "Monitor: journalctl -u arke -f"

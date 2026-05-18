#!/bin/bash
# Arke VPS bootstrap — Ubuntu 22.04
# Run as root once after provisioning.
# Usage: bash server-setup.sh

set -euo pipefail

echo "=== Arke VPS Bootstrap ==="

# System deps
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl wget htop

# Create arke user
if ! id -u arke >/dev/null 2>&1; then
    useradd -m -s /bin/bash arke
    echo "Created arke user"
fi

# Clone repo (assumes GITHUB_REPO env var set, or edit inline)
REPO_URL="${GITHUB_REPO:-https://github.com/your-handle/arke}"
INSTALL_DIR="/opt/arke"

if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R arke:arke "$INSTALL_DIR"

# Python venv
sudo -u arke python3 -m venv "$INSTALL_DIR/venv"
sudo -u arke "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u arke "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "=== Copy your .env file ==="
echo "Run: scp .env root@SERVER_IP:$INSTALL_DIR/.env"
echo "Then run: bash $INSTALL_DIR/infra/install-service.sh"

#!/usr/bin/env bash
# Put the ASTRA demonstration copy on a fresh Ubuntu 24.04 server, behind HTTPS.
#
#     tar xzf astra-demo-bundle.tar.gz
#     bash astra-demo/setup_server.sh                    # address: <ip>.sslip.io
#     bash astra-demo/setup_server.sh astra.duckdns.org  # or a name pointed here
#
# Plain Python in a virtual environment, run by systemd -- no containers.
# Safe to run again: a second run installs whatever bundle is beside it and
# restarts the service, which is how an update is deployed.
set -euo pipefail
BUNDLE="$(cd "$(dirname "$0")" && pwd)"

IP="$(curl -fsS https://api.ipify.org)"
DOMAIN="${1:-${IP//./-}.sslip.io}"
echo "== ASTRA demo: public address ${IP}, site https://${DOMAIN}"

echo "== 1/6 System packages: Python 3.12 and Caddy"
sudo apt-get update -y
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev build-essential curl
if ! command -v caddy >/dev/null; then
    sudo apt-get install -y caddy || {
        # Not in this release's archive: the Caddy project's own repository.
        sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https gnupg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            | sudo tee /etc/apt/sources.list.d/caddy-stable.list
        sudo apt-get update -y && sudo apt-get install -y caddy
    }
fi

echo "== 2/6 Open ports 80 and 443 in the server's own firewall"
# Oracle's Ubuntu images ship an iptables policy that rejects everything but
# SSH, on top of the cloud's security list. Both have to allow the web ports.
for port in 80 443; do
    sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
        || sudo iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then
    sudo netfilter-persistent save
fi

echo "== 3/6 The application, under its own unprivileged account"
id astra >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /opt/astra astra
sudo systemctl stop astra-demo 2>/dev/null || true
sudo rm -rf /opt/astra/app
sudo mkdir -p /opt/astra
sudo cp -a "$BUNDLE" /opt/astra/app
sudo chown -R astra:astra /opt/astra

echo "== 4/6 Python packages (the first install takes 5-15 minutes)"
sudo -u astra python3.12 -m venv /opt/astra/venv
PIP="sudo -u astra /opt/astra/venv/bin/pip --disable-pip-version-check"
$PIP install --upgrade pip
# The same hash-verified lock every other install uses. If this machine's
# processor has a wheel the lock never recorded a hash for, fall back to the
# same pinned versions without the hashes rather than stopping.
if ! $PIP install --require-hashes -r /opt/astra/app/requirements.lock; then
    echo "   hash-verified install failed here; installing the same pinned versions"
    sed -E '/^[[:space:]]*--hash/d; s/[[:space:]]*\\$//' /opt/astra/app/requirements.lock \
        | sudo -u astra tee /opt/astra/requirements.nohash.txt >/dev/null
    $PIP install -r /opt/astra/requirements.nohash.txt
fi
# The deep models (remaining-life network, third detection tier), CPU build,
# the version they were saved with.
$PIP install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu \
    || $PIP install torch==2.13.0

echo "== 5/6 Run it, and keep it running"
sudo cp /opt/astra/app/astra-demo.service /etc/systemd/system/astra-demo.service
sudo systemctl daemon-reload
sudo systemctl enable astra-demo
sudo systemctl restart astra-demo

echo "== 6/6 HTTPS in front of it"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl enable caddy
sudo systemctl restart caddy

echo "== waiting for ASTRA to answer"
for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8000/api/healthz >/dev/null 2>&1; then
        echo
        echo "   ASTRA is running:  https://${DOMAIN}"
        exit 0
    fi
    sleep 3
done
echo "ASTRA did not answer; see: sudo journalctl -u astra-demo -n 80" >&2
exit 1

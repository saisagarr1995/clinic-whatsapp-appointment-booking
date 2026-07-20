#!/usr/bin/env bash
#
# One-time server provisioning for a fresh Oracle Cloud Always Free VM (Ubuntu 24.04).
# Sets up the host to run MANY clinics; individual clinics are added afterwards
# with `clinic-fleet add <slug>`.
#
#     curl -fsSL https://raw.githubusercontent.com/saisagarr1995/clinic-whatsapp-appointment-booking/main/deploy/install_server.sh -o install_server.sh
#     less install_server.sh          # read it before running anything as root
#     sudo bash install_server.sh
#
# Idempotent: safe to re-run. Never touches an existing clinic's data or .env.

set -euo pipefail

APP_USER="clinicbot"
APP_DIR="/opt/clinic-bot"
REPO="https://github.com/saisagarr1995/clinic-whatsapp-appointment-booking.git"
BRANCH="main"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run this with sudo."

# ---------------------------------------------------------------------------
log "Installing system packages"
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    git curl sqlite3 ca-certificates gnupg \
    debian-keyring debian-archive-keyring apt-transport-https \
    unattended-upgrades

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)' \
    || die "Python 3.12+ required. Use the Ubuntu 24.04 image, which ships 3.12."
log "Python $(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])') detected"

# Security patches applied automatically — nobody is going to SSH in weekly.
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
log "Installing Caddy (automatic HTTPS)"
# ---------------------------------------------------------------------------
if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
else
    log "Caddy already present"
fi

# ---------------------------------------------------------------------------
log "Creating the service account"
# ---------------------------------------------------------------------------
# Unprivileged, no login shell. If a clinic process is ever compromised the
# blast radius is that one clinic's folder.
id -u "$APP_USER" >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir "/home/${APP_USER}" \
            --shell /usr/sbin/nologin "$APP_USER"

# ---------------------------------------------------------------------------
log "Fetching the application"
# ---------------------------------------------------------------------------
if [[ -d "${APP_DIR}/.git" ]]; then
    git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/${BRANCH}"
else
    git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

mkdir -p "${APP_DIR}/clinics" "${APP_DIR}/data/backups"

# ---------------------------------------------------------------------------
log "Building the shared virtual environment"
# ---------------------------------------------------------------------------
[[ -x "${APP_DIR}/.venv/bin/python" ]] || python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip --quiet
"${APP_DIR}/.venv/bin/python" -m pip install -e "$APP_DIR" --quiet

# ---------------------------------------------------------------------------
log "Installing systemd units and the fleet manager"
# ---------------------------------------------------------------------------
install -m 644 "${APP_DIR}/deploy/clinic-bot@.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/clinic-bot.target"   /etc/systemd/system/
install -m 755 "${APP_DIR}/deploy/fleet.sh"            /usr/local/bin/clinic-fleet
systemctl daemon-reload
systemctl enable clinic-bot.target >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
log "Configuring Caddy"
# ---------------------------------------------------------------------------
mkdir -p /etc/caddy/clinics.d /var/log/caddy
chown -R caddy:caddy /var/log/caddy

if [[ ! -f /etc/caddy/Caddyfile.clinic-installed ]]; then
    cp "${APP_DIR}/deploy/Caddyfile" /etc/caddy/Caddyfile
    touch /etc/caddy/Caddyfile.clinic-installed
    warn "Set your domain in /etc/caddy/Caddyfile (currently bot.example.duckdns.org)"
fi

# ---------------------------------------------------------------------------
log "Fleet configuration"
# ---------------------------------------------------------------------------
if [[ ! -f "${APP_DIR}/fleet.conf" ]]; then
    cat >"${APP_DIR}/fleet.conf" <<'EOF'
# Fleet-wide settings, read by clinic-fleet.
# DOMAIN must match the domain in /etc/caddy/Caddyfile.
DOMAIN=bot.example.duckdns.org
RETAIN_DAYS=30
EOF
    warn "Set DOMAIN in ${APP_DIR}/fleet.conf"
fi

# ---------------------------------------------------------------------------
log "Installing nightly fleet backups"
# ---------------------------------------------------------------------------
cat >/etc/cron.d/clinic-fleet-backup <<'CRON'
# Verified SQLite snapshot of every clinic, nightly at 02:30, 30-day retention.
30 2 * * * root /usr/local/bin/clinic-fleet backup all >/var/log/clinic-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/clinic-fleet-backup

# ---------------------------------------------------------------------------
log "Permissions"
# ---------------------------------------------------------------------------
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/clinics" "${APP_DIR}/data"
chmod 750 "${APP_DIR}/clinics" "${APP_DIR}/data"

# ---------------------------------------------------------------------------
log "Firewall"
# ---------------------------------------------------------------------------
# Oracle's Ubuntu image ships restrictive iptables rules that silently drop
# 80/443. Opening them here is necessary but NOT sufficient — the VCN Security
# List in the Oracle console must allow them too. See docs/DEPLOYMENT.md.
if command -v iptables >/dev/null 2>&1; then
    iptables -I INPUT -p tcp --dport 80  -j ACCEPT 2>/dev/null || true
    iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save >/dev/null 2>&1 || true
    fi
fi

cat <<EOF

  Server ready. It currently hosts 0 clinics.

  Finish setup:

    1. Point your DuckDNS subdomain at this VM's public IP.

    2. Set your domain in BOTH places, then reload Caddy:
         sudo nano /etc/caddy/Caddyfile        # replace bot.example.duckdns.org
         sudo nano ${APP_DIR}/fleet.conf       # DOMAIN=...
         sudo systemctl reload caddy

    3. Open ports 80 and 443 in the Oracle console:
         Networking > Virtual Cloud Networks > your VCN > Security Lists
         Add ingress rules for TCP 80 and 443 from 0.0.0.0/0

    4. Add your first clinic:
         sudo clinic-fleet add smile-dental

    5. See everything at a glance:
         sudo clinic-fleet list

EOF

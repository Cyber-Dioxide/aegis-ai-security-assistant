#!/usr/bin/env bash
# =============================================================================
#  Hiderox Aegis — one-shot server deployment (Linux + systemd)
#
#  Installs: system packages, Python 3.10+, a virtualenv, Ollama (+ a model),
#  and registers Aegis as a hardened systemd service that starts on boot.
#
#  Usage (run from the repository root, as root or with sudo):
#    sudo ./deploy/deploy.sh                      # defaults: localhost:8080, model gemma3:4b
#    sudo ./deploy/deploy.sh --public --port 8080  # listen on all interfaces (token required)
#    sudo ./deploy/deploy.sh --model qwen3:8b
#    sudo ./deploy/deploy.sh --no-ollama           # cloud AI only (add keys in Settings)
#    sudo ./deploy/deploy.sh --uninstall           # remove service + app (keeps data unless --purge)
#
#  Supported: Debian / Ubuntu, RHEL / Rocky / Alma / Fedora, Arch, openSUSE.
# =============================================================================
set -euo pipefail

APP_NAME="hiderox-aegis"
APP_USER="aegis"
INSTALL_DIR="/opt/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
ENV_FILE="/etc/${APP_NAME}/aegis.env"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
HOST="127.0.0.1"
PORT="8080"
MODEL="gemma3:4b"
INSTALL_OLLAMA=1
PULL_MODEL=1
UNINSTALL=0
PURGE=0
MIN_PY_MINOR=10

# ---------------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------------- #
c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_dim=$'\e[2m'; c_off=$'\e[0m'
step() { echo; echo "${c_ok}==>${c_off} $*"; }
warn() { echo "${c_warn}!!${c_off}  $*"; }
die()  { echo "${c_err}xx${c_off}  $*" >&2; exit 1; }

usage() { sed -n '2,17p' "$0" | sed 's/^#\s\{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --public) HOST="0.0.0.0"; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --no-ollama) INSTALL_OLLAMA=0; PULL_MODEL=0; shift ;;
    --no-model) PULL_MODEL=0; shift ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge) PURGE=1; shift ;;
    -h|--help) usage ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Run as root: sudo $0 $*"
command -v systemctl >/dev/null || die "systemd is required."
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$SRC_DIR/app.py" ]] || die "Run this from the Aegis repository (app.py not found in $SRC_DIR)."
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT > 0 && PORT < 65536 )) || die "Invalid port: $PORT"

# ---------------------------------------------------------------------------- #
# Uninstall
# ---------------------------------------------------------------------------- #
if [[ $UNINSTALL -eq 1 ]]; then
  step "Removing ${APP_NAME}"
  systemctl disable --now "${APP_NAME}" 2>/dev/null || true
  rm -f "$SERVICE_FILE"; systemctl daemon-reload
  rm -rf "$INSTALL_DIR"
  if [[ $PURGE -eq 1 ]]; then
    rm -rf "$DATA_DIR" "/etc/${APP_NAME}"
    id "$APP_USER" &>/dev/null && userdel "$APP_USER" || true
    echo "Data, config and user removed."
  else
    echo "Kept data in $DATA_DIR and config in /etc/${APP_NAME} (use --purge to delete)."
  fi
  echo "Ollama was left installed (remove it separately if you want)."
  exit 0
fi

# ---------------------------------------------------------------------------- #
# 1. System packages
# ---------------------------------------------------------------------------- #
step "Installing system packages"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates fonts-dejavu-core zstd >/dev/null
  PKG=apt
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 python3-pip curl ca-certificates dejavu-sans-fonts dejavu-sans-mono-fonts zstd >/dev/null
  PKG=dnf
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed python python-pip curl ca-certificates ttf-dejavu zstd >/dev/null
  PKG=pacman
elif command -v zypper >/dev/null; then
  zypper -n -q install python3 python3-pip curl ca-certificates dejavu-fonts zstd >/dev/null
  PKG=zypper
else
  die "Unsupported distribution (need apt, dnf, pacman or zypper)."
fi

# ---------------------------------------------------------------------------- #
# 2. Python >= 3.10
# ---------------------------------------------------------------------------- #
step "Checking Python (need 3.${MIN_PY_MINOR}+)"
find_python() {
  for py in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$py" >/dev/null && "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, ${MIN_PY_MINOR}) else 1)"; then
      command -v "$py"; return 0
    fi
  done
  return 1
}
PYTHON="$(find_python || true)"
if [[ -z "$PYTHON" ]]; then
  warn "System Python is too old — installing a newer one"
  case "$PKG" in
    apt) apt-get install -y -qq software-properties-common >/dev/null
         if grep -qi ubuntu /etc/os-release; then add-apt-repository -y ppa:deadsnakes/ppa >/dev/null; apt-get update -qq; fi
         apt-get install -y -qq python3.11 python3.11-venv >/dev/null ;;
    dnf) dnf install -y -q python3.11 >/dev/null ;;
    *)   die "Install Python 3.${MIN_PY_MINOR}+ manually, then re-run." ;;
  esac
  PYTHON="$(find_python || true)"
  [[ -n "$PYTHON" ]] || die "Could not install Python 3.${MIN_PY_MINOR}+."
fi
echo "   using $PYTHON ($("$PYTHON" --version))"

# ---------------------------------------------------------------------------- #
# 3. Ollama (local AI)
# ---------------------------------------------------------------------------- #
if [[ $INSTALL_OLLAMA -eq 1 ]]; then
  step "Installing Ollama"
  if command -v ollama >/dev/null; then
    echo "   already installed ($(ollama --version 2>/dev/null | head -1))"
  else
    # Official installer; it creates the 'ollama' user and systemd service.
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  systemctl enable --now ollama >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
  curl -fs http://127.0.0.1:11434/api/tags >/dev/null || warn "Ollama isn't answering on :11434 yet — check: systemctl status ollama"
  if [[ $PULL_MODEL -eq 1 ]]; then
    step "Pulling model ${MODEL} (this can take a while)"
    ollama pull "$MODEL" || warn "Model pull failed — pull it later with: ollama pull $MODEL"
  fi
fi

# ---------------------------------------------------------------------------- #
# 4. App user, files, virtualenv
# ---------------------------------------------------------------------------- #
step "Installing Aegis to ${INSTALL_DIR}"
id "$APP_USER" &>/dev/null || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$(dirname "$ENV_FILE")"
# Copy the code (not local data, venvs or git metadata).
tar -C "$SRC_DIR" --exclude=./data --exclude=./venv --exclude=./.venv --exclude=./.git \
    --exclude='__pycache__' -cf - . | tar -C "$INSTALL_DIR" -xf -
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

step "Creating virtualenv"
"$PYTHON" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" gunicorn

# ---------------------------------------------------------------------------- #
# 5. Config (/etc/hiderox-aegis/aegis.env) — kept across re-deploys
# ---------------------------------------------------------------------------- #
step "Writing configuration"
if [[ ! -f "$ENV_FILE" ]]; then
  TOKEN="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(24))')"
  cat > "$ENV_FILE" <<EOF
# Hiderox Aegis configuration — edit, then: systemctl restart ${APP_NAME}
AEGIS_HOST=${HOST}
AEGIS_PORT=${PORT}
AEGIS_DATA_DIR=${DATA_DIR}
# Login token for the web UI. Required when listening beyond localhost. Empty = no login.
AEGIS_ACCESS_TOKEN=${TOKEN}
# Set to 1 when served over HTTPS (e.g. behind nginx/Caddy) so cookies are Secure-only.
AEGIS_SECURE_COOKIES=0
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=${MODEL}
# Optional cloud keys (or add them in Settings → AI Brain):
# GEMINI_API_KEY=
# GROQ_API_KEY=
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
EOF
  NEW_TOKEN=1
else
  sed -i "s|^AEGIS_HOST=.*|AEGIS_HOST=${HOST}|; s|^AEGIS_PORT=.*|AEGIS_PORT=${PORT}|" "$ENV_FILE"
  NEW_TOKEN=0
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"
# shellcheck disable=SC1090
source "$ENV_FILE"
if [[ "$AEGIS_HOST" != "127.0.0.1" && "$AEGIS_HOST" != "localhost" && -z "${AEGIS_ACCESS_TOKEN:-}" ]]; then
  die "Refusing to expose Aegis on ${AEGIS_HOST} without AEGIS_ACCESS_TOKEN (set it in ${ENV_FILE})."
fi

# ---------------------------------------------------------------------------- #
# 6. systemd service (gunicorn, threaded workers for streaming, sandboxed)
# ---------------------------------------------------------------------------- #
step "Registering systemd service ${APP_NAME}"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Hiderox Aegis — AI security & privacy assistant
Documentation=https://hiderox.com
After=network-online.target ollama.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ExecStart=/bin/sh -c 'exec ${INSTALL_DIR}/venv/bin/gunicorn --workers 1 --worker-class gthread --threads 16 --timeout 0 --graceful-timeout 30 --bind \${AEGIS_HOST}:\${AEGIS_PORT} --access-logfile - app:app'
Restart=on-failure
RestartSec=3

# Hardening
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DATA_DIR}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
RestrictNamespaces=true
RestrictRealtime=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "${APP_NAME}" >/dev/null 2>&1
systemctl restart "${APP_NAME}"

# ---------------------------------------------------------------------------- #
# 7. Health check
# ---------------------------------------------------------------------------- #
step "Waiting for Aegis to come up"
CHECK_HOST="$AEGIS_HOST"; [[ "$CHECK_HOST" == "0.0.0.0" ]] && CHECK_HOST="127.0.0.1"
for _ in $(seq 1 30); do curl -fs "http://${CHECK_HOST}:${AEGIS_PORT}/api/health" >/dev/null && break; sleep 1; done
if curl -fs "http://${CHECK_HOST}:${AEGIS_PORT}/api/health" >/dev/null; then
  echo "   ${c_ok}healthy${c_off}"
else
  warn "Aegis didn't answer yet. Logs: journalctl -u ${APP_NAME} -n 50"
fi

echo
echo "${c_ok}✔ Hiderox Aegis is installed.${c_off}"
echo "   URL:      http://${CHECK_HOST}:${AEGIS_PORT}"
[[ "$AEGIS_HOST" == "127.0.0.1" ]] && echo "   ${c_dim}(localhost only — use an SSH tunnel or reverse proxy, or re-run with --public)${c_off}"
if [[ -n "${AEGIS_ACCESS_TOKEN:-}" ]]; then
  if [[ $NEW_TOKEN -eq 1 ]]; then
    echo "   Token:    ${AEGIS_ACCESS_TOKEN}   ${c_warn}<- save this; it's also in ${ENV_FILE}${c_off}"
  else
    echo "   Token:    unchanged (see ${ENV_FILE})"
  fi
fi
echo "   Data:     ${DATA_DIR}"
echo "   Config:   ${ENV_FILE}"
echo "   Logs:     journalctl -u ${APP_NAME} -f"
echo "   Manage:   systemctl {status|restart|stop} ${APP_NAME}"
[[ "$AEGIS_HOST" != "127.0.0.1" ]] && echo "   ${c_warn}Tip:${c_off} put it behind HTTPS (Caddy/nginx) and set AEGIS_SECURE_COOKIES=1."

#!/usr/bin/env bash
# Deploy the Splitsmart bundle and integration files to a Raspberry Pi running HA.
# For pre-merge QA only. Production deploys use HACS.
#
# Required env vars:
#   SPLITSMART_PI_HOST   — hostname or IP of the Pi (e.g. homeassistant.local)
#   SPLITSMART_PI_USER   — SSH user (e.g. root or homeassistant)
#
# Optional env vars:
#   SPLITSMART_PI_PATH        — remote path (default: /config/custom_components/splitsmart)
#   SPLITSMART_PI_HA_TOKEN    — long-lived HA access token; if set, triggers a component
#                               reload via the REST API after rsync. Omit to skip restart.

set -euo pipefail

# ---------- configuration ----------

HOST="${SPLITSMART_PI_HOST:?SPLITSMART_PI_HOST is required}"
USER="${SPLITSMART_PI_USER:?SPLITSMART_PI_USER is required}"
REMOTE_PATH="${SPLITSMART_PI_PATH:-/config/custom_components/splitsmart}"
HA_TOKEN="${SPLITSMART_PI_HA_TOKEN:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
COMPONENT_DIR="${REPO_ROOT}/custom_components/splitsmart"
BUNDLE="${COMPONENT_DIR}/frontend/splitsmart-card.js"

# ---------- build ----------

echo "==> Building production bundle ..."

if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "    node_modules missing — running npm ci ..."
    (cd "${FRONTEND_DIR}" && npm ci)
fi

# Record mtime before build so we can confirm the bundle advanced.
pre_mtime=0
if [[ -f "${BUNDLE}" ]]; then
    pre_mtime=$(stat -c '%Y' "${BUNDLE}" 2>/dev/null || stat -f '%m' "${BUNDLE}" 2>/dev/null || echo 0)
fi

(cd "${FRONTEND_DIR}" && npm run build:prod)

post_mtime=$(stat -c '%Y' "${BUNDLE}" 2>/dev/null || stat -f '%m' "${BUNDLE}" 2>/dev/null || echo 0)

if [[ "${post_mtime}" -le "${pre_mtime}" ]]; then
    echo "ERROR: bundle mtime did not advance after build (pre=${pre_mtime} post=${post_mtime})" >&2
    exit 1
fi

echo "    Bundle built: ${BUNDLE}"

# ---------- rsync ----------

echo "==> Syncing to ${USER}@${HOST}:${REMOTE_PATH}/ ..."

rsync -av --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    "${COMPONENT_DIR}/" \
    "${USER}@${HOST}:${REMOTE_PATH}/"

echo "    Sync complete."

# ---------- optional restart ----------

if [[ -n "${HA_TOKEN}" ]]; then
    echo "==> Reloading Splitsmart integration via HA REST API ..."
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
        -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        "https://${HOST}/api/services/homeassistant/reload_config_entry" \
        --data '{}')
    if [[ "${STATUS}" == "200" || "${STATUS}" == "2"* ]]; then
        echo "    Reload requested (HTTP ${STATUS})."
    else
        echo "    WARNING: reload request returned HTTP ${STATUS}. Restart HA manually if needed."
    fi
else
    echo "    SPLITSMART_PI_HA_TOKEN not set — skipping automatic restart."
    echo "    Restart the integration manually: Settings → Devices & Services → Splitsmart → ⋯ → Reload."
fi

# ---------- cache-bust URL ----------

TIMESTAMP=$(date +%s)
echo ""
echo "==> Deploy complete. Verify the fresh bundle in DevTools:"
echo "    https://${HOST}/splitsmart-static/splitsmart-card.js?v=${TIMESTAMP}"

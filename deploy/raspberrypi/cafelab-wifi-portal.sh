#!/usr/bin/env bash
#
# CafeLab edge WiFi provisioning launcher (Part B of onboarding).
#
# Runs at boot. If the Pi already has an active WiFi connection it does
# nothing. Otherwise it opens a captive-portal access point ("CafeLab-Setup")
# using balena wifi-connect so the user can join their WiFi from a phone.
#
# Requires: NetworkManager + wifi-connect binary installed.

set -euo pipefail

PORTAL_SSID="${CAFELAB_PORTAL_SSID:-CafeLab-Setup}"
# Optional WPA2 password for the setup network (>= 8 chars). Empty = open AP.
PORTAL_PASSPHRASE="${CAFELAB_PORTAL_PASSPHRASE:-}"
WIFI_CONNECT="${CAFELAB_WIFI_CONNECT:-/usr/local/sbin/wifi-connect}"

# Give NetworkManager a moment to bring up an already-known network after boot.
sleep 15

if nmcli -t -f TYPE,STATE device status | grep -q '^wifi:connected'; then
    echo "[cafelab] WiFi already connected; captive portal not needed."
    exit 0
fi

echo "[cafelab] No WiFi connection found; starting provisioning portal '${PORTAL_SSID}'."

if [ -n "${PORTAL_PASSPHRASE}" ]; then
    exec "${WIFI_CONNECT}" --portal-ssid "${PORTAL_SSID}" --portal-passphrase "${PORTAL_PASSPHRASE}"
else
    exec "${WIFI_CONNECT}" --portal-ssid "${PORTAL_SSID}"
fi

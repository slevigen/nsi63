#!/bin/bash
# Installerer nsi63-sta-watchdog: kaster ut wifi-stasjoner som står i
# AP-ets tabell men ikke svarer på ping.
#
# Bakgrunn: brcmfmac (Broadcom-driveren) lar en gammel stasjonsoppføring
# blokkere re-autentisering etter urein frakobling (typisk ESP32-reflash).
# hostapds inaktivitets-polling hjelper ikke, fordi den frakoblede
# enhetens radio ACK-er pollene på maskinvarenivå — oppføringen ser
# "levende" ut. Kuren er eksplisitt deauthenticate, som dette scriptet
# automatiserer.
#
# Kjøres på Pi-en:  sudo bash install-sta-watchdog.sh

set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Kjør med sudo: sudo bash $0" >&2
  exit 1
fi

cat > /usr/local/sbin/nsi63-sta-watchdog <<'EOF'
#!/bin/bash
# Pinger alle assosierte wifi-stasjoner på lease-IP-en sin.
# 3 stille runder (~30 s) -> hostapd_cli deauthenticate.
LEASES=/var/lib/misc/dnsmasq.leases
declare -A fails
while true; do
  for mac in $(hostapd_cli all_sta 2>/dev/null \
               | grep -E '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'); do
    ip=$(awk -v m="$mac" 'tolower($2)==tolower(m) {print $3}' "$LEASES" 2>/dev/null | tail -1)
    # Ingen lease (statisk IP / DHCP ikke ferdig): kan ikke pinges —
    # hopp over i stedet for å telle mot utkastelse. Spøkelsene dette
    # skriptet jakter på (reflashede ESP32-er) har alltid hatt lease.
    if [ -z "$ip" ]; then
      fails[$mac]=0
      continue
    fi
    if ping -c1 -W1 -q "$ip" >/dev/null 2>&1; then
      fails[$mac]=0
    else
      fails[$mac]=$(( ${fails[$mac]:-0} + 1 ))
    fi
    if [ "${fails[$mac]:-0}" -ge 3 ]; then
      echo "kaster ut $mac (ip=$ip) etter 3 stille runder"
      hostapd_cli deauthenticate "$mac" >/dev/null 2>&1
      fails[$mac]=0
    fi
  done
  sleep 10
done
EOF
chmod +x /usr/local/sbin/nsi63-sta-watchdog

cat > /etc/systemd/system/nsi63-sta-watchdog.service <<'EOF'
[Unit]
Description=Kaster ut hengende wifi-stasjoner (brcmfmac-workaround)
After=hostapd.service
Wants=hostapd.service

[Service]
ExecStart=/usr/local/sbin/nsi63-sta-watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Rydd bort tjenesten fra tutela-tiden (ufarlig om den ikke finnes)
systemctl disable --now tutela-sta-watchdog.service 2>/dev/null || true
rm -f /etc/systemd/system/tutela-sta-watchdog.service \
      /usr/local/sbin/tutela-sta-watchdog

systemctl daemon-reload
# Samme som HAL-UI: --now starter ikke en tjeneste som alt kjører,
# så et gjenkjørt skript ville latt gammelt vaktbikkje-skript stå.
systemctl enable nsi63-sta-watchdog.service
systemctl restart nsi63-sta-watchdog.service

echo "Ferdig. Følg med:  journalctl -fu nsi63-sta-watchdog"

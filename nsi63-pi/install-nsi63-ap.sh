#!/bin/bash
# Setter opp anleggets AP (NSI63<ID>) med hostapd + dnsmasq.
#
# Bakgrunn: wpa_supplicant i AP-rolle rydder ikke opp i stasjonsoppføringer
# etter ureine frakoblinger (f.eks. ESP32 som reflashes), og nekter deretter
# re-autentisering (AUTH_EXPIRE/reason=2 på klienten). hostapd håndterer
# stasjonsutløp aktivt og er standardverktøyet for Pi-som-AP.
#
# Kjøres på Pi-en:  sudo bash install-nsi63-ap.sh [ANLEGGS-ID]
# ID (tre store bokstaver, f.eks. SKN) tas fra argumentet, ellers fra
# HAL-UI-ets anlegg.json om den finnes, ellers blir SSID-en bare NSI63.
# Etterpå:          sudo reboot

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Kjør med sudo: sudo bash $0" >&2
  exit 1
fi

# Anleggs-ID -> SSID NSI63<ID>. HAL-UI-et kan endre SSID-en senere
# (den skriver ssid= i hostapd.conf og restarter hostapd selv).
AID="${1:-}"
if [ -z "$AID" ] && [ -f /opt/nsi63-hal/anlegg.json ]; then
  AID=$(python3 -c "import json;print(json.load(open('/opt/nsi63-hal/anlegg.json')).get('id',''))" 2>/dev/null || true)
fi
AID=$(echo "$AID" | tr '[:lower:]' '[:upper:]')
if [ -n "$AID" ] && ! echo "$AID" | grep -qE '^[A-Z]{3}$'; then
  echo "Ugyldig anleggs-ID '$AID' (tre store bokstaver A-Z)" >&2
  exit 1
fi
SSID="NSI63${AID}"
PASS="norsksignalindustri"
CHANNEL=11
AP_IP="10.206.0.1"
DHCP_START="10.206.0.100"
DHCP_END="10.206.0.250"

echo "== 1/6: Installerer hostapd og dnsmasq =="
apt-get install -y hostapd dnsmasq
systemctl unmask hostapd

echo "== 2/6: hostapd-konfigurasjon =="
cat > /etc/hostapd/hostapd.conf <<EOF
# NSI63 — AP for sikringsanlegget
country_code=NO
interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=${CHANNEL}
ieee80211n=1
wmm_enabled=1

# Ren WPA2/CCMP — ESP32 nekter WPA1, og PMF (802.11w) er avslått
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_passphrase=${PASS}
rsn_pairwise=CCMP
ieee80211w=0

# Aktiv stasjonshåndtering — kuren mot hengende oppføringer:
# poll inaktive stasjoner, kast ut ved manglende ack, utløp etter 60 s
ap_max_inactivity=60
skip_inactivity_poll=0
disassoc_low_ack=1

# Kontrollgrensesnitt for hostapd_cli (all_sta, deauthenticate, ...)
ctrl_interface=/var/run/hostapd
ctrl_interface_group=0
EOF
chmod 600 /etc/hostapd/hostapd.conf
sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

echo "== 3/6: dnsmasq (DHCP for ${SSID}-nettet) =="
cat > /etc/dnsmasq.d/nsi63.conf <<EOF
# DHCP for NSI63-nettet (kun wlan0)
interface=wlan0
bind-dynamic
dhcp-range=${DHCP_START},${DHCP_END},12h
domain-needed
bogus-priv
EOF

echo "== 4/6: Statisk IP på wlan0 (systemd-enhet) =="
cat > /etc/systemd/system/wlan0-ap-ip.service <<EOF
[Unit]
Description=Statisk IP for wlan0 (NSI63-AP)
Before=hostapd.service dnsmasq.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip link set wlan0 up
ExecStart=/usr/sbin/ip addr replace ${AP_IP}/24 dev wlan0

[Install]
WantedBy=multi-user.target
EOF

mkdir -p /etc/systemd/system/hostapd.service.d
cat > /etc/systemd/system/hostapd.service.d/deps.conf <<EOF
[Unit]
Wants=wlan0-ap-ip.service
After=wlan0-ap-ip.service
EOF

echo "== 5/6: NetworkManager slipper wlan0 =="
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/99-unmanaged-wlan0.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:wlan0
EOF
# Relast NM straks - uten denne kjemper NM om wlan0 helt til reboot
# (skriptet anbefaler reboot uansett, men beltet koster ingenting)
systemctl reload NetworkManager 2>/dev/null || true
# Fjern gamle profiler/konfig fra tutela-tiden (ufarlig om alt er borte)
nmcli connection delete tutela-ap 2>/dev/null || true
rm -f /etc/dnsmasq.d/tutela.conf

echo "== 6/6: Aktiverer tjenester =="
systemctl daemon-reload
systemctl enable wlan0-ap-ip.service hostapd dnsmasq

echo
echo "Ferdig! Kjør:  sudo reboot"
echo "Etter reboot skal '${SSID}' være oppe på kanal ${CHANNEL} (hostapd)."
echo "Sjekk med:  systemctl status hostapd dnsmasq"
echo "            iw dev wlan0 info      (type AP, channel ${CHANNEL})"
echo "Eth0 og Mosquitto er uberørt."

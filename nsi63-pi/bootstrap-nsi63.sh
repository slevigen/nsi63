#!/bin/bash
# Gjør en FERSK Raspberry Pi OS Lite-installasjon til en komplett
# NSI63-Pi: AP (hostapd), vaktbikkje, Mosquitto og HAL-UI.
#
# Forutsetninger:
#  - Kortet er skrevet med Raspberry Pi Imager (hostname nsi63, SSH på,
#    midlertidig wifi/Ethernet med internett)
#  - Hele nsi63-pi-mappen er kopiert til Pi-en:
#      scp -r nsi63-pi bruker@nsi63.local:~
#
# Kjøres:  sudo bash nsi63-pi/bootstrap-nsi63.sh
#
# Etterpå: sudo reboot, koble til NSI63-wifi, åpne http://10.206.0.1:8080
# og bruk «Gjenopprett fra backup…» med siste nsi63-backup-*.json.

set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Kjør med sudo: sudo bash $0" >&2
  exit 1
fi
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==== 1/4: Mosquitto (MQTT-broker) ===="
apt-get update
apt-get install -y mosquitto mosquitto-clients
cat > /etc/mosquitto/conf.d/iot.conf <<'EOF'
listener 1883
allow_anonymous true

# WebSocket-lytter for det digitale stillerapparatet (/panel i
# HAL-UI): panelet er en ren MQTT-klient i nettleseren og kobler
# rett hit. Samme lukkede NSI63-nett, samme tillitsmodell som 1883.
listener 9001
protocol websockets

# Retained-lageret er masterens ENESTE kilde til HAL og forrigling
# (den lagrer bare anleggs-ID-en selv). Distroens standardoppsett har
# som regel persistens på, men vi sier det eksplisitt her i stedet for
# å stole på en default vi ikke eier. autosave_interval er 1800 s som
# standard — altfor lenge når strømmen kan ryke uten ryddig avslutning;
# 30 s koster ingenting på en konfig som endres sjelden.
persistence true
persistence_location /var/lib/mosquitto/
autosave_interval 30
EOF
systemctl enable mosquitto
systemctl restart mosquitto

# HAL-UI FØR aksesspunktet: install-nsi63-ap.sh leser anleggs-ID-en
# fra /opt/nsi63-hal/anlegg.json for å bygge SSID-en NSI63<ID>. Kjørte
# AP-skriptet først, fantes ikke filen ennå, og en fersk Pi endte
# ALLTID med SSID-en «NSI63» uten ID — masteren pares da mot et
# ID-løst nett. HAL-UI klarer seg fint uten AP-et i mellomtiden;
# MQTT-klienten kobler til av seg selv når 10.206.0.1 dukker opp.
echo "==== 2/4: HAL-UI ===="
bash "$HERE/hal-ui/install.sh"

echo "==== 3/4: Aksesspunkt (hostapd + dnsmasq) ===="
bash "$HERE/install-nsi63-ap.sh"

echo "==== 4/4: Stasjonsvaktbikkje ===="
bash "$HERE/install-sta-watchdog.sh"

echo
echo "Ferdig! Kjør:  sudo reboot"
echo "Deretter: koble til NSI63-wifi, åpne http://10.206.0.1:8080 og"
echo "gjenopprett konfigurasjonen fra siste nsi63-backup-*.json."

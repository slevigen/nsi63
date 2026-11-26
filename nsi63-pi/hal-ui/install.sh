#!/bin/bash
# Installerer HAL-konfigurasjonsappen på Pi-en.
# Kjøres fra hal-ui-mappen:  sudo bash install.sh

set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Kjør med sudo: sudo bash $0" >&2
  exit 1
fi

DIR=/opt/nsi63-hal
GAMMEL=/opt/tutela-hal
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== Installerer avhengigheter =="
apt-get install -y python3-flask python3-paho-mqtt

echo "== Kopierer appen til ${DIR} =="
mkdir -p "$DIR"
# Migrering fra tutela-tiden: ta med konfigfilene og skru av gammel tjeneste
if [ -d "$GAMMEL" ]; then
  for f in hal.json forrigling.json anlegg.json noder.json; do
    if [ -f "$GAMMEL/$f" ] && [ ! -f "$DIR/$f" ]; then cp "$GAMMEL/$f" "$DIR/"; fi
  done
  systemctl disable --now tutela-hal.service 2>/dev/null || true
  rm -f /etc/systemd/system/tutela-hal.service
fi
cp "$HERE/app.py" "$DIR/"
# Brukerflaten: HTML, CSS og JS som egne filer
rm -rf "$DIR/ui"
cp -R "$HERE/ui" "$DIR/ui"
# Stillerapparatet (/panel): samme glob som deploy-pi.sh. Manglet
# dette, svarte en fersk Pi 404 på /panel til første deploy.
for f in "$HERE"/panel.html "$HERE"/mqtt.min.js "$HERE"/*.ttf \
         "$HERE"/*.otf "$HERE"/*-OFL.txt; do
  [ -f "$f" ] && cp "$f" "$DIR/"
done
# Konfigen kopieres bare hvis den ikke finnes fra før (ikke overskriv
# konfig!). Alle tre må med: /panel tegner ingenting før både
# config/hal og config/forrigling er retained på brokeren, og med bare
# hal.json ble en fersk Pi stående på «Venter på konfigurasjon».
for f in hal.json forrigling.json anlegg.json; do
  if [ -f "$HERE/$f" ] && [ ! -f "$DIR/$f" ]; then
    cp "$HERE/$f" "$DIR/"
  fi
done

echo "== systemd-tjeneste =="
cat > /etc/systemd/system/nsi63-hal.service <<EOF
[Unit]
Description=HAL-konfigurasjon for sikringsanlegget (web-UI)
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
ExecStart=/usr/bin/python3 ${DIR}/app.py
WorkingDirectory=${DIR}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# enable --now er en NO-OP hvis tjenesten alt kjører — da ville den
# nettopp kopierte app.py først trådt i kraft ved neste reboot.
systemctl enable nsi63-hal.service
systemctl restart nsi63-hal.service

echo
echo "Ferdig! Åpne  http://10.206.0.1:8080  fra en enhet på NSI63-nettet."
echo "Logg:  journalctl -fu nsi63-hal"

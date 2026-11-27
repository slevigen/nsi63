#!/bin/bash
# Røyktest av installasjonen: kjører bootstrap-nsi63.sh på et FERSKT
# Debian og sjekker at Pi-en ender opp brukbar — /panel svarer, og alle
# tre konfigtemaene ligger retained på brokeren.
#
# Kjøres som root i en tom container, aldri på en ekte Pi:
#
#   docker run --rm -v "$PWD/nsi63-pi:/kilde:ro" debian:trixie \
#     bash /kilde/tester/roykttest-installasjon.sh /kilde
#
# Argumentet er nsi63-pi-mappen som skal testes. CI kjører den både på
# repoets mappe (med anleggskonfig) og på det offentlige treet fra
# publiser.sh (uten konfig, slik kunden får det).
#
# Feilene dette fanger, og som ingen enhetstest ser, er alle fra
# virkeligheten:
#  - Mosquitto 2.0.21 (Debian 13) startet ikke: persistence_location
#    var satt to ganger
#  - install.sh kopierte ikke panelfilene: /panel ga 404
#  - install.sh kopierte ikke forrigling.json: panelet ventet for alltid
#  - AP-skriptet kjørt før HAL-UI: SSID-en fikk aldri anleggs-ID
#
# Det som IKKE kan testes i en container: hostapd, dnsmasq og wlan0
# (ingen radio), og vaktbikkja (trenger hostapd_cli). For dem sjekkes
# bare at konfigfilene blir riktige.

set -euo pipefail
KILDE="${1:?bruk: $0 <nsi63-pi-mappe>}"
[ "$(id -u)" -eq 0 ] || { echo "må kjøres som root (i en container)" >&2; exit 1; }
[ -f /.dockerenv ] || [ -n "${CI:-}" ] || [ -n "${NSI63_ROYKTEST_TVING:-}" ] || {
  echo "ser ikke ut som en container — nekter å kjøre (NSI63_ROYKTEST_TVING=1 overstyrer)" >&2
  exit 1
}

feil=0
ok()   { echo "  ok    $*"; }
galt() { echo "  FEIL  $*" >&2; feil=1; }
steg() { echo; echo "==== $* ===="; }

steg "Forbereder containeren"
export DEBIAN_FRONTEND=noninteractive
# Ingen tjenester skal startes av apt selv: det er bootstrap-skriptets
# systemctl-kall som skal gjøre det, og de er det vi tester.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
apt-get update -qq
# Det Raspberry Pi OS Lite har fra før, og som skriptene forutsetter
apt-get install -y -qq python3 curl procps iproute2 >/dev/null

# Stand-in for systemctl. Containeren har ikke systemd, så tjenestene
# startes direkte. Det som teller er at restart av mosquitto FEILER når
# konfigen er ugyldig, slik den gjør på en ekte Pi.
LOGG=/var/log/falsk-systemctl.log
cat > /usr/local/bin/systemctl <<'EOF'
#!/bin/bash
echo "systemctl $*" >> /var/log/falsk-systemctl.log
verb="$1"; shift || true
enheter=()
for a in "$@"; do case "$a" in -*) ;; *) enheter+=("${a%.service}");; esac; done
start_mosquitto() {
  pkill -x mosquitto 2>/dev/null || true
  sleep 0.5
  mkdir -p /run/mosquitto /var/lib/mosquitto /var/log/mosquitto
  chown mosquitto: /run/mosquitto /var/lib/mosquitto /var/log/mosquitto 2>/dev/null || true
  mosquitto -c /etc/mosquitto/mosquitto.conf -d || {
    echo "mosquitto nektet å starte" >&2; return 1; }
}
start_hal() {
  pkill -f /opt/nsi63-hal/app.py 2>/dev/null || true
  sleep 0.5
  (cd /opt/nsi63-hal && nohup python3 /opt/nsi63-hal/app.py \
     >> /var/log/nsi63-hal.log 2>&1 &)
}
case "$verb" in
  restart|start)
    for e in "${enheter[@]}"; do
      case "$e" in
        mosquitto) start_mosquitto || exit 1 ;;
        nsi63-hal) start_hal ;;
        *) ;;   # hostapd, dnsmasq, vaktbikkja: ingen radio her
      esac
    done ;;
  is-active)
    case "${enheter[0]:-}" in
      mosquitto) pgrep -x mosquitto >/dev/null ;;
      nsi63-hal) pgrep -f /opt/nsi63-hal/app.py >/dev/null ;;
      *) exit 3 ;;
    esac ;;
  *) ;;         # enable, disable, unmask, daemon-reload, reload
esac
EOF
chmod +x /usr/local/bin/systemctl
# AP-skriptet kaller nmcli for å rydde gamle profiler; det finnes ikke her
printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/nmcli
chmod +x /usr/local/bin/nmcli

# Skriptene kjøres fra en kopi, som når mappen er scp-et til Pi-en
rm -rf /root/nsi63-pi
cp -R "$KILDE" /root/nsi63-pi
cd /root

vent_paa() {   # vent_paa <sekunder> <kommando...>
  local t="$1"; shift
  for _ in $(seq 1 "$((t * 2))"); do "$@" >/dev/null 2>&1 && return 0; sleep 0.5; done
  return 1
}

sjekk_installasjon() {
  steg "Tjenester"
  pgrep -x mosquitto >/dev/null && ok "mosquitto kjører" || galt "mosquitto kjører ikke"
  vent_paa 20 curl -sf http://127.0.0.1:8080/ \
    && ok "HAL-UI svarer på 8080" \
    || { galt "HAL-UI svarer ikke"; tail -30 /var/log/nsi63-hal.log >&2 || true; }

  steg "Sider"
  for sti in / /ui/app.js /panel /panel/mqtt.js /panel/manifest.json \
             /panel/icon.svg /panel/icon-192.png; do
    kode=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8080$sti")
    [ "$kode" = 200 ] && ok "$sti → 200" || galt "$sti → $kode"
  done
  # Instruksen er valgfri: 200 når treet har en, ellers 404 (og da
  # viser panelet ingen Instruks-knapp)
  forv=404; [ -f /root/nsi63-pi/hal-ui/instruks.md ] && forv=200
  kode=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/panel/instruks)
  [ "$kode" = "$forv" ] && ok "/panel/instruks → $kode" \
    || galt "/panel/instruks → $kode, ventet $forv"
  # Fontene panelet ber om skal finnes; en manglende font faller
  # STILLE tilbake til en annen
  for f in /root/nsi63-pi/hal-ui/*.ttf /root/nsi63-pi/hal-ui/*.otf; do
    [ -e "$f" ] || continue
    n=$(basename "$f")
    kode=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8080/panel/$n")
    [ "$kode" = 200 ] && ok "/panel/$n → 200" || galt "/panel/$n → $kode"
  done

  steg "Retained konfig på brokeren"
  # Med konfig i treet skal alle tre være der — ellers står panelet og
  # venter. Uten konfig (offentlig tre) skal HAL-UI IKKE publisere en
  # tom HAL som kunne overskrevet en masters flash-kopi.
  temaer() {
    timeout 5 mosquitto_sub -h 127.0.0.1 -t 'nsi63/config/#' -v \
      --retained-only -W 2 2>/dev/null | cut -d' ' -f1 | sort -u
  }
  forventet="nsi63/config/anlegg"
  if [ -f /root/nsi63-pi/hal-ui/hal.json ]; then
    forventet="nsi63/config/anlegg nsi63/config/forrigling nsi63/config/hal"
  fi
  for t in $forventet; do
    vent_paa 15 bash -c "timeout 5 mosquitto_sub -h 127.0.0.1 -t '$t' --retained-only -C 1 -W 2" \
      && ok "$t retained" || galt "$t mangler retained"
  done
  if [ ! -f /root/nsi63-pi/hal-ui/hal.json ]; then
    temaer | grep -qx nsi63/config/hal \
      && galt "tom HAL ble publisert retained" || ok "ingen tom HAL publisert"
  fi
  # WebSocket-lytteren panelet bruker
  vent_paa 5 bash -c '</dev/tcp/127.0.0.1/9001' \
    && ok "WebSocket-lytter på 9001" || galt "ingen lytter på 9001"

  steg "Aksesspunkt og vaktbikkje (bare filene)"
  aid=$(python3 -c "import json;print(json.load(open('/opt/nsi63-hal/anlegg.json')).get('id',''))" 2>/dev/null || true)
  grep -qx "ssid=NSI63${aid}" /etc/hostapd/hostapd.conf \
    && ok "ssid=NSI63${aid}" \
    || galt "SSID: fikk '$(grep ^ssid= /etc/hostapd/hostapd.conf)', ventet NSI63${aid}"
  grep -qx 'channel=11' /etc/hostapd/hostapd.conf \
    && ok "kanal 11" || galt "kanal er ikke 11 (ESP-NOW-kanalen)"
  grep -q '10.206.0.100' /etc/dnsmasq.d/nsi63.conf \
    && ok "DHCP-område" || galt "DHCP-området mangler"
  bash -n /usr/local/sbin/nsi63-sta-watchdog \
    && ok "vaktbikkja er gyldig bash" || galt "vaktbikkja har syntaksfeil"
}

steg "1. kjøring av bootstrap-nsi63.sh"
bash /root/nsi63-pi/bootstrap-nsi63.sh || galt "bootstrap feilet (exit $?)"
sjekk_installasjon

steg "2. kjøring: skal være trygg og ikke røre konfigen"
# Merk konfigen som om den var redigert i UI-et. En gjenkjøring av
# installasjonen skal aldri overskrive den.
python3 - <<'EOF'
import json
p = "/opt/nsi63-hal/anlegg.json"
try:
    d = json.load(open(p))
except FileNotFoundError:
    d = {"id": ""}
d["navn"] = "MERKET"
json.dump(d, open(p, "w"))
EOF
bash /root/nsi63-pi/bootstrap-nsi63.sh >/dev/null || galt "2. kjøring feilet"
grep -q MERKET /opt/nsi63-hal/anlegg.json \
  && ok "anlegg.json ble ikke overskrevet" || galt "anlegg.json ble overskrevet"
sjekk_installasjon

echo
echo "systemctl-kall underveis:"; sort -u "$LOGG" | sed 's/^/  /'
echo
if [ "$feil" = 0 ]; then echo "RØYKTEST OK"; else echo "RØYKTEST FEILET" >&2; fi
exit "$feil"

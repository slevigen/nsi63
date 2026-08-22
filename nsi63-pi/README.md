# nsi63-pi — AP-oppsett med hostapd

Flytter AP-rollen på Pi-en fra NetworkManager/wpa_supplicant til
hostapd + dnsmasq. Bakgrunn: wpa_supplicant i AP-rolle lot hengende
stasjonsoppføringer (etter f.eks. ESP32-reflash) blokkere
re-autentisering — klienten fikk AUTH_EXPIRE (reason=2) til
oppføringen ble slettet manuelt. hostapd håndterer dette selv
(inaktivitets-polling, disassoc ved manglende ack).

## Installasjon

Fra maskinen din, kopier scriptet til Pi-en og kjør det:

```bash
scp install-nsi63-ap.sh BRUKER@VERT:~
ssh BRUKER@VERT
sudo bash install-nsi63-ap.sh
sudo reboot
```

`BRUKER` og `VERT` er brukernavnet og vertsnavnet du satte da du skrev
SD-kortet med Raspberry Pi Imager — altså `<vertsnavn>.local` på et
vanlig hjemmenett.

Er du allerede koblet til NSI63-wifien, bruk `10.206.0.1` som vert.
Pi-en svarer alltid på den adressen. Vertsnavnet blir `nsi63<id>.local`
(f.eks. `nsi63abc.local`) først etter at anleggs-ID-en er satt i
HAL-UI — ikke ved førstegangsinstallasjonen.

## Hva scriptet gjør

1. Installerer hostapd + dnsmasq
2. `/etc/hostapd/hostapd.conf` — SSID `NSI63<ID>`, kanal 11, ren
   WPA2/CCMP, PMF av, aktiv stasjonshåndtering
3. `/etc/dnsmasq.d/nsi63.conf` — DHCP 10.206.0.100–250 på wlan0
4. systemd-enhet som setter 10.206.0.1/24 på wlan0 før hostapd
5. NetworkManager instrueres til å ignorere wlan0 (eth0 uberørt),
   og gamle profiler fra tutela-tiden slettes
6. Aktiverer tjenestene for boot

## Verifisering etter reboot

```bash
systemctl status hostapd dnsmasq   # begge active (running)
iw dev wlan0 info                  # type AP, channel 11
sudo hostapd_cli all_sta           # tilkoblede klienter
```

Mosquitto og eth0 er uberørt — nodene og masteren bruker samme
SSID/passord/IP som før og skal koble seg til uten endringer.

## Endre innstillinger senere

- SSID/passord/kanal: rediger `/etc/hostapd/hostapd.conf`,
  deretter `sudo systemctl restart hostapd`.
  NB: bytter du kanal, må `ESPNOW_CHANNEL` i nsi63-espnow endres
  og alle noder + master reflashes!
- DHCP-område: `/etc/dnsmasq.d/nsi63.conf`, restart dnsmasq.

## Tilbake til NM-oppsettet (om nødvendig)

```bash
sudo systemctl disable --now hostapd dnsmasq wlan0-ap-ip.service
sudo rm /etc/NetworkManager/conf.d/99-unmanaged-wlan0.conf
sudo systemctl restart NetworkManager
# og gjenskap AP-profilen med nmcli (se nsi63-espnow/README)
```

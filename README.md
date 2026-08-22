# NSI63 — sikringsanlegg for modelljernbane

Et sikringsanlegg etter norsk **NSI-63**-forbilde for FREMO-moduler:
stillerapparat med stillere og kontrollamper, hovedsignaler og
forsignaler, sporfelter, sentralstilte veksler, sporsperrer og
togveier med full forrigling.

Dette repoet inneholder **Pi-siden** — aksesspunkt, MQTT-broker,
web-grensesnittet der anlegget settes opp, og det digitale
stillerapparatet. Firmwaren til ESP32-enhetene distribueres som
ferdige binærer under [Releases](../../releases).

## Slik henger det sammen

```
      stillerapparat / anlegget — lamper, knapper, sporfeltsensorer
            │ I2C + GPIO         │ I2C + GPIO
      ┌─────┴─────┐        ┌─────┴─────┐
      │   NODE    │        │   NODE    │  · · ·   dumme og tilstandsløse
      └─────┬─────┘        └─────┬─────┘          identitet = MAC-adressen
            └──────────┬─────────┘   ESP-NOW, kanal 11 — kontrollplan
                 ┌─────┴─────┐
                 │  MASTER   │   all sikkerhetslogikk
                 └─────┬─────┘
                       │ wifi / MQTT — adminplan
                 ┌─────┴─────┐
                 │    PI     │   AP · broker · web-UI
                 └───────────┘

      Master og noder kjører SAMME binær — rollen velges med knappegest.
```

**Nodene** er utskiftbare og identiske — identiteten er MAC-adressen,
og all jernbanelogikk bor i master. **Master** kjører signal- og
forriglingsmotoren: atomisk fastlegging, signalfall ved belegg,
to-trinns hjelpeutløsning, sekvensiell vekselomlegging. **Pi-en** er
ren infrastruktur — anlegget kjører videre selv om den faller ut.

Master og noder kjører samme firmware. Rollen velges med en
knappegest: hold frontknappen inne i 3 sekunder fra strømpåslag, så
blir enheten master.

## Installasjon

1. Skriv Raspberry Pi OS Lite til et SD-kort (Pi 3, 4 eller Zero 2 W).
2. Kopier `nsi63-pi/` over til Pi-en og kjør:

```bash
sudo bash nsi63-pi/bootstrap-nsi63.sh
```

Skriptet installerer mosquitto, setter opp aksesspunktet med hostapd
og dnsmasq, og starter web-grensesnittet.

3. Koble til wifi-nettet `NSI63` (passord `norsksignalindustri`) og
   åpne `http://10.206.0.1:8080`.
4. Sett anleggs-ID-en (tre bokstaver), definer objektene og lag
   togveiene.

En fersk installasjon starter blank. `nsi63-pi/hal-ui/eksempler/`
inneholder et ferdig oppsett for stasjonen Grindvoll som kan
importeres og bygges videre på.

## Firmware

Last ned `nsi63-atoms3-<byggestempel>.bin` fra
[Releases](../../releases) og last den opp under «Last opp firmware»
på Noder-fanen. Master og noder henter samme binær trådløst; MD5
verifiseres mot passiv partisjon, så en feilet nedlasting lar gammel
firmware kjøre videre.

Firmwaren er bundet til enheter levert av Norsk Signalindustri og
booter ikke på annen maskinvare.

## Maskinvare

| Enhet | Rolle |
|-------|-------|
| Raspberry Pi 3/4/Zero 2 W | aksesspunkt, broker, web-UI |
| M5 AtomS3 Lite | master eller node (Grove I2C: SDA 2 / SCL 1) |
| PCA9685 (0x40–0x43) | 16 PWM-utganger — signallamper, kontrollamper |
| PCF8574 (0x20–0x23) | 8 innganger — trykknapper, sporfelt (aktiv lav) |

Signallamper kobles felles anode. Provisjonerte AtomS3-enheter fås
fra Norsk Signalindustri.

## JMRI

Brokeren følger JMRI-standarden på `trains/#` i tillegg til den
interne flaten `nsi63/#`, så JMRI kan kobles rett på som betjenings-
og visningsflate.

## Test

`nsi63-pi/mqtt-test/` er en kontraktstest for forriglingen som kjører
mot en ekte master over anleggets broker. Den leser topologien fra
konfigurasjonen, så den kan kjøres uendret mot et hvilket som helst
NSI63-anlegg — på benken, aldri mot et anlegg i trafikk.

## Lisens

GNU General Public License v3.0 — se [LICENSE](LICENSE). Tredjeparts
komponenter er listet i [TREDJEPART.md](TREDJEPART.md).

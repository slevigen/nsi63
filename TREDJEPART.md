# Tredjepartskomponenter

Koden i dette repoet er GPL-3.0 (se `LICENSE`). Følgende filer er
tredjeparts verk som følger med, under sine egne lisenser. De er
selvstendige verk, samlet med — ikke avledet av — NSI63-koden.

## MQTT.js

`nsi63-pi/hal-ui/mqtt.min.js`

MQTT-klienten det digitale stillerapparatet (`/panel`) bruker over
WebSocket. Kopien er bygget og minifisert av prosjektet selv, uten
lisenshode.

- Prosjekt: https://github.com/mqttjs/MQTT.js
- Lisens: dobbeltlisensiert **EPL-2.0** eller **EDL-1.0** (BSD-3)
- Opphavsrett: MQTT.js-bidragsyterne

Filen serveres lokalt av Flask. Panelet henter aldri noe utenfra —
anleggsnettet har ingen ruting til internett.

## Routed Gothic

`nsi63-pi/hal-ui/routed-gothic.ttf`

Skiltfonten på sporplanen i stillerapparatet.

- Opphavsmann: Camillo Osias
- Lisens: **SIL Open Font License 1.1**

OFL tillater bruk, endring og videredistribusjon sammen med
programvare. Fonten kan ikke selges for seg selv, og et endret verk
kan ikke bruke det reserverte fontnavnet.

## Nordvester

`nsi63-pi/hal-ui/Nordvester-Regular.ttf`
(lisens og opphavsmerknad: `nsi63-pi/hal-ui/nordvester-OFL.txt`)

Stasjonsnavnene i stillerapparatet. Nordvester er en endret utgave av
Norwester, utvidet med Æ, Ø og Å (også i kapitéform) og med justerte
vertikale mål. Den har nytt navn fordi «Norwester» er et reservert
fontnavn.

- Opprinnelig font: Norwester, © 2013 Jamie Wilson (jamiewilson.io)
- Lisens: **SIL Open Font License 1.1**

Samme vilkår som for Routed Gothic over: fri bruk og videredistribusjon
sammen med programvare, ikke salg av fonten alene, og et endret verk
kan ikke bruke det reserverte navnet.

## Kjøretidsavhengigheter

Disse installeres av `bootstrap-nsi63.sh` fra distribusjonens
pakkebrønn og følger ikke med i repoet: Flask (BSD-3),
paho-mqtt (EPL-2.0/EDL-1.0), Mosquitto (EPL-2.0/EDL-1.0),
hostapd og dnsmasq (GPL-2.0).

# MQTT-basert kontraktstest for forriglingen

Kjører mot en **ekte master** over anleggets broker — samme flate som
HAL-UI-et og det **digitale stillerapparatet** (`/panel` på Pi-en)
bruker. Suiten er dermed både regresjonstest for forriglingsmotoren og
API-kontrakt for panelet: endres flaten, skal en test knekke først.

## Bruk

```bash
pip install pytest paho-mqtt
cd nsi63-pi/mqtt-test
pytest -v                        # broker på 10.206.0.1 (NSI63-nettet)
NSI63_HOST=127.0.0.1 pytest -v   # kjørt på selve Pi-en
```

## Forutsetninger

- Pi + master i drift **på benken** — aldri mot et anlegg i trafikk:
  suiten stiller og river togveier og simulerer sporfeltbelegg.
- Testmodus AV (suiten tester forriglingen, ikke omgåelsen).
- Konfig lastet: topologien (togveier, felt, veksler, låsegrupper)
  leses fra `../hal-ui/hal.json` og `forrigling.json` (overstyr mappen
  med `NSI63_KONFIG`), så suiten følger anlegget og kan kjøres uendret
  mot et hvilket som helst NSI63-anlegg.
- Suiten rydder anlegget før hver test og etter siste (simene til
  «auto»/«av», alle togveier løses ut).
- Låsetestene krever at minst én togvei har en låsegruppe i «Krever
  låst» (feltet `laaser`). Det er der en håndstilt veksel kommer inn i
  forriglingen — den kan ikke kommanderes, men låsen som holder den
  garanterer stillingen. Uten en slik togvei hopper testene over.

## Testene

### Togvei og forrigling

| Test | Kontrakt |
|------|----------|
| sikring_gir_kjorsignal | `sikre` → state `aktiv` → hovedsignal viser kjørbilde |
| hjelpeutlosning_i_to_trinn | utløs på kjørsignal avvises; `stopp` = trinn 1 (forriglet); `hjelpeutlos` = trinn 2 |
| belagt_felt_avviser_sikring | belagt togspor → `avvist`, state forblir `ledig` |
| fiendtlig_togvei_avvises | togvei nr. 2 med delte felt avvises |
| signalfall_ved_belegg | belegg i togveien feller signalet, togveien forblir forriglet |
| sistevognskontroll | utløsningsfelt belagt→fritt → `klar-utlos` → `kvitter` → `ledig` (krever linjefelt uten linjeblokk) |
| veksel_laast_av_togvei | manuell omlegging av forriglet veksel → `avvist: laast av togvei` |
| signalstopp_sperrer_sikring | signalstopp på → sikring avvises |

### Samlelås — elektrisk frigitt kontrollnøkkel

| Test | Kontrakt |
|------|----------|
| samlelaas_frigi_og_sperr | `frigi` → state `frigitt`; `sperr` → `sperret` (nøkkelen simulert inne) |
| samlelaas_frigitt_sperrer_sikring | frigitt lås → togvei som KREVER den `avvist`, state forblir `ledig` |
| samlelaas_frigivning_avvist_av_togvei | forriglet togvei som krever låsen → `frigivning avvist`, låsen forblir `sperret` (tosidig forrigling) |
| samlelaas_avviser_omlegging | omlegging av veksel i «omfatter» → `avvist: laast av samlelaas` |
| samlelaas_nodutlosning | nøkkelen tatt ut uten frigivning under aktiv togvei → `NOEDUTLOSNING`, signal i stopp STRAKS, togveien fortsatt forriglet |

### Rigel — direkte elektrisk lås

| Test | Kontrakt |
|------|----------|
| rigel_sperret_avviser_omlegging | sperret rigel → omlegging av objekt i «omfatter» → `avvist: laast av rigel` |
| rigel_frigi_omlegging_og_sperr | full sekvens: `frigi` → objektet legges om og tilbake → `sperr` → `etterlop` (10 s) → `sperret` |
| rigel_frigitt_sperrer_sikring | frigitt rigel → togvei som KREVER den `avvist` |

Rigeltestene håndterer både veksler og sporsperrer i «omfatter» —
temanavn og ord (`normal`/`avvik` mot `paalagt`/`avlagt`) velges av
objekttypen.

### Stillerdytt-paring

Panelet lener seg på nøyaktig denne mekanikken: to dytt (linjefelt +
togspor) innen 2 sekunder er én betjening, og retningene er
geometriske — «venstre ende + dytt mot høyre = inn i stasjonen».

| Test | Kontrakt |
|------|----------|
| stillerdytt_sikrer_togvei | to dytt samme vei innen vinduet → togveien sikres → kjørsignal |
| stillerdytt_vindu_paa_to_sekunder | dytt mer enn 2 s fra hverandre → ingen betjening |
| stillerdytt_hjelpeutlosning | stillerne MOT hverandre = trinn 1 (signal i stopp, fortsatt forriglet); FRA hverandre = trinn 2 (tidsreléet kobles inn) |

### Signalmotor

| Test | Kontrakt |
|------|----------|
| forsignal_sporgating_ved_felles_utkjor | innkjør til spor UTEN aktiv utkjøring → forsignalet viser `forvent-stopp` selv om det felles utkjørsignalet viser kjør for nabosporet |
| forsignal_folger_utkjor_for_eget_spor | motstykket: eget spor har aktiv utkjøring → forsignalet følger utkjørsignalets bilde |
| skiftesignal_automatisk_forbudt_under_omlegging | høyt skiftesignal på (42) → veksel i området legges om → automatisk `skifting-forbudt` (41) → `skifting-tillatt` igjen ved bekreftet stilling |

Tester hvis forutsetning ikke finnes i konfigen hoppes over med
begrunnelse — f.eks. ingen togvei uten linjeblokk, ingen samlelås
eller rigel som sperrer noen togvei, intet skiftesignal med
sentralstilt veksel, intet montert forsignal mot et felles
utkjørsignal. Hele suiten hopper rent hvis broker eller master ikke er
tilgjengelig.

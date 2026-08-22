#!/usr/bin/env python3
"""HAL-konfigurasjon for sikringsanlegget (nsi63) — v4.

Datamodell:
- Signaltyper angir ANTALL lamper (posisjonelle: lampe 1..n fra
  førsteporten) og signalbilder (av/pa/blink per lampeposisjon).
  MERK: bildedefinisjonene er PLASSHOLDERE — de riktige NSI-63-bildene
  korrigeres i hal.json (filen eier definisjonene etter første lagring).
- Bindinger per funksjonstype:
    signaler:      "anlegg" + valgfri "panel" (stillerapparat, 1:1)
    sporfelt:      1..N "sensor" (logisk OR — feltet krysser seksjoner,
                   men logikken ser ETT sporfelt) + valgfri "panel"
    veksel(-lokal): "ut-normal", "ut-avvik" (motorutganger) +
                   "sensor-normal", "sensor-avvik" (stillingskontroll)
    andre:         "anlegg"
- Blink/glødefade renderes i noden på 1 Hz-pulsens fase.

Lagring publiserer RETAINED til nsi63/config/hal; master kvitterer på
nsi63/master/hal. Nås på http://10.206.0.1:8080
"""

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, Response, send_file

HAL_FILE = Path(__file__).resolve().parent / "hal.json"
FORRIGLING_FILE = Path(__file__).resolve().parent / "forrigling.json"
MQTT_HOST = "127.0.0.1"
# MQTT-rota er FLAT og felles for alle anlegg (hver Pi = egen broker,
# så anleggene kolliderer aldri lokalt). Skal stasjoner samkjøres
# sentralt en gang, remapper en mosquitto-bro prefikset per stasjon
# (nsi63/# -> nsi63/skn/# sentralt) — én konfiglinje, null kodeendring.
ROT = "nsi63/"

# ---------- MASTERENS KAPASITETSGRENSER ----------
# Speiler konstantene i nsi63-espnow/src/{master,common}.h. Master
# BRYTER UT av parseløkkene når en grense nås — uten melding, uten
# logg. En konfig som er for stor blir altså stille avkortet, og
# «master/hal»-kvitteringen viser bare et lavere tall som ingen
# sammenlikner mot. Endres en grense i firmwaren, MÅ den endres her.
#
# Master varsler nå også selv (nsi63/master/melding) hvis den likevel
# må avkorte — f.eks. ved håndredigert JSON eller en eldre HAL-UI.
MAX_FUNKSJONER    = 96    # kMaxHal
MAX_BINDINGER     = 16    # kMaxBind
MAX_SIGNALTYPER   = 10    # kMaxSigTypes
MAX_SKIFT_VEKSLER = 4     # kMaxSkiftVeksler
MAX_TOGVEIER      = 32    # kMaxTogveier
MAX_TV_VEKSLER    = 6     # kMaxTvVeksler
MAX_TV_FELT       = 8     # kMaxTvFelt
MAX_TV_LAASER     = 3     # kMaxTvLaaser
# PubSubClient-bufferen i master (setBufferSize). HELE MQTT-pakken må
# få plass — nyttelast + tema + header — ellers forkaster biblioteket
# meldingen i STILLHET: callbacket kjører aldri, master beholder
# gammel konfig, og UI-et svarer «lagret». Marginen dekker tema
# (~20 byte), MQTT-header og litt slark.
MASTER_MQTT_BUFFER = 16384
MAX_PAYLOAD        = MASTER_MQTT_BUFFER - 512
CONFIG_TOPIC = ROT + "config/hal"
NODES_TOPIC = ROT + "master/nodes"
MASTER_ACK_TOPIC = ROT + "master/hal"
MASTER_INFO_TOPIC = ROT + "master/info"
MASTER_STATUS_TOPIC = ROT + "master/status"
CONFLICT_TOPIC = ROT + "master/conflict"
FORRIGLING_TOPIC = ROT + "config/forrigling"
FORRIGLING_ACK_TOPIC = ROT + "master/forrigling"
ANLEGG_FILE = Path(__file__).resolve().parent / "anlegg.json"
ANLEGG_TOPIC = ROT + "config/anlegg"           # UI -> master (retained)
ANLEGG_ACK_TOPIC = ROT + "master/anlegg"       # masterens kvittering
MELDING_TOPIC = ROT + "master/melding"         # driftsadvarsler (ren tekst)

# Signalbilder etter NSI-63 (bekreftet av anleggseier).
# Lampekonvensjon (= koblingsrekkefølge fra førsteporten):
#   hovedsignal3: lampe 1 = H1 grønn øvre, 2 = H2 rød, 3 = H3 grønn nedre
#   forsignal2:   lampe 1 = F1 gul,        2 = F2 grønn
# "signalnr" er dokumentasjon (signalnummer i regelverket).
# MERK: lampebildene for skiftesignal2 er utledet av at det er den
# NEDRE lamperekken som ble fjernet på fjernstyrte anlegg — verifiser
# rekkefølgen mot forbildet.
# Etter første lagring eier hal.json definisjonene, og korrigeres der.
SIGNALTYPER_DEFAULT = {
    "hovedsignal3": {
        "klasse": "hovedsignal",
        "lamper": 3,
        "normalbilde": "stopp",   # rolle velger variant: innkjør 20A, utkjør 20B
        "bilder": {
            "stopp-blink":   ["av", "blink", "av"],   # 20A Stopp (blink H2)
            "stopp":         ["av", "pa", "av"],      # 20B Stopp (fast H2)
            "kjor-redusert": ["pa", "av", "av"],      # 21  (H1)
            "kjor":          ["pa", "av", "pa"],      # 22  (H1 + H3)
        },
        "signalnr": {"stopp-blink": "20A", "stopp": "20B",
                     "kjor-redusert": "21", "kjor": "22"},
    },
    # Tolys utkjørhovedsignal: for togspor der utkjøring ALLTID går
    # over veksel i avvik — 22 (to grønne) finnes ikke, tredje lys er
    # utelatt. Alltid rolle utkjør. Lampe 1 = H1 grønn, 2 = H2 rød
    # (samme koblingsrekkefølge som de to første på hovedsignal3).
    "hovedsignal2": {
        "klasse": "hovedsignal",
        "lamper": 2,
        "normalbilde": "stopp",
        "bilder": {
            "stopp":         ["av", "pa"],   # 20B Stopp
            "kjor-redusert": ["pa", "av"],   # 21
        },
        "signalnr": {"stopp": "20B", "kjor-redusert": "21"},
    },
    "forsignal2": {
        "klasse": "forsignal",
        "lamper": 2,
        "normalbilde": "forvent-stopp",   # montert_med hovedsignal: "slukket"
        "bilder": {
            "forvent-stopp":         ["blink", "av"],     # 23 (blink F1)
            "forvent-kjor-redusert": ["blink", "blink"],  # 24 (blink F1+F2)
            "forvent-kjor":          ["av", "blink"],     # 25 (blink F2)
            "slukket":               ["av", "av"],        # montert med
        },                                                # hovedsignal i stopp
        "signalnr": {"forvent-stopp": "23",
                     "forvent-kjor-redusert": "24", "forvent-kjor": "25"},
        # varsler_om: forsignalbildet avledes av hovedsignalet det
        # varsler om, etter denne tabellen (hovedbilde -> forsignalbilde)
        "folger": {
            "stopp":         "forvent-stopp",
            "stopp-blink":   "forvent-stopp",
            "kjor":          "forvent-kjor",
            "kjor-redusert": "forvent-kjor-redusert",
        },
    },
    # Høyt skiftesignal (§ 8-22) — egen klasse. Signalet ble bygget med
    # TO lamperekker: 41 «Skifting forbudt» (nedre) og 42 «Skifting
    # tillatt» (øvre). På FJERNSTYRTE stasjoner ble den nedre rekken
    # fjernet i første halvdel av 1970-årene (lamper og linser tatt ut,
    # åpningen dekket med sortmalt plate), fordi bildet ble ansett
    # unødvendig der og fordi en rekke som lyser nesten konstant brenner
    # mye pærer. Derfor to typer:
    #
    #   skiftesignal2 — anlegg UTEN fjernstyring. Begge bildene finnes,
    #                   og 41 er normalbildet og lyser FAST.
    #   skiftesignal1 — fjernstyrt anlegg. Bare 42; mørkt signal er
    #                   fravær av signal, ikke et forbudssignal. Det er
    #                   denne formen A-sirkulære 16/1973 pkt. 3 for
    #                   Grindvoll beskriver, og Grindvoll var fjernstyrt.
    #
    # Sokna var IKKE fjernstyrt (NSI-63 fra 1962, fjernstyring først på
    # 80-tallet), og et øyenvitne bekrefter at stasjonen på 60-tallet
    # viste «enten skifting tillatt eller skifting forbudt». Sokna skal
    # derfor ha skiftesignal2.
    #
    # Lampe 1 = øvre rekke (42), lampe 2 = nedre rekke (41) — den
    # rekkefølgen «nedre lamperekke ble fjernet» forutsetter. Er en
    # rekke bygget av flere pærer, parallellkobles de på samme kanal.
    "skiftesignal2": {
        "klasse": "skiftesignal",
        "lamper": 2,
        "normalbilde": "skifting-forbudt",
        "bilder": {
            "skifting-forbudt": ["av", "pa"],   # 41 nedre rekke
            "skifting-tillatt": ["pa", "av"],   # 42 øvre rekke
        },
        "signalnr": {"skifting-forbudt": "41", "skifting-tillatt": "42"},
    },
    "skiftesignal1": {
        "klasse": "skiftesignal",
        "lamper": 1,
        "normalbilde": "slukket",
        "bilder": {
            "slukket": ["av"],
            "skifting-tillatt": ["pa"],
        },
        "signalnr": {"skifting-tillatt": "42"},
    },
    # Dvergsignal (§ 8-23): tre hvite lys — 1 = øvre venstre,
    # 2 = nedre venstre, 3 = nedre høyre. Bildene dannes av lampepar:
    # vannrett (2+3) = kjøring forbudt, skrå (1+3) = varsom kjøring,
    # loddrett (1+2) = kjøring tillatt. MERK: frigitt-lokal-bildet er
    # PLASSHOLDER — verifiseres mot forbildet før bruk (korrigeres i
    # hal.json, som eier definisjonene etter første lagring).
    "dvergsignal3": {
        "klasse": "dvergsignal",
        "lamper": 3,
        "normalbilde": "kjoring-forbudt",
        "bilder": {
            "kjoring-forbudt": ["av", "pa", "pa"],
            "varsom-kjoring":  ["pa", "av", "pa"],
            "kjoring-tillatt": ["pa", "pa", "av"],
            "frigitt-lokal":   ["av", "blink", "pa"],
        },
    },
}
# Litra er unik PER OBJEKTKLASSE, som i forbildet: veksel 1 og
# sporfelt 1 kan sameksistere. Navnerommene følger UI-gruppene.
def litra_ugyldig(s):
    """MQTT-farlige tegn: / er nivåskille, + og # er jokertegn.
    En litra med disse ville gitt temaer som ikke kan adresseres."""
    for c in "/+#":
        if c in s:
            return c
    return None


def sig_klasse(t, signaltyper=None):
    """Signalklassen for en type: fra typedefinisjonen, ellers utledet
    av navnet (migrering av eldre konfigurasjoner)."""
    st = (signaltyper or SIGNALTYPER_DEFAULT).get(t)
    if isinstance(st, dict) and st.get("klasse"):
        return st["klasse"]
    for k in ("forsignal", "skiftesignal", "dvergsignal", "hovedsignal"):
        if t.startswith(k):
            return k
    return None


def litra_ns(t, signaltyper=None):
    k = sig_klasse(t, signaltyper)
    if k:
        return k   # hovedsignal/forsignal/skiftesignal/dvergsignal
    if t in ("sporveksel", "manuellveksel"):
        return "sporveksel"   # samme flate; forriglingen skiller dem
    if t == "sporfelt":
        return "sporfelt"
    if t in ("trykknapp", "bryter"):
        return "knapp"
    if t in ("samlelaas", "rigel", "sporsperre"):
        return t   # egne MQTT-rotnavn: nsi63/<type>/<id>/…
    return "annet"


# Forsignal kan ha "montert_med": "<hovedsignal-id>" på funksjonen:
# viser dét hovedsignalet stopp, settes forsignalet til "slukket".
# Hovedsignal har "rolle": "innkjor" | "utkjor" — bestemmer stopp-bildet:
# innkjør viser 20A (stopp-blink), utkjør viser 20B (stopp).

app = Flask(__name__)
lock = threading.Lock()
cache = {"nodes": None, "master_ack": None, "inputs": {},
         # Masterens egen tilstandsflate (retained) — se on_connect
         "jord": None, "signalstopp": None, "testmodus": None,
         "frigivning": None,
         "master_info": None, "master_status": None, "conflict": None,
         "forrigling_ack": None, "anlegg_ack": None, "meldinger": [],
         # Siste svar per togvei fra nsi63/togvei/<id>/info — så
         # Still/Riv i UI-et kan vise masterens begrunnelse direkte
         "togvei_info": {}}


# ---------- MQTT ----------

def on_connect(client, userdata, flags, reason_code, properties=None):
    # ETT bredt abonnement i stedet for en liste enkelttemaer: on_message
    # matcher uansett på eksakt tema, og hendelsesloggen (svart boks)
    # skal se ALT under roten. Overlappende abonnementer ville dessuten
    # kunne gi dobbeltlevering fra brokeren.
    client.subscribe(ROT + "#", 0)
    hevd_konfig()


def hevd_konfig() -> None:
    """Re-hev alle tre retained konfigene mot brokeren.

    Kalles fra on_connect — altså ved oppstart OG ved hver
    gjenoppkobling. Det siste er poenget: restartes mosquitto uten at
    HAL-UI restartes, er retained-lageret tomt, og ingenting ville
    ellers fylt det igjen før neste lagring.

    Republiseringen lå tidligere rett før `app.run()`. Den virket
    aldri: `connect_async` kobler i BAKGRUNNEN, så publiseringene gikk
    millisekunder senere — nesten alltid før CONNACK — og paho
    forkaster QoS 0 fra en klient som ikke er tilkoblet. Returkoden ble
    heller ikke sjekket, så tapet var stille.

    Filene her på Pi-en er fasiten; masteren speiler dem til eget
    flash og klarer seg uten oss, men retained skal likevel stemme.
    """
    try:
        hal = load_hal()
        if hal["functions"] or hal["version"]:
            publish_config(hal)
        fr = load_forrigling()
        if fr["togveier"] or fr["version"]:
            publish_forrigling(fr)
        mq.publish(ANLEGG_TOPIC,
                   json.dumps(_les_anlegg(), ensure_ascii=False),
                   retain=True)
    except Exception as e:            # aldri velt nettverkstråden
        cache["meldinger"].append(
            {"tekst": f"kunne ikke re-hevde konfig: {e}", "ts": time.time()})


# ---------- hendelseslogg («svart boks») ----------
# Alt som skjer på MQTT-flaten — togveier, signaler, sporfelt,
# betjening (også fra UI-ets egne publiseringer), nodenes inn-bytes,
# driftsmeldinger — skrives som én JSON-linje per hendelse med
# tidsstempel. Formålet er ettertidsanalyse («hvorfor gikk signalet i
# stopp 14:32?») og support av solgte anlegg. Loggen er også
# datagrunnlaget for et fremtidig digitalt stillerapparat (webpanel på
# Pi-en): /api/hendelser gir historikken, resten av flaten betjeningen.
# Periodisk støy (master/info, master/nodes, nodenes 5 s-STATE) hoppes
# over — loggen skal inneholde HENDELSER, ikke hjerteslag.
HENDELSE_FIL = Path(__file__).resolve().parent / "hendelser.jsonl"
# Loggingen er VALGFRI og AV som standard — den skrives til SD-kortet
# og samler alt som skjer, så den skal være et bevisst valg (feilsøk,
# treff, innkjøring), ikke en stille bakgrunnsprosess. På/av huskes
# som en flaggfil ved siden av loggen (uavhengig av anleggskonfigen,
# som master leser — dette angår bare Pi-en).
HENDELSE_AKTIV_FIL = HENDELSE_FIL.with_suffix(".aktiv")
_h_lock = threading.Lock()
_h_teller = 0
_H_MAKS_BYTE = 5_000_000        # ruller til .gammel over dette (1 gen.)
_H_HOPP = ("master/nodes", "master/info")
_H_RE_HOPP = re.compile(r"^espnow/[0-9a-f]{12}/state$")
_h_aktiv = HENDELSE_AKTIV_FIL.exists()


def hendelse_logg(tema: str, tekst: str, retained: bool) -> None:
    global _h_teller
    if not _h_aktiv:
        return
    if tema in _H_HOPP or _H_RE_HOPP.match(tema):
        return
    if tema.startswith("config/"):
        tekst = f"<konfig, {len(tekst)} tegn>"   # innholdet bor i git/backup
    elif len(tekst) > 300:
        tekst = tekst[:300] + "…"
    rad = {"ts": round(time.time(), 3), "tema": tema, "data": tekst}
    if retained:
        rad["r"] = 1   # retained = gammel tilstand re-levert ved oppkobling
    with _h_lock:
        try:
            with open(HENDELSE_FIL, "a", encoding="utf-8") as f:
                f.write(json.dumps(rad, ensure_ascii=False) + "\n")
            _h_teller += 1
            if (_h_teller % 500 == 0
                    and HENDELSE_FIL.stat().st_size > _H_MAKS_BYTE):
                HENDELSE_FIL.replace(
                    HENDELSE_FIL.with_suffix(".jsonl.gammel"))
        except OSError:
            pass   # full disk o.l. skal aldri velte nettverkstråden


def on_message(client, userdata, msg):
    text = msg.payload.decode("utf-8", "replace")
    tema_kort = (msg.topic[len(ROT):] if msg.topic.startswith(ROT)
                 else msg.topic)
    hendelse_logg(tema_kort, text, bool(msg.retain))
    if msg.topic == MASTER_STATUS_TOPIC:      # ren tekst: online/offline
        cache["master_status"] = text
        cache["master_status_ts"] = time.time()
        return
    if msg.topic == MELDING_TOPIC:            # ren tekst: driftsadvarsel
        cache["meldinger"].append({"tekst": text, "ts": time.time()})
        del cache["meldinger"][:-8]           # behold de 8 siste
        return
    if msg.topic == ROT + "master/lampeprove/ack":   # ren tekst
        cache["lampeprove_ack"] = {"svar": text, "ts": time.time()}
        return
    if msg.topic in (ROT + "master/jord", ROT + "master/signalstopp",
                     ROT + "master/testmodus"):          # ren tekst
        cache[msg.topic.rsplit("/", 1)[1]] = text
        cache["master_hort_ts"] = time.time()
        return
    # nsi63/togvei/<id>/info — masterens svar på betjening (ren tekst)
    if msg.topic.startswith(ROT + "togvei/") and msg.topic.endswith("/info"):
        tid = msg.topic[len(ROT + "togvei/"):-len("/info")]
        ti = cache["togvei_info"]
        ti[tid] = {"tekst": text, "ts": time.time()}
        if len(ti) > 32:                      # aldri voks fritt
            for k in list(ti)[:len(ti) - 32]:
                del ti[k]
        return
    try:
        payload = json.loads(text)
    except ValueError:
        return
    if msg.topic == NODES_TOPIC:
        cache["nodes"] = payload
        cache["master_hort_ts"] = time.time()
    elif msg.topic == MASTER_ACK_TOPIC:
        cache["master_ack"] = payload
    elif msg.topic == MASTER_INFO_TOPIC:
        cache["master_info"] = payload
        cache["master_hort_ts"] = time.time()
    elif msg.topic == CONFLICT_TOPIC:
        cache["conflict"] = {"data": payload, "ts": time.time()}
    elif msg.topic == FORRIGLING_ACK_TOPIC:
        cache["forrigling_ack"] = payload
    elif msg.topic == ANLEGG_ACK_TOPIC:
        cache["anlegg_ack"] = payload
    elif msg.topic == ROT + "master/frigivning":
        cache["frigivning"] = payload
    else:
        # nsi63/espnow/<mac>/in/<addr-hex> -> {"i2c":"0x20","value":n}
        parts = msg.topic.split("/")
        if len(parts) == 5 and parts[3] == "in":
            inn = cache["inputs"]
            inn[f"{parts[2]}/0x{parts[4]}"] = payload.get("value")
            # Taket speiler masterens inCache: flere kilder enn den kan
            # holde er uansett ikke i drift. Uten det vokser dicten for
            # hver node som noen gang har meldt en inngang — også de
            # som er glemt for lenge siden.
            if len(inn) > 64:
                for k in list(inn)[:len(inn) - 64]:
                    del inn[k]


# paho-mqtt 2.x krever eksplisitt callback-API-versjon; 1.x (eldre
# Raspberry Pi OS / Debian-pakker) kjenner ikke CallbackAPIVersion.
# Callbackene over er skrevet så de virker med begge (properties=None).
try:
    mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hal-ui")
except AttributeError:              # paho-mqtt 1.x
    mq = mqtt.Client(client_id="hal-ui")
mq.on_connect = on_connect
mq.on_message = on_message
# NB: selve tilkoblingen startes NEDERST i fila. on_connect kaller
# hevd_konfig(), som bruker load_hal()/load_forrigling()/_les_anlegg()
# — de er ikke definert ennå her, og en rask CONNACK ville gitt
# NameError på nettverkstråden midt under import.


def publish_config(data: dict):
    mq.publish(CONFIG_TOPIC, json.dumps(data, ensure_ascii=False), retain=True)


# ---------- hal.json ----------

def migrate_forrigling(data: dict, functions: list) -> dict:
    """Løft togveitabellen til gjeldende form.

    En håndstilt veksel sto tidligere i togveiens vekselliste. Den kan
    ikke kommanderes, og forriglingen kan derfor bare KREVE at den
    ligger riktig — noe kontrollåsen er garantien for. Oppføringen
    flyttes til togveiens «laaser»: låsen som omfatter vekselen må
    være sperret. Er vekselen ikke omfattet av noen lås, finnes ingen
    garanti, og oppføringen fjernes (valideringen sier fra).
    """
    manuelle = {f.get("id") for f in functions
                if f.get("type") == "manuellveksel"}
    if not manuelle:
        return data
    eier = {}          # objekt-litra -> låsegruppe som omfatter det
    for f in functions:
        if f.get("type") in ("samlelaas", "rigel"):
            for o in f.get("omfatter") or []:
                eier.setdefault(o, f.get("id"))
    for tv in data.get("togveier", []):
        beholdt, laaser = [], list(tv.get("laaser") or [])
        for v in tv.get("sporveksler") or []:
            lit = v.get("sporveksel")
            if lit not in manuelle:
                beholdt.append(v)
                continue
            lg = eier.get(lit)
            if lg and lg not in laaser:
                laaser.append(lg)
        tv["sporveksler"] = beholdt
        if laaser:
            tv["laaser"] = laaser
    return data


def migrate(data: dict) -> dict:
    """Løft eldre formater til gjeldende."""
    for f in data.get("functions", []):
        if f.get("type") in ("buzzer", "surre"):   # eldre navn (v5/v7)
            f["type"] = "klokke"
        # «sporveksel-lokal» delte prefiks med den sentralstilte, og
        # master dro den dermed med inn i togveier, skifteområder og
        # Lok-frigivning der den ikke hører hjemme. Nytt navn uten
        # prefiks tvinger eksplisitt håndtering.
        if f.get("type") == "sporveksel-lokal":
            f["type"] = "manuellveksel"
        # Notatfeltet er fjernet fra HAL-UI: teksten var dokumentasjon
        # master aldri leste, men den tok 39 % av konfigpayloaden mot
        # masterens 16 kB-grense.
        f.pop("notes", None)
        # Den gamle enkeltinngangen var nivåstyrt med LAV = avvik —
        # nøyaktig det «-avvik» alene betyr nå. Hvilket PAR den havner
        # i følger av hvor objektet betjenes fra: den sentralstilte
        # hadde stilleren på apparatet, mens manuellveksel og
        # sporsperre betjenes ute ved objektet.
        for b in f.get("bindinger") or []:
            if b.get("sted") != "stiller":
                continue
            if f.get("type") == "sporveksel":
                b["sted"] = "stiller-avvik"
            elif f.get("type") == "manuellveksel":
                b["sted"] = "lokal-avvik"
            elif f.get("type") == "sporsperre":
                b["sted"] = "lokal-avlagt"
        # Sporsperren har fått sine egne bindingsnavn: normalstillingen
        # ER pålagt. Master kjenner dem som aliaser, men konfigen skal
        # si det den er.
        if f.get("type") == "sporsperre":
            SPERRENAVN = {"ut-normal": "ut-paalagt",
                          "ut-avvik": "ut-avlagt",
                          "sensor-normal": "sensor-paalagt",
                          "lokal-normal": "lokal-paalagt",
                          "lokal-avvik": "lokal-avlagt"}
            for b in f.get("bindinger") or []:
                if b.get("sted") in SPERRENAVN:
                    b["sted"] = SPERRENAVN[b["sted"]]
        if f.get("type") == "klokke" and f.get("rolle") == "sporvekselklokke":
            f.pop("rolle")   # rolledelt klokke utgått: én klokke gjør alt
        if "bindinger" not in f:
            f["bindinger"] = []
            if f.get("node"):
                f["bindinger"].append({
                    "sted": "anlegg", "node": f.pop("node"),
                    "i2c": f.pop("i2c", "0x40"), "port": f.pop("port", 0),
                })
    st = data.get("signaltyper")
    if (not st or "signalnr" not in st.get("hovedsignal3", {})
            or "slukket" not in st.get("forsignal2", {}).get("bilder", {})
            or "normalbilde" not in st.get("hovedsignal3", {})
            or "folger" not in st.get("forsignal2", {})):
        # Mangler eller fra før gjeldende fasit: erstatt.
        # DYP KOPI: hal.json eier definisjonene etter innlasting og kan
        # redigeres. Uten kopi ville redigeringen truffet modulnivå-
        # dicten SIGNALTYPER_DEFAULT, som er delt av alle senere kall.
        data["signaltyper"] = copy.deepcopy(SIGNALTYPER_DEFAULT)
    else:
        for t in st.values():             # v2 hadde lamper som navneliste
            if isinstance(t.get("lamper"), list):
                t["lamper"] = len(t["lamper"])
        # Nyere typer skytes inn i eldre hal.json (filen eier
        # definisjonene, men skal ikke mangle typene UI-et tilbyr).
        # Generelt: ENHVER standardtype som mangler flettes inn — da
        # følger fremtidige typer med uten ny migreringskode
        for navn, definisjon in SIGNALTYPER_DEFAULT.items():
            if navn not in st:
                st[navn] = copy.deepcopy(definisjon)
        # Signal 41 er sløyfet: bildet «skifting-forbudt» døpes om til
        # «slukket» (mørkt signal = intet signal). Bildedefinisjonen
        # er den samme, så omdøpingen er ren navnereparasjon — men
        # normalbildet må følge med, ellers peker det i løse luften.
        sk = st.get("skiftesignal1", {})
        if isinstance(sk, dict) and "skifting-forbudt" in sk.get("bilder", {}):
            sk["bilder"]["slukket"] = sk["bilder"].pop("skifting-forbudt")
            if sk.get("normalbilde") == "skifting-forbudt":
                sk["normalbilde"] = "slukket"
        # Signalklasser (navnerom/MQTT-rot): eldre konfig mangler
        # klassefeltet — utled det av typenavnet én gang
        for navn, t in st.items():
            if isinstance(t, dict) and not t.get("klasse"):
                t["klasse"] = sig_klasse(navn) or "hovedsignal"
    return data


def load_hal() -> dict:
    if HAL_FILE.exists():
        with open(HAL_FILE, encoding="utf-8") as f:
            data = migrate(json.load(f))
    else:
        # Dyp kopi, som i migrate(): den returnerte dicten kan bli
        # redigert av kalleren, og modulnivå-defaulten deles av alle
        # senere kall i samme prosess.
        data = {"version": 0, "updated": None,
                "signaltyper": copy.deepcopy(SIGNALTYPER_DEFAULT),
                "functions": []}
    data.setdefault("noder", {})   # kallenavn -> {"mac": "..."}
    return data


def _skriv_atomisk(fil, data: dict) -> None:
    """Atomisk OG HOLDBAR skriving.

    `replace()` er atomisk — filen er enten den gamle eller den nye,
    aldri en halv. Men atomisk er ikke det samme som holdbart: uten
    fsync ligger innholdet i sidebufferen, og et strømbrudd rett etter
    lagring kan etterlate en fil som FINNES men er tom (0 byte). Da
    kaster load_hal() ved oppstart og tjenesten restart-looper — og
    masteren, som henter konfigen herfra, står uten HAL.

    Derfor: fsync på DATA før navnebyttet, og fsync på KATALOGEN etter,
    så selve navnebyttet også når disken.
    """
    tmp = fil.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(fil)
    dfd = os.open(str(fil.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def save_hal(functions=None, noder=None) -> dict:
    with lock:
        data = load_hal()
        if functions is not None:
            data["functions"] = functions
        if noder is not None:
            data["noder"] = noder
        # Versjon = lokalt tidsstempel — leselig overalt der den vises
        data["version"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _skriv_atomisk(HAL_FILE, data)
        # Publiseringen skjer INNENFOR låsen. Flask er flertrådet, og
        # med publiseringen utenfor kunne to samtidige lagringer flettes
        # slik: A skriver v1, B skriver v2, B publiserer, A publiserer —
        # og da står v2 på disk mens masteren kjører v1, permanent.
        publish_config(data)
    return data


def valid_mac(s: str) -> bool:
    return len(s) == 12 and all(c in "0123456789abcdef" for c in s)


# ---------- API ----------

@app.get("/api/hal")
def api_hal():
    return jsonify(load_hal())


@app.get("/api/nodes")
def api_nodes():
    return jsonify(cache["nodes"] or {})


@app.get("/api/ack")
def api_ack():
    return jsonify(cache["master_ack"] or {})


@app.get("/api/inputs")
def api_inputs():
    # Kopi før serialisering: MQTT-tråden skriver i denne dicten, og
    # jsonify-iterasjon over et dict som endrer størrelse underveis
    # gir RuntimeError. dict()-kopien er ett C-kall under GIL = atomisk.
    return jsonify(dict(cache["inputs"]))


@app.get("/api/master")
def api_master():
    c = cache["conflict"]
    fresh = c if c and time.time() - c["ts"] < 60 else None
    now = time.time()
    hort = cache.get("master_hort_ts")
    return jsonify({
        "mac": (cache["nodes"] or {}).get("master"),
        "status": cache["master_status"],
        # sekunder siden siste LIVSTEGN (info/roster, sendes hvert 10. s)
        # — retained «online» skal aldri tros på alene: den overlever
        # både broker-omstart (LWT-en dør med forbindelsen sin) og
        # denne prosessens egen cache
        "sist_hort_s": (round(time.time() - hort) if hort else None),
        "info": cache["master_info"],
        "conflict": fresh["data"] if fresh else None,
        # driftsadvarsler siste time (fw-avvik, full inngangscache, ...)
        "meldinger": [m for m in list(cache["meldinger"])
                      if now - m["ts"] < 3600],
        # Masterens EGEN tilstand — det er denne som gjelder, ikke det
        # som tilfeldigvis står i Pi-ens anlegg.json
        "jord": cache.get("jord"),
        "signalstopp": cache.get("signalstopp"),
        "testmodus": cache.get("testmodus"),
        "frigivning": cache.get("frigivning"),
    })


# ---------- anleggs-ID ----------
# Tre store bokstaver (jernbanens interne stasjonskoder, f.eks. SOK).
# Skiller to anlegg på samme radiokanal i samme lokale: master sender
# ID-en i puls/WELCOME, parede noder godtar kun sitt eget anlegg, og
# master ignorerer HELLO fra naboens noder. Filen eier verdien;
# publiseres retained ved lagring (samme mønster som hal.json).

def _les_anlegg() -> dict:
    try:
        with open(ANLEGG_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    # fjernstyrt: REN DOKUMENTASJON foreløpig — ingenting i forriglingen
    # leser den. Feltet er med nå så konfigurasjoner og sikkerhetskopier
    # bærer opplysningen videre, og fordi den styrer hvilke varianter av
    # signaler og funksjoner som er RIKTIGE for anlegget (høyt
    # skiftesignal med én eller to lamperekker, middelkontrollampe eller
    # sistevognskontroll). Standard True = som anleggene flest.
    try:
        hs = int(d.get("hjelpeutlosning_s", 90))
    except (TypeError, ValueError):
        hs = 90
    if hs != 0:
        hs = max(5, min(300, hs))
    return {"id": d.get("id", ""), "adopter": bool(d.get("adopter", True)),
            "testmodus": bool(d.get("testmodus", False)),
            "fjernstyrt": bool(d.get("fjernstyrt", True)),
            # Hjelpeutløsningens tidsrelé i sekunder. Forbildet har ca. 90 s
            # («Arbeid på signalanlegg 1» s. 44 og 111). 0 = av, altså
            # momentan utløsning på trinn 2.
            "hjelpeutlosning_s": hs,
            # Dekningsstilling: krysningsvekselen i motsatt ende legges vekk
            # fra togveiens spor ved sikring av innkjørtogvei, uten å låses.
            "dekningsstilling": bool(d.get("dekningsstilling", True))}


@app.get("/api/anlegg")
def api_anlegg():
    d = _les_anlegg()
    d["ack"] = cache["anlegg_ack"]
    return jsonify(d)


def _oppdater_ap_og_hostname(aid: str) -> dict:
    """Døp AP-et (SSID) og Pi-ens hostname etter anleggs-ID-en.

    SSID = NSI63 + ID (bare NSI63 uten ID); hostname = samme i små
    bokstaver (f.eks. http://nsi63abc.local). Alt feiler mykt så UI-et
    også utenfor en ekte Pi. hostapd restartes KUN når SSID-en faktisk
    endres — det kaster alle wifi-klienter (også nettleseren din!),
    derfor gjøres det til slutt, etter at konfigen er publisert.
    """
    ssid = "NSI63" + aid
    host = ssid.lower()
    ut = {"ssid": ssid, "hostname": host, "ap_omdopt": False}
    conf = Path("/etc/hostapd/hostapd.conf")
    try:
        txt = conf.read_text()
        ny = re.sub(r"(?m)^ssid=.*$", "ssid=" + ssid, txt)
        if ny != txt:
            conf.write_text(ny)
            subprocess.run(["systemctl", "restart", "hostapd"],
                           timeout=15, check=False)
            ut["ap_omdopt"] = True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        gml = subprocess.run(["hostnamectl", "--static"], timeout=5,
                             capture_output=True, text=True).stdout.strip()
        if gml and gml != host:
            subprocess.run(["hostnamectl", "set-hostname", host],
                           timeout=10, check=False)
            hosts = Path("/etc/hosts")
            txt = hosts.read_text()
            ny = re.sub(r"(?m)^(127\.0\.1\.1\s+).*$", r"\g<1>" + host, txt)
            if ny != txt:
                hosts.write_text(ny)
    except (OSError, subprocess.SubprocessError):
        pass
    return ut


@app.post("/api/anlegg")
def api_anlegg_save():
    data = request.get_json(force=True) or {}
    aid = str(data.get("id", "")).strip().upper()
    adopter = bool(data.get("adopter", True))
    # Testmodus er en SIKKERHETSOMGÅELSE: MQTT-kommandoer omgår
    # forriglingen. Den lagres som konfig (synlig i sikkerhetskopien),
    # men master maser hvert minutt så den ikke blir stående på.
    testmodus = bool(data.get("testmodus", False))
    fjernstyrt = bool(data.get("fjernstyrt", True))
    dekning = bool(data.get("dekningsstilling", True))
    try:
        hjelp = int(data.get("hjelpeutlosning_s", 90))
    except (TypeError, ValueError):
        hjelp = 90
    if hjelp != 0 and not (5 <= hjelp <= 300):
        return jsonify({"error": "hjelpeutløsning må være 0 (av) eller "
                        "mellom 5 og 300 sekunder — forbildet har 90"}), 400
    if aid and not re.fullmatch(r"[A-Z]{3}", aid):
        return jsonify({"error": "anleggs-ID må være nøyaktig tre store "
                        "bokstaver A-Z — eller tom for å skru av filteret"}), 400
    d = {"id": aid, "adopter": adopter, "testmodus": testmodus,
         "fjernstyrt": fjernstyrt, "hjelpeutlosning_s": hjelp,
         "dekningsstilling": dekning}
    with lock:                              # samme mønster som hal/forrigling:
        _skriv_atomisk(ANLEGG_FILE, d)      # atomisk, holdbart, og
        # Rekkefølgen er viktig: publiser konfigen FØR hostapd evt.
        # restartes — brokeren er lokal og upåvirket av AP-omstarten, så
        # masteren finner den retained når den kobler seg på det nye nettet
        mq.publish(ANLEGG_TOPIC, json.dumps(d, ensure_ascii=False),
                   retain=True)             # publisert under samme lås
    ut = _oppdater_ap_og_hostname(aid)
    return jsonify({"ok": True, **d, **ut})


# ---------- OTA: trådløs firmwareoppdatering ----------
# Ferdigkompilert binærfil (pio run -> .pio/build/<env>/firmware.bin)
# lastes opp hit og serveres på FAST adresse — enhetene henter selv:
#   master:  MQTT nsi63/master/ota  -> henter /ota/nsi63-atoms3.bin
#   node:    CMD "ota" (via master) -> kobler seg midlertidig på AP-et
#            som wifi-klient og henter samme fil
# MD5-summen serveres ved siden av og verifiseres av enheten før
# bootslot byttes — feilet nedlasting = gammel firmware kjører videre.

OTA_DIR = Path(__file__).resolve().parent / "ota"
# FELLES firmware: master og noder kjører samme binær — rollen velges
# med knappegest på enheten og huskes i NVS. ÉN navngitt fil: enheten
# ber om navnet den har kompilert inn, og bare navn i denne lista
# serveres. Byggevarianter som ikke skal kunne hentes trådløst, får
# navn som med vilje står utenfor — de flashes over USB.
OTA_FILER = ["nsi63-atoms3.bin"]


@app.get("/ota/<navn>")
def ota_fil(navn):
    base, md5 = (navn[:-4], True) if navn.endswith(".md5") else (navn, False)
    if base not in OTA_FILER:
        return jsonify({"error": "ukjent fil"}), 404
    sti = OTA_DIR / (base + (".md5" if md5 else ""))
    if not sti.exists():
        return jsonify({"error": "ikke lastet opp"}), 404
    return send_file(sti, max_age=0,
                     mimetype="text/plain" if md5
                     else "application/octet-stream")


@app.get("/api/ota")
def api_ota():
    ut = {}
    for fn in OTA_FILER:
        sti = OTA_DIR / fn
        md5 = OTA_DIR / (fn + ".md5")
        sc = OTA_DIR / (fn + ".stempel")
        ut[fn] = ({"bytes": sti.stat().st_size,
                   "md5": md5.read_text().strip() if md5.exists() else "",
                   "stempel": sc.read_text().strip() if sc.exists() else "",
                   "tid": sti.stat().st_mtime}
                  if sti.exists() else None)
    return jsonify(ut)


def _ota_valider(data: bytes, navn: str):
    """Felles firmware-validering. Returnerer feiltekst eller None."""
    if not data or data[0] != 0xE9:
        return (f"{navn}: ikke et ESP32-firmwarebilde "
                "(mangler magisk byte 0xE9)")
    if len(data) < 200_000 or len(data) > 4_000_000:
        return f"{navn}: urimelig størrelse ({len(data)} byte)"
    return None


@app.post("/api/ota/firmware")
def api_ota_firmware():
    """Firmwarebinær fra bygg-ota.sh på utviklingsmaskinen — ÉN rå
    ESP32-fil, ingen pakking. (Zip-veien var fra den gang master og
    noder hadde hver sin binær og måtte ankomme atomisk; med felles
    firmware er det ett bilde, og pakken ga ikke lenger noe.)

    Filnavnet bærer byggestempelet
    (nsi63-atoms3-202608221037.bin). Enhetene henter på FAST
    navn — den kompilerte OTA_FIL-en — så vi normaliserer bort
    stempelet her og husker det ved siden av for visning. MD5 regnes
    av Pi-en fra de mottatte bytene og serveres sammen med binæren;
    enheten verifiserer mot den før bootslot byttes."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "ingen fil mottatt"}), 400
    # Størrelsen sjekkes FØR read(): en absurd opplasting skal ikke
    # kunne spise minnet på Pi-en før valideringen rekker å avvise
    # den. (Erstatter zip-bombe-vernet på deklarert utpakket
    # størrelse, som forsvant med pakken.)
    if request.content_length and request.content_length > 8 * 1024 * 1024:
        return jsonify({"error": f"opplastingen er "
                        f"{request.content_length} byte — urimelig "
                        f"stor firmware, avvist"}), 400
    base = (f.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    # Mønsteret utledes av OTA_FILER, så navnene aldri kan komme i
    # utakt. Benkevarianten står ikke der og avvises dermed her også:
    # den skal USB-flashes, aldri distribueres.
    stamme = "|".join(re.escape(f[:-4]) for f in OTA_FILER)
    m = re.fullmatch(rf"({stamme})(?:-(\d{{12}}))?\.bin", base)
    if not m:
        return jsonify({"error": f"ukjent filnavn «{base}» — venter "
                        + " eller ".join(OTA_FILER) +
                        " (byggestempel i navnet er valgfritt)"}), 400
    data = f.read()
    feil = _ota_valider(data, base)
    if feil:
        return jsonify({"error": feil}), 400
    kanon, stempel = m.group(1) + ".bin", m.group(2) or ""
    OTA_DIR.mkdir(exist_ok=True)
    (OTA_DIR / kanon).write_bytes(data)
    (OTA_DIR / (kanon + ".md5")).write_text(hashlib.md5(data).hexdigest())
    sc = OTA_DIR / (kanon + ".stempel")
    if stempel:
        sc.write_text(stempel)
    elif sc.exists():
        sc.unlink()   # ustemplet bygg skal ikke arve forrige stempel
    return jsonify({"ok": True, "fil": kanon, "stempel": stempel})


@app.post("/api/ota/start")
def api_ota_start():
    body = request.get_json(force=True) or {}
    maal = (body.get("maal") or "").strip().lower()
    har_fw = any((OTA_DIR / f).exists() for f in OTA_FILER)
    if maal == "master":
        if not har_fw:
            return jsonify({"error": "last opp firmware først"}), 400
        mq.publish(ROT + "master/ota", "start")
        return jsonify({"ok": True, "maal": "master"})
    if valid_mac(maal):
        if not har_fw:
            return jsonify({"error": "last opp firmware først"}), 400
        mq.publish(f"{ROT}espnow/{maal}/cmd", "ota")
        return jsonify({"ok": True, "maal": maal})
    return jsonify({"error": "mål må være 'master' eller en node-MAC"}), 400


# ---------- Pi-status: temperatur, nett, klienter, tjenester ----------
# Leses med systemverktøy (tjenesten kjører som root). Alt feiler mykt,
# så endepunktet virker (med hull) også utenfor en ekte Pi.
_pi_cache = {"ts": 0.0, "data": None}


def _run(cmd, timeout=3):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ""


def _pi_temp():
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text()
        return round(int(raw.strip()) / 1000, 1)
    except Exception:
        return None


def _pi_throttled():
    """vcgencmd get_throttled: underspenning/struping, nå og siden boot."""
    m = re.search(r"0x([0-9a-fA-F]+)", _run(["vcgencmd", "get_throttled"]))
    if not m:
        return None
    v = int(m.group(1), 16)
    navn = {0: "underspenning", 1: "frekvens begrenset",
            2: "strupet", 3: "temp-grense"}
    return {"raw": f"0x{v:x}",
            "naa": [n for b, n in navn.items() if v & (1 << b)],
            "historikk": [n for b, n in navn.items() if v & (1 << (b + 16))]}


def _pi_ips():
    res = []
    try:
        for i in json.loads(_run(["ip", "-j", "addr", "show"]) or "[]"):
            if i.get("ifname") == "lo":
                continue
            addrs = [a["local"] for a in i.get("addr_info", [])
                     if a.get("family") == "inet"]
            if addrs:
                res.append({"ifname": i["ifname"], "addrs": addrs,
                            "oper": i.get("operstate", "")})
    except Exception:
        pass
    return res


def _pi_leases():
    """dnsmasq-leases: mac -> ip/navn."""
    res = {}
    try:
        for ln in Path("/var/lib/misc/dnsmasq.leases").read_text().splitlines():
            p = ln.split()
            if len(p) >= 4:
                res[p[1].lower()] = {"ip": p[2],
                                     "navn": p[3] if p[3] != "*" else ""}
    except Exception:
        pass
    return res


def _pi_klienter():
    """Tilkoblede AP-klienter fra iw, beriket med dnsmasq-leases."""
    leases = _pi_leases()
    kl, cur = [], None
    for ln in _run(["iw", "dev", "wlan0", "station", "dump"]).splitlines():
        ln = ln.strip()
        if ln.startswith("Station "):
            cur = {"mac": ln.split()[1].lower(), "signal": None, "tid_s": None}
            kl.append(cur)
        elif cur and (ln.startswith("signal avg:") or
                      (ln.startswith("signal:") and cur["signal"] is None)):
            m = re.search(r"(-?\d+)", ln)
            if m:
                cur["signal"] = int(m.group(1))
        elif cur and ln.startswith("connected time:"):
            m = re.search(r"(\d+)", ln)
            if m:
                cur["tid_s"] = int(m.group(1))
    for c in kl:
        li = leases.get(c["mac"], {})
        c["ip"] = li.get("ip", "")
        c["navn"] = li.get("navn", "")
    return kl


def _pi_tjenester():
    navn = ["mosquitto", "hostapd", "dnsmasq", "nsi63-sta-watchdog"]
    st = _run(["systemctl", "is-active"] + navn).split()
    return {n: (st[i] if i < len(st) else "ukjent")
            for i, n in enumerate(navn)}


# Klokkestilling fra nettleseren: Pi-en mangler RTC, men enheten som
# åpner GUI-et har alltid riktig tid. UI-et melder inn sin klokke i det
# stille; vi justerer BARE når Pi-en ikke er NTP-synket, avviket er
# stort, og det er lenge siden sist (to klienter skal ikke dra i hver
# sin retning). fake-hwclock lagres straks, så tiden overlever reboot.
_klokke_stilt = {"ts": None, "diff_s": None, "fra": None}
_KLOKKE_TERSKEL_S = 120
_KLOKKE_COOLDOWN_S = 600


def _ntp_synk():
    return _run(["timedatectl", "show", "-p", "NTPSynchronized",
                 "--value"]).strip() == "yes"


@app.post("/api/klokke")
def api_klokke():
    body = request.get_json(force=True)
    try:
        nett_s = float(body.get("epoch_ms", 0)) / 1000.0
    except (TypeError, ValueError):
        return jsonify({"error": "ugyldig epoch_ms"}), 400
    if nett_s < 1e9:                      # åpenbart tull (før 2001)
        return jsonify({"error": "ugyldig epoch_ms"}), 400
    diff = nett_s - time.time()
    if _ntp_synk():                       # ekte NTP vinner alltid
        return jsonify({"status": "ntp", "diff_s": round(diff, 1)})
    if abs(diff) < _KLOKKE_TERSKEL_S:
        return jsonify({"status": "ok", "diff_s": round(diff, 1)})
    if (_klokke_stilt["ts"]
            and 0 <= time.time() - _klokke_stilt["ts"] < _KLOKKE_COOLDOWN_S):
        return jsonify({"status": "cooldown", "diff_s": round(diff, 1)})
    _run(["date", "-u", "-s", "@%d" % int(nett_s)])
    _run(["fake-hwclock", "save"])        # overlev neste boot
    _klokke_stilt.update(ts=time.time(), diff_s=round(diff, 1),
                         fra=request.remote_addr)
    _pi_cache["data"] = None              # vis ny klokke straks
    print(f"[klokke] stilt {round(diff)} s fra {request.remote_addr}",
          flush=True)
    return jsonify({"status": "stilt", "diff_s": round(diff, 1)})


@app.get("/api/pi")
def api_pi():
    now = time.time()
    if _pi_cache["data"] and now - _pi_cache["ts"] < 3:
        return jsonify(_pi_cache["data"])
    d = {"temp": _pi_temp(), "throttled": _pi_throttled(),
         "ips": _pi_ips(), "klienter": _pi_klienter(),
         "tjenester": _pi_tjenester(), "ntp": _ntp_synk(),
         "klokke": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    d["klokke_stilt"] = None
    if _klokke_stilt["ts"]:
        d["klokke_stilt"] = {
            "naar": datetime.fromtimestamp(_klokke_stilt["ts"])
            .strftime("%H:%M"),
            "diff_s": _klokke_stilt["diff_s"],
            "fra": _klokke_stilt["fra"]}
    try:
        d["oppetid_s"] = int(float(Path("/proc/uptime")
                                   .read_text().split()[0]))
    except Exception:
        d["oppetid_s"] = None
    try:
        d["last"] = list(os.getloadavg())
    except Exception:
        d["last"] = None
    try:
        mi = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            p = ln.split()
            mi[p[0].rstrip(":")] = int(p[1])
        d["mem"] = {"total_mb": mi["MemTotal"] // 1024,
                    "ledig_mb": mi["MemAvailable"] // 1024}
    except Exception:
        d["mem"] = None
    try:
        du = shutil.disk_usage("/")
        d["disk"] = {"total_gb": round(du.total / 2**30, 1),
                     "ledig_gb": round(du.free / 2**30, 1)}
    except Exception:
        d["disk"] = None
    try:
        d["modell"] = (Path("/proc/device-tree/model")
                       .read_bytes().decode().rstrip("\x00"))
    except Exception:
        d["modell"] = None
    _pi_cache.update(ts=now, data=d)
    return jsonify(d)


def _gen_togvei_id(tv, fns, st_map):
    """Togvei-ID av rute-endene (samme regel som UI-ets frGenId):
    fra+til — A01 (innkjør), 01A (utkjør), 0102 (indre)."""
    if tv.get("fra") and tv.get("til"):
        return tv["fra"] + tv["til"]
    rolle = next((f.get("rolle", "") for f in fns
                  if sig_klasse(f.get("type", ""), st_map) == "hovedsignal"
                  and f.get("id") == tv.get("start")), "")
    linjefelter = {f["id"] for f in fns
                   if f.get("type") == "sporfelt"
                   and f.get("rolle") == "linjefelt"}
    linje = next((x for x in tv.get("frie", []) if x in linjefelter), "")
    spor = tv.get("spor", "")
    if not (linje and spor and rolle in ("innkjor", "utkjor")):
        return ""
    return linje + spor if rolle == "innkjor" else spor + linje


def _er_inngangsbinding(ftype, sted):
    """Speiler masterens erInngangsBinding: sensor-/stiller-/
    kvitteringsbindinger er innganger, og "anlegg" er inngang for
    inngangstypene (trykknapp/bryter/inngang leses via anlegg)."""
    # NB «lokal-» med bindestrek: «lokalstillerlampe» er en LAMPE og
    # skal ikke havne her.
    return (sted.startswith(("sensor", "stiller", "lokal-"))
            or sted == "kvittering"
            or (sted == "anlegg" and ftype in ("trykknapp", "bryter",
                                               "inngang")))


def _heltall(v, feil, hva):
    """Trygg int-parsing i valideringen: søppel skal gi en KLAR
    400-melding, aldri en ubehandlet ValueError (= stum 500)."""
    try:
        return int(v or 0)
    except (ValueError, TypeError):
        feil.append(f"{hva}: '{v}' er ikke et gyldig tall")
        return 0


def _for_stor(data: dict, hva: str):
    """Sjekk at konfigen får plass i masterens MQTT-buffer.

    PubSubClient forkaster en for stor melding i STILLHET — callbacket
    kjører aldri. Uten denne sjekken svarer UI-et «lagret og publisert»
    mens master fortsetter på gammel konfig, og det eneste sporet er at
    versjonen i kvitteringen ikke følger med.
    """
    n = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    if n <= MAX_PAYLOAD:
        return None
    return (f"{hva} er {n} byte — masteren tar maks {MAX_PAYLOAD}. "
            f"Reduser antall objekter eller bindinger.")


def _kapasitet_feil(functions, signaltyper=None):
    """Grenser master ellers ville avkortet i stillhet."""
    feil = []
    if len(functions) > MAX_FUNKSJONER:
        feil.append(f"{len(functions)} objekter — masteren tar maks "
                    f"{MAX_FUNKSJONER} (resten forsvinner uten varsel)")
    if signaltyper and len(signaltyper) > MAX_SIGNALTYPER:
        feil.append(f"{len(signaltyper)} signaltyper — masteren tar maks "
                    f"{MAX_SIGNALTYPER}")
    for f in functions:
        fid = f.get("id") or "(uten litra)"
        skv = f.get("skift_sporveksler") or []
        if len(skv) > MAX_SKIFT_VEKSLER:
            feil.append(f"{fid}: {len(skv)} veksler i skifteområdet — "
                        f"maks {MAX_SKIFT_VEKSLER}")
        # Samlelåsens objektliste deler masterens skift-tabell
        omf = f.get("omfatter") or []
        if len(omf) > MAX_SKIFT_VEKSLER:
            feil.append(f"{fid}: {len(omf)} objekter i samlelåsen — "
                        f"maks {MAX_SKIFT_VEKSLER}")
    return feil


def _kapasitet_feil_togvei(togveier):
    feil = []
    if len(togveier) > MAX_TOGVEIER:
        feil.append(f"{len(togveier)} togveier — masteren tar maks "
                    f"{MAX_TOGVEIER} (resten forsvinner uten varsel)")
    for tv in togveier:
        tid = (tv.get("id") or "(uten id)")
        nv = len(tv.get("sporveksler") or [])
        nf = len(tv.get("frie") or [])
        if nv > MAX_TV_VEKSLER:
            feil.append(f"togvei {tid}: {nv} veksler — maks "
                        f"{MAX_TV_VEKSLER}")
        if nf > MAX_TV_FELT:
            feil.append(f"togvei {tid}: {nf} frie felt — maks "
                        f"{MAX_TV_FELT}")
    return feil


def _topologi_feil(functions):
    """Venstre/høyre er panelgeometri — stillerapparatet viser spor-
    planen sett fra stasjonsbygningen — og LINJEFELTETS side er den
    eneste håndsatte v/h i sportopologien. Alt annet (vekselens ende,
    skiftesignalets og dvergsignalets område) utledes derfra, så et
    linjefelt uten side river grunnen vekk under hele avledningen.
    Meldefelt arver siden fra linjefeltet sitt og skal ikke ha egen."""
    feil = []
    linjefelt = {}
    for f in functions:
        if f.get("type") != "sporfelt" or f.get("rolle") != "linjefelt":
            continue
        litra = f.get("id") or "(uten litra)"
        side = (f.get("side") or "").strip()
        linjefelt[litra] = side
        if side not in ("v", "h"):
            feil.append(f"linjefeltet {litra} mangler ende "
                        f"(venstre/høyre) — vekselens stasjonsende, "
                        f"skiftesignalets område og dvergsignalets "
                        f"bilde utledes av den")
    for f in functions:
        if f.get("type") != "sporfelt" or f.get("rolle") != "varselfelt":
            continue
        ref = (f.get("linjefelt") or "").strip()
        if ref and ref not in linjefelt:
            feil.append(f"varselfeltet {f.get('id')} viser til ukjent "
                        f"linjefelt {ref}")
    # MERK — bevisst IKKE validert her: et linjefelt uten linjeblokk og
    # uten kvitteringsknapp på varselfeltet sitt. Innkjørtogveien blir da
    # stående og vente, og må løses ut med hjelpeutløsning på
    # togveistillerne (eller nsi63/togvei/<id>/set = kvitter) hver gang.
    # Tungvint, men verken farlig eller stille: togveislampen blinker og
    # master melder «klar for sistevognskontroll». Denne funksjonen
    # BLOKKERER lagring, og et anlegg under bygging skal kunne sette
    # flagget før knappen er koblet.
    # Skiftesignalets område må peke på veksler som finnes
    veksler = {f.get("id") for f in functions
               if f.get("type") in ("sporveksel", "manuellveksel")}
    sentralstilte = {f.get("id") for f in functions
                     if f.get("type") == "sporveksel"}
    sperrer_ids = {f.get("id") for f in functions
                   if f.get("type") == "sporsperre"}
    for f in functions:
        for v in f.get("skift_sporveksler") or []:
            if v not in veksler:
                feil.append(f"skiftesignal {f.get('id')} viser til "
                            f"ukjent veksel {v}")
            elif v not in sentralstilte:
                # Signalet FØLGER vekslene sine: 41 så lenge en av dem
                # er i bevegelse eller uten kontroll, 42 når stillingen
                # er bekreftet. En lokalstilt veksel melder aldri
                # kontroll og blir stående V_UKJENT — tas den med,
                # låses signalet i 41 for alltid. Stille i drift,
                # derfor avvist her.
                feil.append(f"skiftesignal {f.get('id')}: {v} er en "
                            f"manuellveksel — et høyt skiftesignal følger "
                            f"bare sentralstilte veksler, og ville blitt "
                            f"stående i «skifting forbudt»")
        # Låsegruppenes virkeområde (samlelås/rigel): et omfatter-
        # litra UTEN objekt i anlegget er LOV — det er en helt manuell
        # veksel/sperre, eller en som drives av kundens eget utstyr
        # utenfor systemet. Anlegget ser da bare låsen, som forbildet
        # (kontrollåskjeden er mekanisk og usynlig). Tegnene må
        # likevel være trygge: litraen vises i panelet og UI-et.
        for v in f.get("omfatter") or []:
            if v in veksler or v in sperrer_ids:
                continue
            tegn = litra_ugyldig(v)
            if tegn:
                feil.append(f"{f.get('type')} {f.get('id')}: objektet "
                            f"«{v}» utenfor anlegget har ulovlig tegn "
                            f"'{tegn}'")
    # Sporplan-topologien (portmodellen): referansene må finnes —
    # sporfelt-litra, eller «veksel N» for kjeder. Kun tegnefelt,
    # men en død referanse gir hull i planen.
    alle_felt = {f.get("id") for f in functions
                 if f.get("type") == "sporfelt"}
    def _topo_ref_ok(v):
        if not v:
            return True
        if v.startswith("veksel "):
            return v[7:] in veksler
        return v in alle_felt
    for f in functions:
        for felt in ("pluss_til", "minus_til", "spiss_til", "ligger_i"):
            v = f.get(felt)
            if v and not _topo_ref_ok(v):
                feil.append(f"{f.get('id')}: {felt} viser til ukjent "
                            f"«{v}»")
        if f.get("spiss") not in (None, "", "v", "h"):
            feil.append(f"{f.get('id')}: spiss må være v eller h")
        if f.get("avvik_ben") not in (None, "", "spiss", "pluss"):
            feil.append(f"{f.get('id')}: avvik_ben må være tom, "
                        f"«spiss» eller «pluss»")
    # Dvergsignalets ende arves fra hovedsignalet det er montert på,
    # via dets «foran»-linjefelt. Mangler den lenken, blir bildet
    # stående på 43 for alltid — en STILLE død som er nesten umulig
    # å feilsøke i felten. Fang den her i stedet.
    hoved = {f.get("id"): f for f in functions
             if str(f.get("type", "")).startswith("hovedsignal")}
    for f in functions:
        if sig_klasse(f.get("type", "")) != "dvergsignal":
            continue
        vert = (f.get("montert_med") or "").strip()
        if not vert:
            feil.append(f"dvergsignal {f.get('id')} mangler "
                        f"hovedsignalet det står på")
        elif vert not in hoved:
            feil.append(f"dvergsignal {f.get('id')} viser til ukjent "
                        f"hovedsignal {vert}")
        elif not (hoved[vert].get("linjefelt") or "").strip():
            feil.append(f"hovedsignal {vert} mangler «foran»-linjefelt "
                        f"— dvergsignal {f.get('id')} kan da ikke "
                        f"utlede stasjonsenden og ville stått mørkt")
    return feil


def _port_konflikter(functions, st_map, noder):
    """Fysiske portkollisjoner. Inngang+inngang deles lovlig (én knapp
    kan betjene flere funksjoner); inngang+utgang og utgang+utgang på
    samme port er alltid feil — på GPIO ville inn/ut-blanding fått
    porten til å vippe retning ved hver re-render. Signaler opptar
    'lamper' påfølgende porter fra bindingsporten."""
    def kapasitet(i2c):
        i2c = str(i2c or "")
        if i2c == "gpio":
            return 6
        if i2c.startswith("0x4"):
            return 16
        if i2c.startswith("0x2"):
            return 8
        return None   # ukjent adresse — range-sjekk hopper over

    bruk = {}   # (mac, i2c, port) -> [(litra, sted, er_inngang)]
    ordrer = {}   # mac -> antall ordrepunkter (utganger + GPIO-inn-
                  # aktiveringer) — én MSG_UT-ramme rommer maks 40, og
                  # taket garanterer at hver node får HELE bildet sitt
                  # i én atomisk ramme (fw v5)
    feil = []
    for f in functions:
        t = st_map.get(f.get("type"))
        for b in f.get("bindinger", []):
            node = (b.get("node") or "").strip()
            mac = noder.get(node, {}).get("mac", node).lower()
            sted = b.get("sted") or ""
            n = int(t.get("lamper", 1)) if (
                t and sted in ("anlegg", "panel")) else 1
            inn = _er_inngangsbinding(f.get("type", ""), sted)
            if not inn:
                ordrer[mac] = ordrer.get(mac, 0) + n
            elif b.get("i2c") == "gpio":
                ordrer[mac] = ordrer.get(mac, 0) + 1   # aktiveringsordre
            kap = kapasitet(b.get("i2c"))
            port0 = _heltall(b.get("port"), feil,
                             f"{f.get('id')} ({sted}) port")
            if port0 < 0:
                feil.append(f"{f.get('id')} ({sted}): negativ port "
                            f"{port0}")
            elif kap is not None and port0 + n > kap:
                feil.append(
                    f"{f.get('id')} ({sted}): port {port0}"
                    + (f"–{port0 + n - 1} ({n} lamper)" if n > 1 else "")
                    + f" går utenfor {b.get('i2c')} "
                    f"(porter 0–{kap - 1})")
            for k in range(n):
                key = (mac, b.get("i2c"), port0 + k)
                bruk.setdefault(key, []).append(
                    (f.get("id"), sted,
                     _er_inngangsbinding(f.get("type", ""), sted)))
    for (mac, i2c, port), brukere in sorted(bruk.items()):
        if len(brukere) < 2:
            continue
        inn = [x for x in brukere if x[2]]
        ut = [x for x in brukere if not x[2]]
        hvem = " og ".join(f"{l} ({s})" for l, s, _ in brukere)
        sted_txt = f"{i2c} port {port}"
        if inn and ut:
            feil.append(f"{hvem} deler {sted_txt} som både inngang "
                        f"og utgang")
        elif len(ut) >= 2:
            feil.append(f"{hvem} deler utgangen {sted_txt}")
    navn = {v.get("mac", "").lower(): k for k, v in noder.items()}
    for mac, antall in sorted(ordrer.items()):
        if antall > 40:
            feil.append(f"{navn.get(mac, mac)} har {antall} ordrepunkter "
                        f"(utganger + GPIO-innganger) — maks 40 per node, "
                        f"fordel på flere noder")
    return feil


@app.post("/api/hal")
def api_save():
    body = request.get_json(force=True)
    functions = body.get("functions", [])
    lagret = load_hal()
    noder = lagret.get("noder", {})
    st_map = lagret.get("signaltyper", {})
    seen = set()
    for f in functions:
        fid = (f.get("id") or "").strip()
        if not fid:
            return jsonify({"error": "Alle rader må ha litra"}), 400
        tegn = litra_ugyldig(fid)
        if tegn:
            return jsonify({"error": f"Litra «{fid}»: tegnet '{tegn}' er "
                            f"ulovlig (brukes i MQTT-temaer — prøv f.eks. "
                            f"bindestrek i stedet)"}), 400
        ns = litra_ns(f.get("type"), st_map)
        if (ns, fid) in seen:
            return jsonify({"error": f"Duplikat litra i samme gruppe: "
                                     f"{fid}"}), 400
        seen.add((ns, fid))
        # Bindinger er valgfrie: en litra kan finnes rent logisk
        # (simulering/planlegging) til maskinvaren kobles
        if len(f.get("bindinger", [])) > 16:
            return jsonify({"error": f"{fid}: maks 16 bindinger per "
                                     f"funksjon (masterens grense)"}), 400
        for b in f.get("bindinger", []):
            node = (b.get("node") or "").strip()
            if node not in noder and not valid_mac(node.lower()):
                return jsonify({"error": f"{fid} ({b.get('sted')}): ukjent "
                                         f"node '{node}' (kallenavn/MAC)"}), 400
            b["node"] = node if node in noder else node.lower()
    konflikter = _port_konflikter(functions, st_map, noder)
    if konflikter:
        return jsonify({"error": "Portkonflikt: "
                        + " · ".join(konflikter)}), 400
    topologi = _topologi_feil(functions)
    if topologi:
        return jsonify({"error": " · ".join(topologi)}), 400
    kap = _kapasitet_feil(functions, lagret.get("signaltyper"))
    if kap:
        return jsonify({"error": "Kapasitet: " + " · ".join(kap)}), 400
    # Størrelsen måles på DET SOM FAKTISK PUBLISERES — samme dict som
    # save_hal bygger, med signaltyper og kallenavn.
    prove = dict(lagret); prove["functions"] = functions
    stor = _for_stor(prove, "Objektkonfigurasjonen")
    if stor:
        return jsonify({"error": stor}), 400
    # LITRA-OMDØPING: UI-et sender gammel_id per rad når litraen er
    # endret. Alle referanser følger med — ellers ble koblingene
    # stille foreldreløse (samme prinsipp som kallenavn-omdøping).
    renames = {}   # (klasse/navnerom, gammel) -> ny
    for f in functions:
        gammel = (f.pop("gammel_id", "") or "").strip()
        ny = f["id"].strip()
        if gammel and gammel != ny:
            renames[(litra_ns(f.get("type"), st_map), gammel)] = ny

    def omd(ns, verdi):
        return renames.get((ns, (verdi or "").strip()), verdi)

    n_refs = 0
    if renames:
        for f in functions:   # interne referanser i objekttabellen
            for felt, ns in (("montert_med", "hovedsignal"),
                             ("varsler_om", "hovedsignal"),
                             ("linjefelt", "sporfelt")):
                if f.get(felt) and omd(ns, f[felt]) != f[felt]:
                    f[felt] = omd(ns, f[felt])
                    n_refs += 1
    data = save_hal(functions=functions)

    # Togveitabellen refererer litraer i tre navnerom — skriv om og
    # regenerer togvei-ID-ene (de er avledet av linjefelt+spor)
    if renames:
        forr = load_forrigling()
        endret = False
        for tv in forr.get("togveier", []):
            for felt, ns in (("start", "hovedsignal"),
                             ("spor", "sporfelt"),
                             ("fra", "sporfelt"),
                             ("til", "sporfelt"),
                             ("utlosningsfelt", "sporfelt")):
                if tv.get(felt) and omd(ns, tv[felt]) != tv[felt]:
                    tv[felt] = omd(ns, tv[felt])
                    endret = True
                    n_refs += 1
            nyfrie = [omd("sporfelt", x) for x in tv.get("frie", [])]
            if nyfrie != tv.get("frie", []):
                n_refs += sum(1 for a, b in zip(nyfrie, tv["frie"])
                              if a != b)
                tv["frie"] = nyfrie
                endret = True
            for v in tv.get("sporveksler", []):
                if v.get("sporveksel") and \
                        omd("sporveksel", v["sporveksel"]) != v["sporveksel"]:
                    v["sporveksel"] = omd("sporveksel", v["sporveksel"])
                    endret = True
                    n_refs += 1
            nyid = _gen_togvei_id(tv, functions, st_map)
            if nyid and nyid != tv.get("id"):
                tv["id"] = nyid
                endret = True
        if endret:
            _skriv_og_publiser(forr, FORRIGLING_FILE, publish_forrigling)
    return jsonify({"ok": True, "version": data["version"],
                    "omdopt": len(renames), "referanser": n_refs})


@app.post("/api/node-alias")
def api_node_alias():
    """Sett/endre/fjern kallenavn for en node. Bytte av defekt ESP32 =
    sett samme kallenavn på ny MAC — alle bindinger følger med."""
    body = request.get_json(force=True)
    mac = (body.get("mac") or "").strip().lower()
    # STORE bokstaver, som MASTER — normaliseres også her, så API-kall
    # utenom UI-et ikke kan lage seksjon1/SEKSJON1-forviklinger
    alias = (body.get("alias") or "").strip().upper()
    if not valid_mac(mac):
        return jsonify({"error": "ugyldig MAC"}), 400
    if alias and not re.fullmatch(r"[A-Z0-9_-]{1,24}", alias):
        return jsonify({"error": "kallenavn: bokstaver/tall/-/_ "
                                 "(maks 24 tegn)"}), 400
    data = load_hal()
    # Fjern evt. gammelt kallenavn for denne MAC-en, og frigjør
    # kallenavnet hvis det pekte på en annen (defekt) MAC.
    gamle = [a for a, v in data.get("noder", {}).items()
             if v.get("mac") == mac and a != alias]
    noder = {a: v for a, v in data.get("noder", {}).items()
             if v.get("mac") != mac and a != alias}
    functions = data.get("functions", [])
    if alias:
        noder[alias] = {"mac": mac}
        # Skriv om eksisterende bindinger fra rå MAC OG fra nodens
        # tidligere kallenavn (omdøping skal aldri gi foreldreløse
        # bindinger — f.eks. seksjon1 -> SEKSJON1)
        for f in functions:
            for b in f.get("bindinger", []):
                if b.get("node") == mac or b.get("node") in gamle:
                    b["node"] = alias
    data = save_hal(functions=functions, noder=noder)
    return jsonify({"ok": True, "version": data["version"]})


# ---------- Forriglingstabellen (togveier) ----------

def load_forrigling() -> dict:
    if FORRIGLING_FILE.exists():
        with open(FORRIGLING_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"version": 0, "updated": None, "togveier": []}
    # Migrering: gammel ordnet "utlosning"-liste -> to rollefelt
    for tv in data.get("togveier", []):
        if "utlosning" in tv and "signalfall" not in tv:
            arr = tv.pop("utlosning")
            tv["signalfall"] = arr[0] if arr else ""
            tv["utlosningsfelt"] = arr[1] if len(arr) > 1 else \
                (arr[0] if arr else "")
    # Håndstilte veksler ut av veksellisten, over i låsekravet. Krever
    # HAL-en, som sier hvilke veksler som er manuelle og hvilken lås
    # som omfatter dem.
    migrate_forrigling(data, load_hal().get("functions", []))
    return data


def publish_forrigling(data: dict):
    mq.publish(FORRIGLING_TOPIC, json.dumps(data, ensure_ascii=False),
               retain=True)


@app.get("/api/forrigling")
def api_forrigling():
    return jsonify(load_forrigling())


@app.get("/api/forrigling-ack")
def api_forrigling_ack():
    return jsonify(cache["forrigling_ack"] or {})


@app.post("/api/forrigling")
def api_forrigling_save():
    body = request.get_json(force=True)
    togveier = body.get("togveier", [])
    hal = load_hal()
    # Typede oppslag: litra er unik per objektklasse, så referansene
    # slås opp i riktig navnerom (veksel 1 og sporfelt 1 kan begge finnes)
    fns = hal.get("functions", [])
    st_map = hal.get("signaltyper", {})
    hoved = {f["id"]: f for f in fns
             if sig_klasse(f.get("type", ""), st_map) == "hovedsignal"}
    vx = {f["id"]: f for f in fns if f.get("type") == "sporveksel"}
    felt = {f["id"]: f for f in fns if f.get("type") == "sporfelt"}
    seen = set()
    for tv in togveier:
        tid = (tv.get("id") or "").strip()
        if not tid:
            return jsonify({"error": "Alle togveier må ha ID"}), 400
        tegn = litra_ugyldig(tid)
        if tegn:
            return jsonify({"error": f"Togvei «{tid}»: tegnet '{tegn}' er "
                            f"ulovlig (brukes i MQTT-temaer)"}), 400
        if tid in seen:
            return jsonify({"error": f"Duplikat togvei-ID: {tid}"}), 400
        seen.add(tid)
        start = (tv.get("start") or "").strip()
        if not start:
            return jsonify({"error": f"{tid}: mangler startsignal"}), 400
        if start not in hoved:
            return jsonify({"error": f"{tid}: startsignal '{start}' er ikke "
                                     f"et hovedsignal i HAL"}), 400
        for v in tv.get("sporveksler", []):
            if v.get("sporveksel") not in vx:
                # Egen begrunnelse for manuellveksel: forriglingen kan
                # ikke kaste en håndstilt veksel, og den melder aldri
                # kontroll. Sikringen skjer med samlelås eller rigel.
                manuell = any(f.get("id") == v.get("sporveksel")
                              and f.get("type") == "manuellveksel"
                              for f in fns)
                if manuell:
                    return jsonify({"error":
                        f"{tid}: '{v.get('sporveksel')}' er en "
                        f"manuellveksel og kan ikke inngå i en togvei — "
                        f"sikre den med samlelås eller rigel i stedet"}), 400
                return jsonify({"error": f"{tid}: '{v.get('sporveksel')}' "
                                         f"er ikke en sporveksel i HAL"}), 400
            if v.get("stilling") not in ("normal", "avvik"):
                return jsonify({"error": f"{tid}: ugyldig stilling"}), 400
        laasgrupper = {f["id"] for f in fns
                       if f.get("type") in ("samlelaas", "rigel")}
        laaser = tv.get("laaser") or []
        if len(laaser) > MAX_TV_LAASER:
            return jsonify({"error": f"{tid}: {len(laaser)} låsegrupper — "
                                     f"maks {MAX_TV_LAASER}"}), 400
        for lg in laaser:
            if lg not in laasgrupper:
                return jsonify({"error": f"{tid}: '{lg}' er ikke en "
                                         f"samlelås eller rigel i HAL"}), 400
        felt_refs = list(tv.get("frie", [])) + \
            [tv.get("utlosningsfelt")]
        for sf in felt_refs:
            if sf and sf not in felt:
                return jsonify({"error": f"{tid}: '{sf}' er ikke et "
                                         f"sporfelt i HAL"}), 400
        # Utløsningsfeltet er en hendelse PÅ togveien — det må stå
        # blant feltene togveien krever frie. (Signalfall trenger
        # ingen konfig: ethvert felt i togveien feller signalet.)
        frie = set(tv.get("frie", []))
        uf = tv.get("utlosningsfelt")
        if uf and uf not in frie:
            return jsonify({"error": f"{tid}: utløsningsfeltet '{uf}' må "
                                     f"stå i «Frie sporfelt»"}), 400
        # Sporfelt-roller: spor kan være fritekst (eldre konfig), men
        # refererer den et kjent sporfelt, må rollen være togspor — og
        # da gjelder retningslogikken: en innkjørtogvei krever at
        # togsporfeltet er FRITT (toget skal dit), en utkjørtogvei kan
        # ikke kreve det fritt (toget STÅR der).
        spor = (tv.get("spor") or "").strip()
        spor_f = felt.get(spor)
        if spor_f is not None:
            if spor_f.get("rolle") != "togspor":
                return jsonify({"error": f"{tid}: '{spor}' er ikke et "
                                         f"sporfelt med rolle togspor"}), 400
            start_rolle = (hoved.get(start) or {}).get("rolle") or ""
            if start_rolle == "innkjor" and spor not in frie:
                return jsonify({"error": f"{tid}: innkjørtogvei — togspor"
                                f"feltet '{spor}' må stå i «Frie sporfelt» "
                                f"(sporet må være ledig for å ta imot "
                                f"tog)"}), 400
            if start_rolle == "utkjor" and spor in frie:
                return jsonify({"error": f"{tid}: utkjørtogvei — togspor"
                                f"feltet '{spor}' kan ikke stå i «Frie "
                                f"sporfelt» (toget står der)"}), 400
    kap = _kapasitet_feil_togvei(togveier)
    if kap:
        return jsonify({"error": "Kapasitet: " + " · ".join(kap)}), 400
    with lock:
        data = load_forrigling()
        data["version"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data["togveier"] = togveier
        stor = _for_stor(data, "Forriglingstabellen")
        if stor:
            return jsonify({"error": stor}), 400
        # Samme mønster som hal/anlegg: holdbar skriving, og
        # publiseringen INNENFOR låsen (se save_hal)
        _skriv_atomisk(FORRIGLING_FILE, data)
        publish_forrigling(data)
    return jsonify({"ok": True, "version": data["version"]})


# ---------- Lampeprøve: tenn hver konfigurerte lampe i tur ----------

lamptest = {"running": False, "progress": "", "i": 0, "total": 0}


def lamp_list(data):
    """Alle konfigurerte lamper: signalbindinger (anlegg/panel, én per
    lampeposisjon) og vekselens kontrollamper. Motorer/sensorer utelates."""
    st = data.get("signaltyper", {})
    noder = data.get("noder", {})
    lamps = []
    for f in data.get("functions", []):
        t = st.get(f.get("type"))
        for b in f.get("bindinger", []):
            mac = noder.get(b.get("node"), {}).get("mac", b.get("node"))
            if not valid_mac(str(mac).lower()):
                continue   # uoppløselig kallenavn: hopp over
            sted = b.get("sted")
            if t and sted in ("anlegg", "panel"):
                for k in range(int(t.get("lamper", 1))):
                    lamps.append((mac, b["i2c"], int(b["port"]) + k,
                                  f'{f["id"]} ({sted}) lampe {k + 1}'))
            elif sted in ("panel", "panel-normal", "panel-avvik",
                          "togveislampe", "lokalstillerlampe",
                          "middelkontrollampe"):
                # enkeltlamper på stillerapparatet: sporfeltindikering
                # og vekslenes kontrollamper
                lamps.append((mac, b["i2c"], int(b["port"]),
                              f'{f["id"]} ({sted})'))
    return lamps


def _lampe(mac, i2c, port, mode):
    mq.publish(f"{ROT}espnow/{mac}/out",
               json.dumps({"i2c": i2c, "port": port,
                           "mode": mode, "invert": True}))


def _alle_lamper(lamps, mode):
    for mac, i2c, port, _ in lamps:
        _lampe(mac, i2c, port, mode)
        time.sleep(0.02)   # ikke overkjør nodenes mottakskø


def _lt_vent(sek):
    """Avbrytbar venting — Stopp skal virke momentant. Avbryter også
    hvis master forsvinner UNDERVEIS: da har den mistet pausen (ikke
    retained), og bildemotoren dens vil male signalbilder oppå prøven.
    NB: kun offline-meldinger MOTTATT ETTER prøvestart teller — en
    foreldet retained-offline (fra forrige reboot/OTA) skal ikke
    kollapse prøven på et blunk."""
    slutt = time.time() + sek
    while lamptest["running"] and time.time() < slutt:
        if (cache.get("master_status") == "offline"
                and cache.get("master_status_ts", 0) > lamptest.get("start_ts", 0)):
            lamptest.update(running=False,
                            progress="AVBRUTT: master falt ut under "
                            "prøven (LWT offline)")
            return
        time.sleep(0.05)


def run_lamptest():
    """Slukk alt → alle blinker tre ganger → løpelys 0,5 s per lampe."""
    lamps = lamp_list(load_hal())
    lamptest.update(running=True, total=len(lamps), i=0, progress="",
                    start_ts=time.time())
    runde = 0
    try:
        if not lamps:
            return
        # HÅNDTRYKK: be master pause bildemotoren, og VENT på
        # kvitteringen før noe slukkes — ellers kan en master som
        # aldri fikk «start» stått og malt signalbildene oppå prøven
        cache["lampeprove_ack"] = None
        sendt = time.time()
        mq.publish(ROT + "master/lampeprove", "start")
        while time.time() - sendt < 3.0:
            a = cache.get("lampeprove_ack")
            if a and a["svar"] == "pauset":
                break
            time.sleep(0.05)
        else:
            lamptest.update(progress="AVBRUTT: master bekrefter ikke "
                            "pausen — kjører den eldre firmware, eller "
                            "rebootet den nettopp?")
            return
        # 1) Nullstill: alle lamper mørke
        lamptest.update(progress="slukker alle lamper")
        _alle_lamper(lamps, "av")
        _lt_vent(1.0)
        # 2) Alle blinker tre ganger — pulssynkront (1 s på / 1 s av),
        #    så hele anlegget blunker i takt via nodenes blinkmodus
        lamptest.update(progress="alle lamper blinker (3×)")
        _alle_lamper(lamps, "blink")
        _lt_vent(6.0)
        _alle_lamper(lamps, "av")
        # 3) Løpelys: én lampe om gangen, 0,5 s på
        while lamptest["running"]:
            runde += 1
            for idx, (mac, i2c, port, label) in enumerate(lamps):
                if not lamptest["running"]:
                    break   # stoppet av bruker
                lamptest.update(i=idx + 1,
                                progress=f"{label} (runde {runde})")
                _lampe(mac, i2c, port, "pa")
                _lt_vent(0.5)
                # Slukkes ALLTID — også lampen som lyste i Stopp-
                # øyeblikket (_lt_vent returnerer straks ved stopp)
                _lampe(mac, i2c, port, "av")
                _lt_vent(0.1)
    finally:
        lamptest.update(running=False,
                        progress=f"stoppet etter {runde} runder")
        # Gjenoppta re-render (utløser full gjenoppretting i master);
        # resync i tillegg for eldre master-firmware
        mq.publish(ROT + "master/lampeprove", "stopp")
        mq.publish(ROT + "master/resync", "")


@app.post("/api/togvei-betjen")
def api_togvei_betjen():
    """Betjeningsønske fra UI-et: publiseres til master, som kjører det
    gjennom forriglingen på vanlig måte — UI-et har ingen autoritet.

    Svaret masteren publiserer på nsi63/togvei/<id>/info fanges opp
    (se on_message) og ventes på i inntil ~1,5 s, så UI-et kan vise
    begrunnelsen direkte — «sikret», «avvist: …», «hjelpeutlosning
    trinn 1: …» osv. Kommer flere meldinger i vinduet (sikring i flere
    steg), returneres den SISTE; kommer ingen (master frakoblet,
    eller sikringen tar lengre tid), returneres svar=None og UI-et
    peker til meldingsloggen."""
    body = request.get_json(force=True)
    tid = (body.get("id") or "").strip()
    hva = body.get("hva")
    if not tid or hva not in ("sikre", "stopp", "hjelpeutlos"):
        return jsonify(
            {"error": "trenger id og hva=sikre|stopp|hjelpeutlos"}), 400
    sendt = time.time()
    mq.publish(f"{ROT}togvei/{tid}/set", hva)
    svar, svar_ts = None, None
    frist = sendt + 1.5
    while time.time() < frist:
        m = cache["togvei_info"].get(tid)
        if m and m["ts"] >= sendt:
            if svar != m["tekst"]:
                # nytt/endret svar — men ikke returner straks: et raskt
                # mellomsvar («sikring: venter sporvekselkontroll») skal
                # kunne avløses av fasiten («sikret: kjorsignal satt»)
                svar, svar_ts = m["tekst"], m["ts"]
            elif time.time() - svar_ts > 0.4:
                break              # svaret har stått stille — godta det
        time.sleep(0.05)
    return jsonify({"ok": True, "svar": svar})


# ---------- digitalt stillerapparat ----------
# Flask serverer BARE filene — panelet er en ren MQTT-klient over
# WebSocket rett mot mosquitto (port 9001, se bootstrap-nsi63.sh) og
# selvkonfigureres fra retained config-temaer. Ingen API-er her.

@app.get("/panel")
def panel_side():
    sti = Path(__file__).resolve().parent / "panel.html"
    if not sti.exists():
        return jsonify({"error": "panel.html mangler — kjør deploy"}), 404
    return send_file(sti, max_age=0)


@app.get("/panel/mqtt.js")
def panel_mqttjs():
    sti = Path(__file__).resolve().parent / "mqtt.min.js"
    if not sti.exists():
        return jsonify({"error": "mqtt.min.js mangler — kjør deploy"}), 404
    return send_file(sti, max_age=86400)


@app.get("/panel/routed-gothic.ttf")
def panel_font():
    """Routed Gothic (Camillo Osias, SIL OFL) — skiltfonten på
    sporplanen. Lokal kopi: panelet skal aldri hente noe utenfra."""
    sti = Path(__file__).resolve().parent / "routed-gothic.ttf"
    if not sti.exists():
        return jsonify({"error": "routed-gothic.ttf mangler"}), 404
    return send_file(sti, max_age=86400)


@app.get("/api/hendelser")
def api_hendelser():
    """Siste hendelser fra svartboksloggen, nyeste sist. Leser bare
    halen av fila (siste ~400 kB) — nok til noen tusen hendelser, og
    konstant kost uansett hvor stor loggen er. filter = delstreng som
    må finnes i rålinjen (tema eller data), ufølsom for store/små."""
    n = min(int(request.args.get("n", 300) or 300), 2000)
    filt = (request.args.get("filter") or "").lower()
    rader, kuttet = [], False
    try:
        with open(HENDELSE_FIL, "rb") as f:
            f.seek(0, 2)
            størrelse = f.tell()
            start = max(0, størrelse - 400_000)
            f.seek(start)
            rader = f.read().decode("utf-8", "replace").splitlines()
            if start > 0 and rader:
                rader = rader[1:]   # første linje kan være halv
                kuttet = True
    except OSError:
        pass
    ut = []
    for r in reversed(rader):
        if filt and filt not in r.lower():
            continue
        try:
            ut.append(json.loads(r))
        except ValueError:
            continue
        if len(ut) >= n:
            break
    ut.reverse()
    return jsonify({"hendelser": ut, "kuttet": kuttet, "aktiv": _h_aktiv})


@app.post("/api/hendelser/aktiv")
def api_hendelser_aktiv():
    """Slå hendelsesloggingen på/av. Valget huskes over restart
    (flaggfil); loggfila beholdes når loggingen slås av."""
    global _h_aktiv
    _h_aktiv = bool((request.get_json(force=True) or {}).get("aktiv"))
    try:
        if _h_aktiv:
            HENDELSE_AKTIV_FIL.touch()
        else:
            HENDELSE_AKTIV_FIL.unlink(missing_ok=True)
    except OSError:
        pass
    if _h_aktiv:
        hendelse_logg("pi/hendelseslogg", "logging slaatt paa", False)
    return jsonify({"ok": True, "aktiv": _h_aktiv})


@app.get("/api/hendelser/fil")
def api_hendelser_fil():
    if not HENDELSE_FIL.exists():
        return jsonify({"error": "ingen hendelser logget ennå"}), 404
    return send_file(HENDELSE_FIL, as_attachment=True,
                     download_name="nsi63-hendelser.jsonl", max_age=0)


@app.get("/api/lamptest")
def api_lamptest_status():
    return jsonify(lamptest)


@app.post("/api/lamptest")
def api_lamptest():
    body = request.get_json(force=True)
    if body.get("action") == "stop":
        lamptest["running"] = False
        return jsonify({"ok": True})
    # Sjekk-og-sett under lås: to samtidige forespørsler kunne begge
    # se «ikke i gang» og starte hver sin tråd, som så ville kjempet om
    # de samme lampene.
    with lock:
        if lamptest["running"]:
            return jsonify({"error": "lampeprøve pågår allerede"}), 400
        lamptest["running"] = True
    threading.Thread(target=run_lamptest, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/backup")
def api_backup():
    """Last ned komplett backup: HAL + forriglingstabell i én fil."""
    bundle = {"type": "nsi63-backup",
              "hal": load_hal(),
              "forrigling": load_forrigling(),
              # Til gjenoppbygging etter Pi-havari: ID-en VISES ved
              # restore men brukes aldri automatisk — en backup fra
              # ett anlegg skal ikke døpe om et annet
              "anlegg": _les_anlegg()}
    fname = ("nsi63-backup-" +
             datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    return Response(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


def _skriv_og_publiser(data: dict, fil, publiser):
    with lock:
        data["version"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _skriv_atomisk(fil, data)
        publiser(data)   # innenfor låsen — se save_hal


@app.post("/api/restore")
def api_restore():
    """Gjenopprett fra backupfil. Håndterer både komplett bundle
    (hal + forrigling) og eldre rene HAL-backuper."""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "ingen fil mottatt"}), 400
    try:
        data = json.loads(f.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return jsonify({"error": "filen er ikke gyldig JSON"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "ukjent filformat"}), 400

    # Bundle eller gammel ren HAL-fil?
    hal = data.get("hal") if "hal" in data else data
    forr = data.get("forrigling")
    if not isinstance(hal, dict) or not isinstance(hal.get("functions"), list):
        return jsonify({"error": "filen ser ikke ut som en nsi63-backup "
                                 "(mangler HAL/functions)"}), 400
    for fn in hal["functions"]:
        if not (isinstance(fn, dict) and (fn.get("id") or "").strip()):
            return jsonify({"error": "backupen inneholder funksjon uten "
                                     "litra"}), 400
    if forr is not None and not isinstance(forr.get("togveier"), list):
        return jsonify({"error": "forrigling-delen mangler togveier"}), 400

    # Samme node-validering som ved vanlig lagring — kjøres ETTER
    # migrate() så også eldre backupformater kontrolleres. Referansen
    # måles mot bundlens EGNE kallenavn (aliaser til noder som ikke er
    # sett ennå er legitime; UI-et viser dem som foreldreløse).
    hal = migrate(hal)
    noder = hal.get("noder") or {}
    for alias, v in noder.items():
        if not (isinstance(v, dict) and valid_mac((v.get("mac") or "").lower())):
            return jsonify({"error": f"backup: kallenavn '{alias}' har "
                                     f"ugyldig MAC"}), 400
    seen = set()
    for fn in hal["functions"]:
        fid = fn["id"].strip()
        tegn = litra_ugyldig(fid)
        if tegn:
            return jsonify({"error": f"backup: litra «{fid}» har ulovlig "
                            f"tegn '{tegn}' (MQTT) — rett i kilden"}), 400
        ns = litra_ns(fn.get("type"), hal.get("signaltyper"))
        if (ns, fid) in seen:
            return jsonify({"error": f"backup: duplikat litra i samme "
                                     f"gruppe: {fid}"}), 400
        seen.add((ns, fid))
        if len(fn.get("bindinger", []) or []) > 16:
            return jsonify({"error": f"backup: {fid}: maks 16 bindinger "
                                     f"per funksjon"}), 400
        for b in fn.get("bindinger", []) or []:
            node = (b.get("node") or "").strip()
            if node not in noder and not valid_mac(node.lower()):
                return jsonify({"error": f"backup: {fid} ({b.get('sted')}): "
                                         f"ukjent node '{node}'"}), 400
            b["node"] = node if node in noder else node.lower()

    # SAMME strukturvalidering som vanlig lagring. En backup er ikke
    # mer troverdig enn et skjema — den kan være redigert for hånd,
    # laget av en eldre versjon, eller vise til objekter som siden er
    # slettet. Gikk den rett ut retained, ville master fått en konfig
    # UI-et selv ville nektet å lagre.
    konflikter = _port_konflikter(hal["functions"],
                                  hal.get("signaltyper", {}), noder)
    if konflikter:
        return jsonify({"error": "backup, portkonflikt: "
                        + " · ".join(konflikter)}), 400
    topologi = _topologi_feil(hal["functions"])
    if topologi:
        return jsonify({"error": "backup: " + " · ".join(topologi)}), 400
    kap = _kapasitet_feil(hal["functions"], hal.get("signaltyper"))
    if kap:
        return jsonify({"error": "backup, kapasitet: "
                        + " · ".join(kap)}), 400
    stor = _for_stor(hal, "Backupens objektkonfigurasjon")
    if stor:
        return jsonify({"error": "backup: " + stor}), 400
    if forr is not None:
        kapt = _kapasitet_feil_togvei(forr["togveier"])
        if kapt:
            return jsonify({"error": "backup, kapasitet: "
                            + " · ".join(kapt)}), 400
        stor = _for_stor(forr, "Backupens forriglingstabell")
        if stor:
            return jsonify({"error": "backup: " + stor}), 400
        # Togveiene må vise til objekter som finnes i BACKUPENS egen HAL
        litra = {(f.get("id") or "").strip() for f in hal["functions"]}
        for tv in forr["togveier"]:
            if not isinstance(tv, dict) or not (tv.get("id") or "").strip():
                return jsonify({"error": "backup: togvei uten id"}), 400
            mangler = [x for x in
                       ([tv.get("start")] + (tv.get("frie") or []) +
                        [v.get("sporveksel")
                         for v in (tv.get("sporveksler") or [])
                         if isinstance(v, dict)])
                       if x and x not in litra]
            if mangler:
                return jsonify({"error": f"backup: togvei {tv['id']} viser "
                                f"til ukjente objekter: "
                                f"{', '.join(sorted(set(mangler)))}"}), 400

    _skriv_og_publiser(hal, HAL_FILE, publish_config)
    n_tv = None
    if forr is not None:
        _skriv_og_publiser(forr, FORRIGLING_FILE, publish_forrigling)
        n_tv = len(forr["togveier"])
    # Anleggs-ID-en i backupen brukes ALDRI automatisk (den ville døpt
    # om anlegget) — den meldes bare tilbake så UI-et kan opplyse
    ba = data.get("anlegg")
    ba_id = (ba.get("id") or "") if isinstance(ba, dict) else ""
    return jsonify({"ok": True, "version": hal["version"],
                    "functions": len(hal["functions"]),
                    "togveier": n_tv,
                    "anlegg_i_backup": ba_id or None})


@app.post("/api/find")
def api_find():
    """Få noden til å blinke gult i 10 s — fysisk identifisering."""
    body = request.get_json(force=True)
    mac = (body.get("mac") or "").strip().lower()
    if not valid_mac(mac):
        return jsonify({"error": "ugyldig MAC"}), 400
    mq.publish(f"{ROT}espnow/{mac}/cmd", "blink")
    return jsonify({"ok": True})


@app.post("/api/forget")
def api_forget():
    """Be master glemme en node (fjernes fra oversikt + retained-temaer).
    En levende node melder seg naturligvis inn igjen av seg selv."""
    body = request.get_json(force=True)
    mac = (body.get("mac") or "").strip().lower()
    if not valid_mac(mac):
        return jsonify({"error": "ugyldig MAC"}), 400
    mq.publish(ROT + "master/forget", mac)
    return jsonify({"ok": True})


# ---------- UI ----------

# ---------- brukerflaten ----------
# HTML, CSS og JavaScript ligger i ui/ som EGNE filer, ikke som en
# Python-streng. Det var 2800 linjer JavaScript inne i en tekststreng
# Python tolket escape-sekvensene i: en «\n» i JS-koden ble et ekte
# linjeskift midt i en JS-streng og knakk hele siden — en feilklasse
# som ikke kan oppstå i en .js-fil. Nå kan filene også syntakssjekkes
# før de rulles ut (node --check ui/app.js).
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_FILER = {"app.js": "application/javascript",
            "app.css": "text/css"}


@app.get("/ui/<fil>")
def ui_fil(fil):
    if fil not in UI_FILER:
        return jsonify({"error": "ukjent fil"}), 404
    sti = UI_DIR / fil
    if not sti.exists():
        return jsonify({"error": f"{fil} mangler — kjør deploy"}), 404
    # max_age=0: konfigverktøyet skal aldri servere gammel kode fra
    # nettleserens buffer etter en utrulling.
    return send_file(sti, max_age=0, mimetype=UI_FILER[fil])


@app.get("/")
def index():
    sti = UI_DIR / "index.html"
    if not sti.exists():
        return jsonify({"error": "ui/index.html mangler — kjør deploy"}), 404
    return send_file(sti, max_age=0, mimetype="text/html")


# Alt er definert — nå kan nettverkstråden trygt kalle on_connect,
# som re-hevder konfigen (se hevd_konfig).
mq.connect_async(MQTT_HOST, 1883, 60)
mq.loop_start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

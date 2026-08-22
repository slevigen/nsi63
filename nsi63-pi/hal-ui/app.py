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
    return (sted.startswith(("sensor", "stiller")) or sted == "kvittering"
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
        spr = f.get("sperrer") or []
        if len(spr) > 2:
            feil.append(f"{fid}: {len(spr)} sperrer-linjefelt — maks 2 "
                        f"(tomt = hele stasjonen)")
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
        # sperrer-avgrensningen må derimot peke på virkelige
        # linjefelt — den styr forriglingen direkte.
        for v in f.get("omfatter") or []:
            if v in veksler or v in sperrer_ids:
                continue
            tegn = litra_ugyldig(v)
            if tegn:
                feil.append(f"{f.get('type')} {f.get('id')}: objektet "
                            f"«{v}» utenfor anlegget har ulovlig tegn "
                            f"'{tegn}'")
        for lf in f.get("sperrer") or []:
            if lf not in linjefelt:
                feil.append(f"{f.get('type')} {f.get('id')} sperrer "
                            f"ukjent linjefelt {lf}")
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

PAGE = """<!doctype html>
<html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSI63 — sikringsanlegg</title>
<style>
  :root { --bg:#14171c; --panel:#1d232b; --line:#2e3742; --fg:#e8e6e3;
          --dim:#98a2ae; --acc:#e0a437; --ok:#5bb974; --warn:#e06c5b; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 system-ui, sans-serif; }
  header { padding:18px 24px; border-bottom:2px solid var(--acc);
           display:flex; justify-content:space-between; align-items:baseline; }
  h1 { margin:0; font-size:20px; letter-spacing:.06em; }
  h1 small { color:var(--dim); font-weight:400; margin-left:10px; }
  #status { color:var(--dim); font-size:13px; }
  main { padding:20px 24px; max-width:1280px; margin:0 auto; }
  table { width:100%; border-collapse:collapse; background:var(--panel); }
  th, td { padding:6px 8px; border:1px solid var(--line); text-align:left; }
  th { color:var(--dim); font-size:11px; text-transform:uppercase;
       letter-spacing:.08em; }
  th.grp { text-align:center; color:var(--acc); }
  /* Avkryssingsbokser må unntas width:100% under — ellers strekkes
     selve boksen over hele etiketten, og teksten havner langt til
     høyre for den. Gjelder alle avkryssinger i UI-et. */
  input[type=checkbox] { width:auto; margin:0 4px 0 0;
                         vertical-align:middle; }
  input, select { width:100%; background:var(--bg); color:var(--fg);
                  border:1px solid var(--line); border-radius:4px;
                  padding:5px 7px; font:inherit; }
  input:focus, select:focus { outline:1px solid var(--acc); }
  select:disabled, input:disabled { opacity:.25; }
  td.port select { width:70px; }
  .hint { color:var(--dim); font-size:11px; }
  /* tegnefelter: gjelder KUN sporplan-tegningen, skjult til de
     klikkes fram — ikke alle vil ha et digitalt panel */
  .tegnvis { color:var(--dim); font-size:11px; cursor:pointer;
             text-decoration:underline dotted; user-select:none; }
  .subrow td { border-top:none; background:#181d24; }
  .grphead td { background:#10141a; border-top:2px solid #2a3140;
                padding:10px 8px 6px; }
  .skisse { margin:0; line-height:1.7; overflow-x:auto;
            font-size:13px; color:#7f8ba0; }
  .sk-hs { color:#ff6b6b; }   /* hovedsignal */
  .sk-fs { color:#ffd75e; }   /* forsignal */
  .sk-ts { color:#6db3ff; }   /* togspor */
  .sk-lf { color:#c792ea; }   /* linjefelt */
  .sk-mf { color:#4dd0c4; }   /* varselfelt */
  .sk-vx { color:#ffa657; }   /* veksel */
  .grphead b { color:var(--acc); }
  .grp-pil { display:inline-block; width:14px; color:var(--acc); }
  .sub-label { color:var(--dim); font-size:12px; text-align:right; }
  button { background:var(--panel); color:var(--fg); border:1px solid var(--line);
           border-radius:4px; padding:8px 14px; font:inherit; cursor:pointer; }
  button:hover { border-color:var(--acc); }
  button.primary { background:var(--acc); color:#14171c; border:none;
                   font-weight:600; }
  button.mini { padding:2px 8px; font-size:12px; }
  .row-del { color:var(--warn); border:none; background:none; font-size:15px; }
  .bar { display:flex; gap:10px; margin:16px 0; align-items:center; }
  .spacer { flex:1; }
  #msg { font-size:14px; }
  #msg.ok { color:var(--ok); } #msg.err { color:var(--warn); }
  nav { display:flex; gap:6px; }
  .tab { padding:6px 16px; border-radius:4px 4px 0 0; }
  .tab.active { background:var(--acc); color:#14171c; border-color:var(--acc);
                font-weight:600; }
  .card { background:var(--panel); border:1px solid var(--line);
          border-radius:6px; padding:14px 16px; margin-bottom:16px; }
  .card h2 { margin:0 0 4px; font-size:16px; letter-spacing:.04em; }
  .card h2 .off { color:var(--warn); font-size:13px; }
  .card h2 .on { color:var(--ok); font-size:13px; }
  .chips { display:flex; flex-wrap:wrap; gap:16px; margin-top:10px; }
  .chip table { width:auto; }
  .chip caption { color:var(--acc); font-size:12px; text-align:left;
                  padding:2px 0 6px; letter-spacing:.06em; }
  .chip td, .chip th { padding:2px 10px; font-size:13px; }
  .bit1 { color:var(--ok); } .bit0 { color:var(--warn); font-weight:600; }
  .fri { color:#4a5563; }
</style></head><body>
<header>
  <h1 id="tittel">NSI63<small>sikringsanlegg</small></h1>
  <nav>
    <button class="tab active" onclick="showView('noder', this)">System</button>
    <button class="tab" onclick="showView('hal', this)">Objekter</button>
    <button class="tab" onclick="showView('forrigling', this)">Forrigling</button>
  </nav>
  <div id="status">laster…</div>
<div id="lpbanner" style="display:none;background:#7a5210;color:#ffe9c4;
     padding:8px 14px;border-radius:8px;margin:8px 0;font-weight:600">
  ⚠ LAMPEPRØVE PÅGÅR — <span id="lpbanner-txt"></span>
  <button class="mini" style="margin-left:12px"
          onclick="lampTest('stop')">Avslutt lampeprøve</button>
</div>
<div id="testbanner" style="display:none;background:#7a2f10;color:#ffd9c4;
     padding:8px 14px;border-radius:8px;margin:8px 0;font-weight:600">
  ⚠ TESTMODUS — MQTT-kommandoer omgår forriglingen. Stillerapparatet og
  sikring av togvei er fortsatt forriglet.
  <button class="mini" style="margin-left:12px"
          onclick="slaAvTestmodus()">Skru av testmodus</button>
</div>
</header>
<main>
<section id="view-hal" style="display:none">
  <div class="bar" style="margin:0 0 8px">
    <input id="halfilter" style="max-width:280px"
           placeholder="filtrer: litra, type eller node…"
           oninput="halFilter(this.value)">
  </div>
  <table id="tbl">
    <thead>
      <tr>
        <th rowspan="2" style="width:6%">Litra</th>
        <th rowspan="2" style="width:10%">Type</th>
        <th rowspan="2" style="width:16%"></th>
        <th class="grp" colspan="3">Binding</th>
        <th class="grp" colspan="3">Panel (stillerapparat)</th>
        <th rowspan="2">Notat</th><th rowspan="2"></th>
      </tr>
      <tr>
        <th>Node</th><th>I2C</th><th>Port</th>
        <th>Node</th><th>I2C</th><th>Port</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
  <div class="bar">
    <input type="file" id="restoreFile" accept=".json,application/json"
           style="display:none" onchange="restoreBackup(this)">
    <span class="spacer"></span>
    <span id="msg"></span>
    <button class="primary" onclick="save()">Lagre og publiser</button>
  </div>
  <p class="hint">Signaler: port = førsteport, lampene på påfølgende kanaler;
  hovedraden er anleggssignalet. Veksler: motorutgang normal (hovedraden)
  og avvik + stiller (betjeningsbryteren — vridd mot GND = avvik),
  deretter én linje per stilling med stillingssensoren i bindings-
  kolonnene og kontrollampen i panelkolonnene (lyser når stillingen er
  bekreftet av sensor). Skiftesignal: stiller-binding = bryter
  (mot GND = skifting tillatt). Sporfeltenes panellampe er TENT når
  feltet er fritt; varselfeltets blinker mens varslet står ukvittert.
  Varselfelt: sensor-ytre = lengst fra stasjonen — slår den ut
  først, er toget i anmarsj og varselklokken ringer; indre først =
  utgående tog, intet varsel. Brytere med rolle signalstopp/frigivning:
  panel-bindingen er kontrollampen; sporvekselens lokalstillerlampe er tent når
  den er frigitt for lokal omlegging.
  Sporfelt: én sensorrad per seksjon feltet krysser (logisk OR).
  Alle bindinger starter på «—» (ingen) — rader du lar stå tomme
  lagres ikke. Bindinger er valgfrie: en litra uten bindinger finnes
  rent logisk (f.eks. sporfelt som simuleres til sensorene er koblet).
  I2C-forvalgene er kun forslag — enhver PCA9685 kan drive enhver
  utgang, og en node kan ha flere av hver brikke.</p>
</section>
<section id="view-forrigling" style="display:none">
  <div class="card">
    <pre id="fr-skisse" class="skisse"></pre>
    <div id="fr-tegn" class="hint" style="margin-top:4px"></div>
    <div id="fr-adv" class="hint" style="margin-top:6px"></div>
  </div>
  <div id="fr-cards"></div>
  <div class="bar">
    <button id="fr-ny" onclick="frAdd()">+ Ny togvei</button>
    <span id="fr-krav" class="hint"></span>
    <span class="spacer"></span>
    <span id="fr-msg"></span>
    <button class="primary" onclick="frSave()">Lagre og publiser</button>
  </div>
  <div id="fr-konflikter"></div>
  <p class="hint">En togvei går FRA et sporfelt TIL et sporfelt:
  linjefelt→togspor er innkjør, togspor→linjefelt er utkjør, og
  togspor→togspor er indre togvei (krever hovedsignal med rolle indre).
  Hovedsignalet, ID-en, de frie feltene og utløsningsfeltet avledes av
  endene — koble hovedsignalene til linjefeltet de står foran
  («foran» under Objekter) så blir signalvalget entydig. Signalbildet utledes
  automatisk — veksel i avvik gir «kjør med redusert hastighet».
  Fiendtlige togveier beregnes av tabellen (felles sporfelt eller
  veksel i ulik stilling) og håndheves av master.</p>
</section>
<section id="view-noder"></section>
</main>
<script>
let SIGNALTYPER = {};
// Signalklasse for en type — fra typedefinisjonen, ellers navneprefiks
function sigKlasse(t) {
  const st = SIGNALTYPER[t];
  if (st && st.klasse) return st.klasse;
  for (const k of ["forsignal", "skiftesignal", "dvergsignal",
                   "hovedsignal"])
    if ((t || "").startsWith(k)) return k;
  return null;
}
const erHoved = t => sigKlasse(t) === "hovedsignal";
const TYPES = ["hovedsignal3","hovedsignal2","forsignal2",
               "skiftesignal2","skiftesignal1",
               "dvergsignal3",
               "sporveksel","manuellveksel","sporsperre",
               "utgang","klokke",
               "sporfelt","bryter","trykknapp","inngang","amperemeter",
               "samlelaas","rigel"];
// Grupper i HAL-tabellen: objektene som inngår i forriglingen først,
// alt annet samlet nederst. Typevalget på raden begrenses til gruppen.
const GRUPPER = [
  {navn: "Signaler",    typer: ["hovedsignal3","hovedsignal2",
                                "forsignal2",
                                "skiftesignal2","skiftesignal1",
                                "dvergsignal3"]},
  {navn: "Sporveksler", typer: ["sporveksel","manuellveksel"]},
  // Sporsperren er en egen ting: normalstillingen er PÅLAGT, den har
  // ingen ende, ingen Lok-frigivning og nesten ingen av vekselens
  // portkonfigurasjon. Egen gruppe, egne ord.
  {navn: "Sporsperrer", typer: ["sporsperre"]},
  {navn: "Sporfelt",    typer: ["sporfelt"]},
  {navn: "Trykknapper og brytere", typer: ["trykknapp","bryter"]},
  // «utgang» og «inngang» er RENE bindingsholdere: master har ingen
  // logikk for dem, så de driver ingenting av seg selv. De er nyttige
  // for å reservere porter og dokumentere kabling — men en port bundet
  // til «utgang» teller mot nodens 40-tak uten noen gang å bli satt.
  {navn: "Annet",       typer: ["utgang","klokke","inngang",
                                "amperemeter","samlelaas","rigel"]},
];
const COLLAPSED = new Set();   // sammenlagte grupper (per sidevisning)
function gruppeIdx(type) {
  const i = GRUPPER.findIndex(g => g.typer.includes(type));
  return i < 0 ? GRUPPER.length - 1 : i;
}
// Full adresseliste — brukes som reserve når valgt node ikke har
// meldt brikkene sine (offline/aldri sett/planlegging).
// PCA9685: 16 kanaler (0-15), PCF8574: 8 pinner (0-7).
const I2C_ALLE = ["0x40","0x41","0x42","0x43","0x20","0x21","0x22","0x23"];
// GPIO-pseudobrikken (fw v4): nodens egne pinner, port 0-5 med fast
// kart til fysiske pinner på AtomS3 Lite. Inn ELLER ut per port —
// retningen avledes av bindingsstedet, master ordner resten.
const GPIO_PINNER = ["G5","G6","G7","G8","G38","G39"];
function i2cLabel(a) {
  if (a === "gpio") return "GPIO (på noden)";
  return a + (a.startsWith("0x4") ? " PCA9685" : " PCF8574");
}
// Brikkene valgt node faktisk har meldt (null = ukjent -> full liste)
function i2cListFor(nodeVal) {
  const mac = (NODER[nodeVal] && NODER[nodeVal].mac) || nodeVal;
  const n = liveNodes.find(x => x.mac === mac);
  return (n && n.i2c && n.i2c.length) ? n.i2c : null;
}
function i2cOptions(nodeVal, sel) {
  const found = i2cListFor(nodeVal);
  const list = (found || I2C_ALLE).concat(["gpio"]);   // alltid tilbudt
  let out = "";
  for (const a of list) out += opt(a, i2cLabel(a), sel);
  if (sel && !list.includes(sel))
    out += opt(sel, i2cLabel(sel) + " (ikke funnet)", sel);
  return out;
}
let liveNodes = [];

const isSignal = t => t in SIGNALTYPER;
// EKSAKTE tester. «sporveksel» er sentralstilt og inngår i
// forriglingen; «manuellveksel» er håndstilt og står utenfor — den er
// med for å tegne panelet og for å kunne betjenes med knapp/bryter
// over nodens porter.
const isVeksel = t => t === "sporveksel";
const isManuell = t => t === "manuellveksel";
const isNoenVeksel = t => isVeksel(t) || isManuell(t);
const isSperre = t => t === "sporsperre";   // deler vekselmaskineriet
const isLaas = t => t === "samlelaas" || t === "rigel";
// Via sigKlasse(), ikke oppslag i SIGNALTYPER: da arves navne-
// fallbacken, og en håndredigert hal.json uten "klasse"-felt mister
// ikke tilleggsvalgene på raden.
const isDverg = t => sigKlasse(t) === "dvergsignal";
// Høyt skiftesignal finnes i to varianter (skiftesignal1 fjernstyrt,
// skiftesignal2 uten fjernstyring). UI-et skal behandle dem likt, så
// sjekk KLASSEN — aldri typenavnet. Da følger en eventuell tredje
// variant med av seg selv.
const isSkift = t => sigKlasse(t) === "skiftesignal";
// Rolle-listen per type: [0] er hovedradens binding, resten faste underrader
function roller(t) {
  if (isVeksel(t))
    return ["ut-normal","ut-avvik","sensor-normal","sensor-avvik",
            "panel-normal","panel-avvik"];
  // Manuellveksel: drivutganger om den skal kunne betjenes med
  // knapp/bryter over noden — ingen sensorer, ingen kontrollamper.
  if (isManuell(t)) return ["ut-normal","ut-avvik"];
  // Sporsperre: valgfrie drivutganger og ÉN pålagt-kontroll, med
  // sperrens egne ord.
  if (isSperre(t)) return ["ut-paalagt","ut-avlagt","sensor-paalagt"];
  if (t === "sporfelt") return ["sensor"];
  return ["anlegg"];
}
const panelOk = t => isSignal(t) || t === "sporfelt" ||
                     t === "bryter" || t === "trykknapp" ||
                     isLaas(t);   // kontrollampen på apparatet

// Attributt-escaping. Litra, notater og kallenavn er BRUKERDATA og
// settes inn i HTML-attributter via innerHTML. Uten escaping bryter
// et anførselstegn ut av attributtet — et litra som «A" onfocus="…»
// ville kjørt vilkårlig skript i konfigverktøyet. Serversiden avviser
// riktignok en del tegn i litra, men notater og kallenavn er frie, og
// en importert backup kan inneholde hva som helst.
function attr(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function opt(v, t, sel) {
  return `<option value="${v}" ${v===sel?"selected":""}>${t}</option>`;
}
let NODER = {};   // kallenavn -> {mac}
function aliasFor(mac) {
  for (const [a, v] of Object.entries(NODER)) if (v.mac === mac) return a;
  return null;
}
function nodeOptions(sel, allowEmpty) {
  let out = allowEmpty ? opt("", "—", sel) : "";
  const seen = new Set();
  for (const [alias, v] of Object.entries(NODER)) {
    seen.add(alias); seen.add(v.mac);
    const live = liveNodes.find(n => n.mac === v.mac);
    const tag = live ? (live.online ? "" : " (offline)") : " (aldri sett)";
    out += opt(alias, alias + tag, sel);
  }
  for (const n of liveNodes) {
    if (seen.has(n.mac)) continue;
    out += opt(n.mac, n.mac + (n.online ? "" : " (offline)"), sel);
  }
  if (sel && !out.includes(`value="${sel}"`)) out += opt(sel, sel + " (ukjent)", sel);
  return out;
}
function portCount(addr) {
  if (addr === "gpio") return GPIO_PINNER.length;
  return addr.startsWith("0x4") ? 16 : 8;
}
function portOptions(n, sel, addr) {
  let out = "";
  for (let p = 0; p < n; p++) {
    const t = (addr === "gpio") ? `${p} (${GPIO_PINNER[p]})` : String(p);
    out += opt(String(p), t, String(sel));
  }
  return out;
}
function i2cChanged(sel, prefix) {
  // Bytt portliste når brikketypen endres (PCA: 0-15, PCF: 0-7)
  const portSel = sel.closest("tr").querySelector("." + prefix + "-port");
  const n = portCount(sel.value);
  const cur = Math.min(parseInt(portSel.value || "0"), n - 1);
  portSel.innerHTML = portOptions(n, cur, sel.value);
}
function nodeChanged(sel, prefix) {
  // Nytt nodevalg -> vis den nodens faktiske brikker i I2C-listen
  const tr = sel.closest("tr");
  const i2cSel = tr.querySelector("." + prefix + "-i2c");
  const cur = i2cSel.value;
  i2cSel.innerHTML = i2cOptions(sel.value, cur);
  if (!i2cSel.value) i2cSel.selectedIndex = 0;
  i2cChanged(i2cSel, prefix);
}
function bindCells(prefix, b, defI2c) {
  // Alle bindinger starter på "—" (ingen) — bare bevisste valg lagres
  const i2cVal = b.i2c || defI2c;
  return `
    <td><select class="${prefix}-node" onchange="nodeChanged(this,'${prefix}')">${nodeOptions(b.node||"", true)}</select></td>
    <td><select class="${prefix}-i2c" onchange="i2cChanged(this,'${prefix}')">${i2cOptions(b.node||"", i2cVal)}</select></td>
    <td class="port"><select class="${prefix}-port">${portOptions(portCount(i2cVal), b.port??0, i2cVal)}</select></td>`;
}
function defaultI2c(sted) {
  if (sted.startsWith("sensor")) return "0x20";
  if (sted.startsWith("stiller")) return "0x20";  // betjening = inngang
  if (sted.startsWith("lokal-")) return "0x20";   // betjening ute ved
      // objektet. Bindestreken skiller den fra «lokalstillerlampe»,
      // som er en LAMPE og skal ha utgangsbrikken.
  if (sted === "kvittering") return "0x20";       // knapp = inngang
  if (sted.startsWith("ut-")) return "0x41";
  return "0x40";
}
// sted2/b2: valgfri binding nr. 2 på samme linje, i panelkolonnene
// (brukes av veksler: kontrollampen på stillingssensorens linje)
function addSubRow(fnTr, sted, b, removable, sted2, b2) {
  b = b || {};
  const del = removable
    ? '<button class="row-del" onclick="this.closest(\\'tr\\').remove()">✕</button>'
    : "";
  const tr = document.createElement("tr");
  tr.className = "subrow";
  tr.dataset.sted = sted;
  if (sted2) tr.dataset.sted2 = sted2;
  const lbl = sted2 ? `${sted} + ${sted2} &rarr;` : `${sted} &rarr;`;
  const hoyre = sted2 ? bindCells("t", b2 || {}, defaultI2c(sted2))
                      : `<td colspan="3"></td>`;
  tr.innerHTML = `
    <td colspan="3" class="sub-label">${lbl}</td>
    ${bindCells("s", b, defaultI2c(sted))}
    ${hoyre}
    <td>${del}</td>`;
  let after = fnTr;
  while (after.nextElementSibling?.classList.contains("subrow"))
    after = after.nextElementSibling;
  after.insertAdjacentElement("afterend", tr);
}
function fillHovedSel(sel) {
  // Nedtrekk over hovedsignal-litraer — kun litraen vises (etiketten
  // står utenfor select-en)
  const cur = sel.value;
  // varsler-nedtrekket: tomt valg = auto (forriglingen avleder
  // utkjørsignalet fra togveiens spor); montert: tomt = ingen
  const tom = sel.classList.contains("f-varsler") ? "auto" : "—";
  let out = `<option value="">${tom}</option>`;
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const ht = tr.querySelector(".f-type").value;
    if (!erHoved(ht)) continue;
    const id = tr.querySelector(".f-id").value.trim();
    if (id) out += opt(id, id, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, `${cur} (ukjent)`, cur);
  sel.innerHTML = out;
  sel.value = cur;
}
function decorateRow(tr) {
  const t = tr.querySelector(".f-type").value;
  const extraCell = tr.querySelector(".f-extra");
  if (t === "forsignal2") {
    // Etiketten står UTENFOR select-en, så litraen alltid er synlig
    const curM = tr.dataset.montert || "";
    const curV = tr.dataset.varsler || "";
    extraCell.innerHTML =
      `<span class="hint">montert:</span> ` +
      `<select class="f-montert" title="Hovedsignal på samme mast — forsignalet slukkes når det viser stopp" onfocus="fillHovedSel(this)">` +
      opt(curM, curM || "—", curM) + `</select><br>` +
      `<span class="hint">varsler:</span> ` +
      `<select class="f-varsler" style="margin-top:2px" title="Hovedsignalet forsignalet varsler om — bildet følger det automatisk. «auto»: forriglingen avleder utkjørsignalet fra den aktive togveiens spor (krever utkjørtogveier med spor satt i tabellen). Et valgt signal brukes som reserve når avledningen ikke finner noe." onfocus="fillHovedSel(this)">` +
      opt(curV, curV || "auto", curV) + `</select>`;
  } else if (t === "hovedsignal3") {
    const cur = tr.dataset.rolle || "utkjor";
    const curL = tr.dataset.linje || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="Innkjør viser 20A (blink) i stopp, utkjør viser 20B (fast). Indre hovedsignal brukes for togveier fra togspor til togspor.">` +
      opt("innkjor", "innkjør", cur) + opt("utkjor", "utkjør", cur) +
      opt("indre", "indre (ikke i master ennå)", cur) +
      `</select><br>` +
      `<span class="hint">foran:</span> ` +
      `<select class="f-linje" style="margin-top:2px" title="Linjefeltet signalet står FORAN (i signalets kjøreretning): innkjør foran linjefeltet det står ved på vei inn, utkjør foran linjefeltet toget kjører ut på. Brukes til å avlede signalet når togveier lages fra→til." onfocus="fillLinjeSel(this)">` +
      opt(curL, curL || "—", curL) + `</select>`;
  } else if (t === "hovedsignal2") {
    const curL = tr.dataset.linje || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="Tolys utkjørsignal: viser bare 20B (stopp) og 21 (kjør redusert) — for spor der utkjøring alltid går over veksel i avvik. Alltid rolle utkjør.">` +
      opt("utkjor", "utkjør (tolys)", "utkjor") + `</select><br>` +
      `<span class="hint">foran:</span> ` +
      `<select class="f-linje" style="margin-top:2px" title="Linjefeltet signalet står foran (linjefeltet toget kjører ut på)" onfocus="fillLinjeSel(this)">` +
      opt(curL, curL || "—", curL) + `</select>`;
  } else if (isSkift(t)) {
    const curM = tr.dataset.montert || "";
    extraCell.innerHTML =
      `<span class="hint">på mast:</span> ` +
      `<select class="f-montert" title="Hovedsignalet skiftesignalet er montert med (Sokna: ZL på utkjør L, ZM på utkjør M) — brukes av panelets sporplan til plasseringen. Tom = egen mast." onfocus="fillHovedSel(this)">` +
      opt(curM, curM || "—", curM) + `</select><br>` +
      `<span class="hint" title="Vekslene det høye skiftesignalet gjelder for — «ZM gjelder for skifting over sporveksel 1 forbi utkjørhovedsignalene M og O». Området er vekselen, ikke linjen: én stasjonshals kan betjene flere linjefelt. Stasjonsenden utledes av vekslene, så signalet trenger ingen egen venstre/høyre.">gjelder veksel:</span><br>` +
      skiftVekselBoks(tr);
  } else if (isDverg(t)) {
    const cur = tr.dataset.montert || "";
    extraCell.innerHTML =
      `<span class="hint">på signal:</span> ` +
      `<select class="f-montert" title="Utkjørhovedsignalet dvergsignalet står på eller ved. Bildet avledes: signal 45 når utkjørtogvei fra dette signalet er sikret, signal 46 når halsen er frigitt for lokal omlegging eller det høye skiftesignalet viser 42, ellers signal 43. Stasjonsenden arves fra hovedsignalets «foran»-linjefelt." onfocus="fillHovedSel(this)">` +
      opt(cur, cur || "—", cur) + `</select>`;
  } else if (isSignal(t)) {
    extraCell.textContent = SIGNALTYPER[t].lamper + " lamper";
  } else if (t === "trykknapp") {
    const cur = tr.dataset.rolle || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="jord: oppstartsritual — etter master-boot er alle signaler sperret til denne knappen trykkes (som forbildets strømstans-prosedyre). Panel-bindingen er den røde kontrollampen, tent mens anlegget er sperret.">` +
      opt("", "rolle: —", cur) + opt("jord", "jord (oppstart)", cur) +
      `</select>`;
  } else if (t === "amperemeter") {
    const u = tr.dataset.utslag || "100";
    extraCell.innerHTML =
      `<span class="hint">utslag:</span> ` +
      `<input class="f-utslag" type="number" min="0" max="100" ` +
      `style="max-width:60px" value="${u}" ` +
      `title="Viserutslag i % av fullt PWM-pådrag mens en veksel legger om. Instrumentet (dreiespole) kobles til PCA-kanalen i anleggsbindingen."> ` +
      `<span class="hint">%</span>`;
  } else if (t === "klokke") {
    const hk = tr.dataset.hakk || "50";
    const du = tr.dataset.duty || "50";
    extraCell.innerHTML =
      `<span class="hint" title="Én klokke gjør alle jobbene, som i forbildet: varselklokke (tog i anmarsj), sporvekselklokke (omlegging/ute av kontroll), togveiklokke (togveistiller holdes utslått) og signalstoppklokke — alle med 30 s spolevern per hendelse.">alle klokkefunksjonene</span><br>` +
      `<span class="hint">hakk:</span> ` +
      `<input class="f-hakk" type="number" min="10" max="250" ` +
      `style="max-width:60px" value="${hk}" ` +
      `title="Hakkfrekvensen for klokkens solenoid i Hz (standard 50). Gjelder GPIO-bindinger — solenoiden og klangbunnen har en mekanisk resonans, så prøv deg frem (f.eks. 30/40/50) til lyden bærer best. Trer i kraft ved lagring, uten ny firmware."> ` +
      `<span class="hint">Hz · duty:</span> ` +
      `<input class="f-duty" type="number" min="10" max="90" ` +
      `style="max-width:55px" value="${du}" ` +
      `title="Hvor stor del av hver hakkperiode spolen får strøm, i % (standard 50). Lavere = kaldere spole og lettere anslag, høyere = hardere anslag men mer varme — spolens snittvarme er direkte proporsjonal med duty. Kvantiseres til nærmeste 1/16. Trer i kraft ved lagring. Ringingen kappes uansett av masteren etter 30 s (spolevern); meldingslampen blinker videre til kvittering."> ` +
      `<span class="hint">%</span>`;
  } else if (t === "bryter") {
    const cur = tr.dataset.rolle || "";
    extraCell.innerHTML =
      `<select class="f-rolle" title="signalstopp: alle signaler i stopp og sperret mens bryteren står på. Frigivning: frigir sentralstilte veksler i enden for lokal omlegging (togveier over dem avvises, vekselfelt-vernet er ute av funksjon). Panel-bindingen er kontrollampen — tent når funksjonen er aktiv.">` +
      opt("", "rolle: —", cur) +
      opt("signalstopp", "signalstopp", cur) +
      opt("lok-v", "frigivning venstre ende", cur) +
      opt("lok-h", "frigivning høyre ende", cur) +
      `</select>`;
  } else if (isNoenVeksel(t)) {
    // «ende» gjelder BARE den sentralstilte: den utledes av
    // togveitabellen, og manuellvekselen står ikke i noen togvei.
    // Tegnefeltene har begge — de er hele grunnen til at den
    // manuelle er definert i det hele tatt.
    const curSide = tr.dataset.side || "";
    const utl = isVeksel(t)
      ? utledetEnde(tr.querySelector(".f-id").value.trim()) : "";
    extraCell.innerHTML =
      (isVeksel(t)
        ? `<span class="hint" title="Stasjonsenden utledes av forriglingstabellen: vekselen hører til den enden hvis linjefelt togveiene over den når. Sett verdi her BARE for veksler ingen togvei berører (rene skifteveksler) eller som nås fra begge sider.">ende:</span> ` +
          `<select class="f-side">` +
          opt("", utl ? `auto (${utl === "v" ? "venstre" : "høyre"})`
                      : "auto (ukjent)", curSide) +
          opt("v", "venstre (overstyrt)", curSide) +
          opt("h", "høyre (overstyrt)", curSide) + `</select>`
        : `<span class="hint" title="Manuellvekselen står utenfor forriglingen: ingen ende, ingen togvei, ingen Lok-frigivning. Den er med for å tegne sporplanen, og kan betjenes med knapp eller bryter over nodens porter. Sikres i en togvei med samlelås eller rigel.">håndstilt — utenfor forriglingen</span>`) +
      // Sporplanens portmodell: spissen + hvor greinene fører. KUN
      // tegning — master leser ingen av feltene, så de ligger skjult
      // bak «tegning»-lenka (ikke alle vil ha et digitalt panel).
      `<br><a class="tegnvis" onclick="visTegn(this)" title="Felter som KUN styrer tegningen av sporplanen — masteren leser dem ikke. Trengs ikke uten digitalt panel.">tegning ▸</a>` +
      `<span class="tegnfelt" hidden> ` +
      `<span class="hint" title="Sporplanens portmodell — bare for tegningen, masteren leser det ikke. Spiss: enden tungespissen peker mot. +→/−→: sporet eller vekselen pluss-/minusgreina fører til (skriv «veksel 5» når den går rett i en annen veksel). st→: der stammen går videre i en kjede. Tomt = utledes av togveitabellen der det går.">spiss:</span> ` +
      `<select class="f-spiss">` +
      opt("", "—", tr.dataset.spiss) +
      opt("v", "venstre", tr.dataset.spiss) +
      opt("h", "høyre", tr.dataset.spiss) + `</select>` +
      ` <span class="hint">+→</span><select class="f-plusstil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.plusstil, tr.dataset.plusstil || "—",
          tr.dataset.plusstil) + `</select>` +
      ` <span class="hint">−→</span><select class="f-minustil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.minustil, tr.dataset.minustil || "—",
          tr.dataset.minustil) + `</select>` +
      ` <span class="hint">st→</span><select class="f-spisstil" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.spisstil, tr.dataset.spisstil || "—",
          tr.dataset.spisstil) + `</select>` +
      ` <span class="hint" title="Hvilket ben som er det FYSISK krumme (tegningen kan ikke utlede det): standard er at minusgreina bøyer av og fortsetter utover; «stammen» betyr at pluss- og minusgreina ligger i linje og stammen bøyer av — som veksel 11, der 6 og 3 ligger rett gjennom og det krumme benet går ned mot veksel 4.">krumt:</span>` +
      `<select class="f-avvikben">` +
      opt("", "minus (std)", tr.dataset.avvikben) +
      opt("spiss", "stammen", tr.dataset.avvikben) +
      opt("pluss", "pluss", tr.dataset.avvikben) + `</select></span>`;
  } else if (isLaas(t)) {
    const navn = tr.dataset.navn || "";
    const laasTip = t === "samlelaas"
      ? "Objektene nøkkelen låser (kontrollås/samlelås): så lenge låsen er SPERRET (nøkkelen står i kontroll) avvises all omlegging av disse — stiller, trykknapp og MQTT. Frigitt lås eller nøkkel ute sperrer til gjengjeld togveiene i virkeområdet (tosidig forrigling)."
      : "Objektene rigelen låser direkte (veksler og sporsperrer): sperret rigel avviser all omlegging, og togveiene i virkeområdet krever rigelen sperret. Tilbaketaking gir 10 s etterløp og fullføres først når alle objektene ligger i normal igjen (motordrevne modellobjekter rekker tilbake). Som i forbildet forholder anlegget seg bare til NØKLENES/rigelens status — stillingssensorer på låste objekter trengs ikke.";
    extraCell.innerHTML =
      `<span class="hint">navn:</span> ` +
      `<input class="f-navn" style="max-width:90px" value="${attr(navn)}" ` +
      `placeholder="${t === "samlelaas" ? "S.LÅS I" : "Ri. Sp.II/3"}" ` +
      `title="Visningsnavn med forbildets skrivemåte — vises i panelet og UI-et. Selve litraen (${t === "samlelaas" ? "S1" : "RI1"}) brukes i MQTT-temaene."><br>` +
      `<span class="hint" title="${laasTip}">omfatter:</span><br>` +
      skiftVekselBoks(tr, true) + `<br>` +
      `<span class="hint">+ utenfor anlegget:</span> ` +
      `<input class="f-omfrit" style="max-width:110px" ` +
      `value="${attr(utenforAnlegget(tr).join(", "))}" ` +
      `placeholder="f.eks. V12" ` +
      `title="Objekter låsen omfatter som IKKE er definert i anlegget: helt manuelle veksler/sperrer, eller slike som drives elektrisk av eget utstyr utenfor systemet. Anlegget ser da bare låsen — at objektene ligger riktig før sperring er operatørens ansvar, som med kontrollåsnøklene i forbildet. Kommaseparert liste; vises i panelet."><br>` +
      `<span class="hint" title="Avgrens togvei-kravet til togveier til/fra bestemte linjefelt (maks 2) — apparatnøkkel-varianten (Sokna: nøkkelen i apparatet sperret bare togveiene til/fra A). TOMT = hele stasjonen, som er forbildets hovedregel.">sperrer:</span> ` +
      sperrerBoks(tr);
  } else if (isSperre(t)) {
    extraCell.innerHTML =
      `<span class="hint" title="Sporsperre: normalstillingen er PÅLAGT — det er dekningen togveiene krever. Deler vekselmaskineriet: valgfrie drivutganger for motordrevet modellsperre, valgfrie sensorer (pålagt-kontroll — uten dem antas stillingen), lokal stiller. Omlegging gates av samlelås/rigel som eier sperren. Symbol på planen: skråstrek over sporet.">normalstilling pålagt (dekning)</span>` +
      `<br><a class="tegnvis" onclick="visTegn(this)" title="Felter som KUN styrer tegningen av sporplanen — masteren leser dem ikke. Trengs ikke uten digitalt panel.">tegning ▸</a>` +
      `<span class="tegnfelt" hidden> ` +
      `<span class="hint" title="Sporplanen: sporet eller forbindelsen skråstreken tegnes på — et sporfelt-litra, eller «veksel N» når sperren ligger på forbindelsen fra den vekselens stamme. Kun tegning; masteren leser det ikke.">ligger i:</span> ` +
      `<select class="f-liggeri" onfocus="fillTopoSel(this)">` +
      opt(tr.dataset.liggeri, tr.dataset.liggeri || "—",
          tr.dataset.liggeri) + `</select></span>`;
  } else if (t === "sporfelt") {
    const cur = tr.dataset.rolle || "";
    const curSide = tr.dataset.side || "";
    extraCell.innerHTML =
      `<select class="f-rolle" onchange="rolleChanged(this)" title="togspor = stasjonsspor der tog står; linjefelt = sporet mot en tilstøtende linje; varselfelt = kort felt ute på linjen utenfor forsignalet — varselklokken ringer for tog i anmarsj. La stå tom for interne felt som sporvekselfelt.">` +
      opt("", "rolle: —", cur) + opt("togspor", "togspor", cur) +
      opt("linjefelt", "linjefelt", cur) +
      opt("varselfelt", "varselfelt", cur) +
      opt("spor", "spor (utenfor anlegget)", cur) +
      `</select> ` +
      (cur === "varselfelt" ? `` :
       `<button class="mini" onclick="addSubRow(this.closest('tr'),'sensor',null,true)">+ sensor</button>`) +
      (cur === "linjefelt"
        ? `<br><span class="hint">ende:</span> ` +
          `<select class="f-side" title="Hvilken stasjonsende linjefeltet ligger i — togveistillerne bruker dette til å skille innkjør (dytt inn mot stasjonen) fra utkjør (dytt ut mot linjen)">` +
          opt("", "—", curSide) + opt("v", "venstre", curSide) +
          opt("h", "høyre", curSide) + `</select>` +
          `<br><label class="hint" title="Har strekningen linjeblokk? UTEN linjeblokk finnes ingen automatisk kontroll av at hele toget er kommet inn: innkjørtogveien blir stående låst til txp har foretatt sistevognskontroll og kvittert med den sorte trykknappen ved varselfeltet. Togveislampen blinker mens den venter. Flagget hører til det enkelte linjefeltet — en stasjon kan ha linjeblokk mot én nabo og manuell togmelding mot en annen.">` +
          `<input type="checkbox" class="f-lblokk"${tr.dataset.lblokk === "0" ? "" : " checked"}> linjeblokk</label>`
        : cur === "varselfelt"
        ? `<br><span class="hint">linjefelt:</span> ` +
          `<select class="f-linje" title="Linjefeltet varselfeltet er koblet til — varslet gjelder den siden (siden arves fra linjefeltet)" onfocus="fillLinjeSel(this)">` +
          opt(tr.dataset.linje || "", tr.dataset.linje || "—",
              tr.dataset.linje || "") + `</select>`
        : ``);
  } else {
    extraCell.textContent = "";
  }
  for (const c of ["p-node","p-i2c","p-port"])
    tr.querySelector("." + c).disabled = !panelOk(t);
  // Meldefelt: hovedradens generiske sensorbinding brukes ikke —
  // sensor-ytre/sensor-indre ER sensorene. Deaktiver og tøm.
  const mfelt = t === "sporfelt" &&
                (tr.dataset.rolle || "") === "varselfelt";
  for (const c of ["a-node","a-i2c","a-port"]) {
    const e2 = tr.querySelector("." + c);
    e2.disabled = mfelt;
    if (mfelt && c === "a-node") e2.value = "";
  }
}
function addRow(f, foerEl) {
  f = f || {id:"", type:"hovedsignal3", bindinger:[], notes:""};
  const t = f.type, binds = f.bindinger || [];
  const r = roller(t);
  // Hovedradens binding: eksakt sted, ellers et legacy-sted som ikke
  // hører hjemme i noen underrad (gamle konfiger uten sted-felt)
  const subSteder = ["panel","ut-avvik","sensor-normal","sensor-avvik",
                     "panel-normal","panel-avvik","stiller",
                     "stiller-v","stiller-h","kvittering",
                     "sensor-ytre","sensor-indre","togveislampe",
                     "lokalstillerlampe",
                     "middelkontrollampe"];   // «middelkontrollampe» manglet:
  // uten den i lista plukket fallbacken under middel-bindingen som
  // HOVEDRADENS binding, og signalets egen lampeadresse ble overskrevet
  // av middellampens ved neste lagring.
  const main = binds.find(b => b.sted === r[0]) ||
               binds.find(b => !subSteder.includes(b.sted)) || {};
  const panel = binds.find(b => b.sted === "panel") || {};
  const tr = document.createElement("tr");
  tr.className = "fnrow";
  tr.dataset.orgId = f.id || "";   // original-litra: omdøping spores
  tr.dataset.montert = f.montert_med || "";
  tr.dataset.varsler = f.varsler_om || "";
  tr.dataset.rolle = f.rolle || "";
  tr.dataset.side = f.side || "";
  // linjeblokk: standard PÅ (dagens oppførsel). Bare eksplisitt
  // false gir "0" — mangler feltet, er strekningen blokkstyrt.
  tr.dataset.lblokk = (f.linjeblokk === false) ? "0" : "1";
  tr.dataset.linje = f.linjefelt || "";
  tr.dataset.utslag = (f.utslag !== undefined) ? String(f.utslag) : "";
  tr.dataset.hakk = (f.hakk_hz !== undefined) ? String(f.hakk_hz) : "";
  tr.dataset.duty = (f.hakk_duty !== undefined) ? String(f.hakk_duty) : "";
  // Samlelåsens «omfatter» gjenbruker skiftv-sporet (samme form, og
  // et objekt er aldri både skiftesignal og samlelås); «sperrer» og
  // «navn» er samlelåsens egne.
  tr.dataset.skiftv = JSON.stringify(f.skift_sporveksler ||
                                     f.omfatter || []);
  tr.dataset.sperrer = JSON.stringify(f.sperrer || []);
  tr.dataset.navn = f.navn || "";
  // Sporplan-topologien (kun tegning; master ignorerer feltene)
  tr.dataset.spiss = f.spiss || "";
  tr.dataset.plusstil = f.pluss_til || "";
  tr.dataset.minustil = f.minus_til || "";
  tr.dataset.spisstil = f.spiss_til || "";
  tr.dataset.avvikben = f.avvik_ben || "";
  tr.dataset.liggeri = f.ligger_i || "";
  tr.innerHTML = `
    <td><input class="f-id" value="${attr(f.id)}" placeholder="A"></td>
    <td><select class="f-type" onchange="typeChanged(this)">
        ${(GRUPPER[gruppeIdx(t)].typer.includes(t)
           ? GRUPPER[gruppeIdx(t)].typer
           : [t].concat(GRUPPER[gruppeIdx(t)].typer))
          .map(x=>opt(x,x,t)).join("")}</select></td>
    <td class="hint f-extra"></td>
    ${bindCells("a", main, defaultI2c(r[0]))}
    ${bindCells("p", panel, "0x40")}
    <td><input class="f-notes" value="${attr(f.notes)}"></td>
    <td><button class="row-del" onclick="delFn(this)">✕</button></td>`;
  const tb = document.querySelector("#tbl tbody");
  if (foerEl) tb.insertBefore(tr, foerEl);
  else tb.appendChild(tr);
  // Faste underrader (veksel) med lagrede verdier
  byggSubrader(tr, t, binds);
  // Ekstra sensorer for sporfelt (utover hovedradens)
  if (t === "sporfelt")
    binds.filter(b => b.sted === "sensor" && b !== main)
         .forEach(b => addSubRow(tr, "sensor", b, true));
  decorateRow(tr);
  return tr;
}
// ---- gruppeoverskrifter i HAL-tabellen ----
function grpHeaderRow(gi) {
  const tr = document.createElement("tr");
  tr.className = "grphead";
  tr.dataset.grp = gi;
  tr.innerHTML = `<td colspan="11">
    <span style="cursor:pointer" onclick="grpToggle(${gi})">
      <span class="grp-pil">▾</span> <b>${GRUPPER[gi].navn}</b>
      <span class="hint grp-tall"></span></span>
    <button class="mini" style="margin-left:10px"
            onclick="grpAdd(${gi})">+ ny</button></td>`;
  return tr;
}
function grpHeader(gi) {
  return document.querySelector('#tbl tbody tr.grphead[data-grp="' + gi + '"]');
}
function grpAdd(gi) {
  COLLAPSED.delete(gi);                     // vis gruppen det legges til i
  addRow({id:"", type: GRUPPER[gi].typer[0], bindinger:[], notes:""},
         grpHeader(gi + 1));                // null = nederst (siste gruppe)
  grpOppdater();
}
function grpToggle(gi) {
  COLLAPSED.has(gi) ? COLLAPSED.delete(gi) : COLLAPSED.add(gi);
  grpOppdater();
}
// Filter på Objekter-fanen: en hovedrad matcher hvis litra, type
// eller et bundet nodenavn inneholder søkestrengen; underradene
// følger hovedraden sin. Tomt felt viser alt. Selve vis/skjul eies
// av grpOppdater (som også håndterer sammenlagte grupper) — filteret
// er bare et ekstra kriterium der.
let HALFILTER = "";
function halFilter(q) {
  HALFILTER = (q || "").trim().toLowerCase();
  grpOppdater();
}
function grpOppdater() {   // vis/skjul etter sammenlegging + tell rader
  let gi = -1;
  const tall = {};
  let radMatch = true;   // gjelder hovedraden OG underradene dens
  for (const tr of document.querySelectorAll("#tbl tbody tr")) {
    if (tr.classList.contains("grphead")) {
      gi = parseInt(tr.dataset.grp);
      tr.querySelector(".grp-pil").textContent =
        COLLAPSED.has(gi) ? "▸" : "▾";
      continue;
    }
    if (tr.classList.contains("fnrow")) {
      tall[gi] = (tall[gi] || 0) + 1;
      radMatch = !HALFILTER ||
        [...tr.querySelectorAll("input,select")]
          .map(e => (e.value || "")).join(" ").toLowerCase()
          .includes(HALFILTER);
    }
    tr.style.display = (COLLAPSED.has(gi) || !radMatch) ? "none" : "";
  }
  GRUPPER.forEach((g, i) => {
    const h = grpHeader(i);
    if (h) h.querySelector(".grp-tall").textContent = "(" + (tall[i] || 0) + ")";
  });
}

// Tegnefeltene (sporplanens portmodell m.m.) gjelder KUN tegningen av
// planen — masteren leser dem ikke, og ikke alle vil ha et digitalt
// panel. De ligger derfor skjult bak en «tegning»-lenke. Feltene står
// i DOM-en hele tiden, så collect() leser dem uansett.
function visTegn(a) {
  const sp = a.nextElementSibling;
  sp.hidden = !sp.hidden;
  a.textContent = sp.hidden ? "tegning ▸" : "tegning ▾";
}

function rolleChanged(sel) {   // sporfelt-rolle: vis/skjul tilleggsvalg
  const tr = sel.closest("tr");
  tr.dataset.rolle = sel.value;
  const side = tr.querySelector(".f-side");
  tr.dataset.side = side ? side.value : (tr.dataset.side || "");
  const lin = tr.querySelector(".f-linje");
  tr.dataset.linje = lin ? lin.value : (tr.dataset.linje || "");
  // Avkryssingen tegnes på nytt fra datasettet, så en ulagret
  // endring må speiles hit først — ellers spretter den tilbake
  // hver gang rollen endres.
  const lb = tr.querySelector(".f-lblokk");
  if (lb) tr.dataset.lblokk = lb.checked ? "1" : "0";
  // rollespesifikke underrader bygges på nytt (sensor-radene beholdes)
  let n = tr.nextElementSibling;
  while (n && n.classList.contains("subrow")) {
    const neste = n.nextElementSibling;
    if (n.dataset.sted !== "sensor") n.remove();
    n = neste;
  }
  byggSubrader(tr, "sporfelt", []);
  decorateRow(tr);
}
// Speiler masterens utledning i UI-et: vekselen hører til den enden
// hvis linjefelt togveiene over den når. TOGVEIER er tabellen slik
// den ble lastet — utledningen viser altså LAGRET tilstand, ikke
// ulagrede endringer i Forrigling-fanen.
function utledetEnde(vLitra) {
  if (!vLitra) return "";
  const side = {};   // linjefelt-litra -> v/h fra Objekter-tabellen
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (tr.querySelector(".f-type").value !== "sporfelt") continue;
    const r = tr.querySelector(".f-rolle");
    if (!r || r.value !== "linjefelt") continue;
    const s = tr.querySelector(".f-side");
    const id = tr.querySelector(".f-id").value.trim();
    if (id && s && s.value) side[id] = s.value;
  }
  let v = false, h = false;
  for (const tv of (TOGVEIER || [])) {
    if (!(tv.sporveksler || []).some(x => x.sporveksel === vLitra)) continue;
    for (const f of (tv.frie || [])) {
      if (side[f] === "v") v = true;
      else if (side[f] === "h") h = true;
    }
  }
  return (v && !h) ? "v" : (h && !v) ? "h" : "";
}
function fillLinjeSel(sel) {   // nedtrekk over linjefelt-litraer
  const cur = sel.value;
  let out = `<option value="">—</option>`;
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (tr.querySelector(".f-type").value !== "sporfelt") continue;
    const r = tr.querySelector(".f-rolle");
    if (!r || r.value !== "linjefelt") continue;
    const id = tr.querySelector(".f-id").value.trim();
    if (id) out += opt(id, id, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, cur + " (ukjent)", cur);
  sel.innerHTML = out;
  sel.value = cur;
}
// Vekselvelger for høyt skiftesignal: avkryssing over vekslene i
// anlegget. Området er vekslene signalet GJELDER FOR (A-sirk. 3) —
// stasjonsenden følger med gjennom vekselens utledede ende, så
// skiltet trenger ingen egen venstre/høyre.
function skiftVekselBoks(tr, gruppe) {
  // To ulike utvalg, av samme grunn som i forbildet:
  //
  //   gruppe=false — HØYT SKIFTESIGNAL. Bare SENTRALSTILTE veksler.
  //     Signalet følger vekslene sine: det viser 41 så lenge en av dem
  //     er i bevegelse eller uten kontroll, og 42 igjen når stillingen
  //     er bekreftet. En lokalstilt veksel har ingen kontroll å gi —
  //     den blir stående V_UKJENT — så tas den med, låses signalet i
  //     41 for alltid og kommer aldri til 42.
  //
  //   gruppe=true — SAMLELÅS/RIGEL. Motsatt: det er nettopp de
  //     lokalstilte vekslene og sporsperrene låsen finnes for.
  //     Sentralstilte tas med der de inngår i låsegruppen.
  const valgt = new Set(JSON.parse(tr.dataset.skiftv || "[]"));
  const vist = new Set();
  let out = "";
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const passer = gruppe ? (isNoenVeksel(rt) || isSperre(rt))
                          : isVeksel(rt);
    if (!passer) continue;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    vist.add(id);
    out += `<label style="margin-right:8px;white-space:nowrap">` +
           `<input type="checkbox" class="f-skiftv" value="${attr(id)}" ` +
           `${valgt.has(id) ? "checked" : ""}>${id}</label>`;
  }
  // Alt som ALT er valgt, men ikke hører hjemme i utvalget over, vises
  // likevel — avkrysset og merket. Uten dette ville en konfig som
  // inneholder en lokalstilt veksel på et skiftesignal bli avvist av
  // valideringen UTEN at raden ga noen måte å fjerne den på: feilen
  // ville vært synlig og uopprettelig på samme tid.
  for (const id of valgt) {
    if (vist.has(id)) continue;
    out += `<label style="margin-right:8px;white-space:nowrap;` +
           `color:var(--warn,#e0c23c)" ` +
           `title="Hører ikke hjemme her — fjern avkryssingen. ` +
           `Enten er objektet slettet, eller det er en lokalstilt ` +
           `veksel, som et høyt skiftesignal ikke kan følge.">` +
           `<input type="checkbox" class="f-skiftv" value="${attr(id)}" ` +
           `checked>${id} ⚠</label>`;
  }
  if (out) return out;
  return `<span class="hint">${gruppe
    ? "ingen veksler eller sporsperrer definert"
    : "ingen sentralstilte veksler definert"}</span>`;
}
// Linjefelt-velger for samlelåsens sperrer-avgrensning (maks 2 —
// masterens tabellgrense). Leser rolle fra select-en når raden er
// dekorert, ellers fra datasettet (radene dekoreres i rekkefølge).
function sperrerBoks(tr) {
  const valgt = new Set(JSON.parse(tr.dataset.sperrer || "[]"));
  let out = "";
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    if (r.querySelector(".f-type").value !== "sporfelt") continue;
    const rsel = r.querySelector(".f-rolle");
    const rolle = rsel ? rsel.value : (r.dataset.rolle || "");
    if (rolle !== "linjefelt") continue;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    out += `<label style="margin-right:6px;white-space:nowrap">` +
           `<input type="checkbox" class="f-sperrer" value="${attr(id)}" ` +
           `${valgt.has(id) ? "checked" : ""}> ${id}</label>`;
  }
  return out || `<span class="hint">(ingen linjefelt = hele stasjonen)</span>`;
}
// Omfatter-litra som IKKE finnes som objekt i tabellen: objekter
// utenfor anlegget (helt manuelle / drevet av eget utstyr). De har
// intet avkryssingsvalg og vises i fritekstfeltet i stedet.
function utenforAnlegget(tr) {
  const kjent = new Set();
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    if (isNoenVeksel(rt) || isSperre(rt))
      kjent.add(r.querySelector(".f-id").value.trim());
  }
  return JSON.parse(tr.dataset.skiftv || "[]").filter(x => !kjent.has(x));
}
// Nedtrekk for sporplan-topologien: alle sporfelt + «veksel N» for
// hver sporveksel (litraene kolliderer på tvers av navnerommene, så
// vekselreferanser prefikses). Fylles ved fokus, som fillLinjeSel.
function fillTopoSel(sel) {
  const cur = sel.value;
  let out = `<option value="">—</option>`;
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    if (rt === "sporfelt") out += opt(id, id, cur);
  }
  for (const r of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const rt = r.querySelector(".f-type").value;
    const id = r.querySelector(".f-id").value.trim();
    if (!id) continue;
    if (isNoenVeksel(rt))   // begge tegnes på sporplanen
      out += opt(`veksel ${id}`, `veksel ${id}`, cur);
  }
  if (cur && !out.includes(`value="${cur}"`))
    out += opt(cur, cur + " (ukjent)", cur);
  sel.innerHTML = out;
  sel.value = cur;
}
function typeChanged(sel) {   // brukerbytte: bygg underrader på nytt
  const tr = sel.closest("tr");
  while (tr.nextElementSibling?.classList.contains("subrow"))
    tr.nextElementSibling.remove();
  byggSubrader(tr, sel.value, []);
  decorateRow(tr);
}
// Underradene per type. Veksler kompakt på tre linjer: motorutgang
// avvik, så én linje per stilling med stillingssensoren i bindings-
// kolonnene og kontrollampen i panelkolonnene (ut-normal er hovedraden).
function byggSubrader(tr, t, binds) {
  const finn = sted => (binds || []).find(b => b.sted === sted);
  // BETJENING: ett par innganger per betjeningssted, navngitt etter
  // RETNING. Begge bundet = flankestyrt (to trykknapper ELLER en
  // vippebryter). Bare én bundet = enpolet bryter, lest på nivå.
  // Ingen modus å velge — koblingen forteller selv hva den er.
  if (isVeksel(t)) {
    addSubRow(tr, "ut-avvik", finn("ut-avvik"), false,
              "stiller-normal", finn("stiller-normal"));
    addSubRow(tr, "stiller-avvik", finn("stiller-avvik"), false,
              "lokal-normal", finn("lokal-normal"));
    addSubRow(tr, "lokal-avvik", finn("lokal-avvik"), false,
              "lokalstillerlampe", finn("lokalstillerlampe"));
    addSubRow(tr, "sensor-normal", finn("sensor-normal"), false,
              "panel-normal", finn("panel-normal"));
    addSubRow(tr, "sensor-avvik", finn("sensor-avvik"), false,
              "panel-avvik", finn("panel-avvik"));
    return;
  }
  // Manuellveksel og sporsperre betjenes LOKALT, ute ved objektet —
  // de har ikke noe stillerapparat å betjenes fra. Derfor lokalparet,
  // ikke apparatparet, og ingen Lok-frigivning å skille på.
  if (isManuell(t)) {
    addSubRow(tr, "ut-avvik", finn("ut-avvik"), false,
              "lokal-normal", finn("lokal-normal"));
    addSubRow(tr, "lokal-avvik", finn("lokal-avvik"), false);
    return;
  }
  if (isSperre(t)) {
    // Sperren har sine EGNE bindingsnavn: normalstillingen er pålagt.
    // Master kjenner dem som aliaser for de samme stedene, så konfigen
    // sier det den er i stedet for å bli oversatt i etiketten.
    addSubRow(tr, "ut-avlagt", finn("ut-avlagt"), false,
              "lokal-paalagt", finn("lokal-paalagt"));
    addSubRow(tr, "lokal-avlagt", finn("lokal-avlagt"), false,
              "sensor-paalagt", finn("sensor-paalagt"));
    return;
  }
  if (isSkift(t)) {   // betjeningsbryter på apparatet
    addSubRow(tr, "stiller", finn("stiller"), false);
    // middelkontrollampen sitter på skiftesignalets mast: hvitt
    // blinklys når innkjørende tog i motsatt ende er klar av middel
    addSubRow(tr, "middelkontrollampe", finn("middelkontrollampe"), false);
    return;
  }
  if (t === "samlelaas") {
    // stiller = vedvarende frigivningsstiller; kvittering = momentan
    // trykknapp (apparatnøkkelen, selvsperrende); sensor = nøkkel-
    // kontakten (aktiv lav = nøkkelen i låsen). Hovedraden (anlegg)
    // er frigitt-lampen ved låsen, panelkolonnene kontrollampen på
    // apparatet (tent = nøkkelen i kontroll, Nelaug-regelen).
    addSubRow(tr, "stiller", finn("stiller"), false);
    addSubRow(tr, "kvittering", finn("kvittering"), false);
    addSubRow(tr, "sensor", finn("sensor"), false);
    return;
  }
  if (t === "rigel") {
    // stiller = den blå frigivningsstilleren. Hovedraden (anlegg) er
    // frigittlampen ved objektene, panelkolonnene kontrollampen —
    // objektenes egen kontroll leses fra DERES sensorer, så rigelen
    // har ingen egen sensorbinding.
    addSubRow(tr, "stiller", finn("stiller"), false);
    return;
  }
  if (t === "sporfelt") {   // rollestyrt: stillere / kvitteringsknapp
    const rolle = tr.dataset.rolle || "";
    if (rolle === "varselfelt") {
      addSubRow(tr, "kvittering", finn("kvittering"), false);
      // to sensorer gir togretning: ytre (lengst fra stasjonen)
      // først = innkommende tog -> melding; indre først = utgående
      addSubRow(tr, "sensor-ytre", finn("sensor-ytre"), false,
                "sensor-indre", finn("sensor-indre"));
    } else if (rolle === "togspor" || rolle === "linjefelt") {
      addSubRow(tr, "stiller-v", finn("stiller-v"), false,
                "stiller-h", finn("stiller-h"));
      if (rolle === "linjefelt")   // blå lampe: tent når togvei er forriglet
        addSubRow(tr, "togveislampe", finn("togveislampe"), false);
    }
    return;   // felt uten rolle (vekselfelt o.l.): ingen betjeningsrader
  }
  for (const sted of roller(t).slice(1))
    addSubRow(tr, sted, finn(sted), false);
}
function delFn(btn) {
  const tr = btn.closest("tr");
  const id = tr.querySelector(".f-id").value.trim() || "(uten litra)";
  if (!confirm(`Slette ${id} med alle bindinger?\\n\\n` +
               `(Blir permanent først ved «Lagre og publiser».)`)) return;
  while (tr.nextElementSibling?.classList.contains("subrow"))
    tr.nextElementSibling.remove();
  tr.remove();
  grpOppdater();
}
function collect() {
  const out = [];
  for (const tr of document.querySelectorAll("#tbl tbody tr")) {
    if (tr.classList.contains("grphead")) continue;
    if (tr.classList.contains("subrow")) {
      const nodeVal = tr.querySelector(".s-node").value;
      if (nodeVal) out[out.length-1]?.bindinger.push({sted: tr.dataset.sted,
        node: nodeVal,
        i2c: tr.querySelector(".s-i2c").value,
        port: parseInt(tr.querySelector(".s-port").value || "0")});
      const n2 = tr.querySelector(".t-node");   // binding nr. 2 på linjen
      if (n2 && n2.value) out[out.length-1]?.bindinger.push({
        sted: tr.dataset.sted2, node: n2.value,
        i2c: tr.querySelector(".t-i2c").value,
        port: parseInt(tr.querySelector(".t-port").value || "0")});
      continue;
    }
    const t = tr.querySelector(".f-type").value;
    const binds = [];
    const mainNode = tr.querySelector(".a-node").value;
    if (mainNode) binds.push({sted: roller(t)[0],
      node: mainNode,
      i2c: tr.querySelector(".a-i2c").value,
      port: parseInt(tr.querySelector(".a-port").value || "0")});
    if (!tr.querySelector(".p-node").disabled && tr.querySelector(".p-node").value) {
      binds.push({sted:"panel",
        node: tr.querySelector(".p-node").value,
        i2c: tr.querySelector(".p-i2c").value,
        port: parseInt(tr.querySelector(".p-port").value || "0")});
    }
    const fn = {id: tr.querySelector(".f-id").value.trim(), type: t,
                bindinger: binds,
                notes: tr.querySelector(".f-notes").value.trim()};
    if (tr.dataset.orgId && tr.dataset.orgId !== fn.id)
      fn.gammel_id = tr.dataset.orgId;   // referansene skrives om
    const montert = tr.querySelector(".f-montert");
    if (montert && montert.value) fn.montert_med = montert.value;
    const varsler = tr.querySelector(".f-varsler");
    if (varsler && varsler.value) fn.varsler_om = varsler.value;
    const rolle = tr.querySelector(".f-rolle");
    if (rolle) fn.rolle = rolle.value;
    const side = tr.querySelector(".f-side");
    if (side && side.value) fn.side = side.value;
    // Skriv linjeblokk bare når den er AV: true er standarden, og en
    // konfig full av "linjeblokk": true er bare støy. Er avkryssingen
    // ikke tegnet (raden er ikke dekorert som linjefelt), faller vi
    // tilbake på det som ble lastet — samme prinsipp som skift_sporveksler.
    const lb = tr.querySelector(".f-lblokk");
    if (lb) { if (!lb.checked) fn.linjeblokk = false; }
    else if (tr.dataset.lblokk === "0" &&
             (rolle ? rolle.value : "") === "linjefelt") fn.linjeblokk = false;
    const lin = tr.querySelector(".f-linje");
    if (lin && lin.value) fn.linjefelt = lin.value;
    const us = tr.querySelector(".f-utslag");
    if (us) fn.utslag = Math.max(0, Math.min(100,
        parseInt(us.value || "100") || 0));
    const hk = tr.querySelector(".f-hakk");
    if (hk) fn.hakk_hz = Math.max(10, Math.min(250,
        parseInt(hk.value || "50") || 50));
    const du = tr.querySelector(".f-duty");
    if (du) fn.hakk_duty = Math.max(10, Math.min(90,
        parseInt(du.value || "50") || 50));
    // Vekselvelgeren finnes bare på skiftesignalrader som ER dekorert.
    // Er boksene der, er de fasiten (også når ingen er huket av — da
    // har brukeren fjernet området med vilje). Er de IKKE der, faller
    // vi tilbake på det som ble lastet: en rad som av en eller annen
    // grunn ikke rakk å bli dekorert skal ALDRI slette området i
    // stillhet. Det var nettopp slik skift_sporveksler forsvant.
    if (isLaas(t) && tr.querySelector(".f-navn")) {
      // Dekorert låserad: avkryssingene (objekter i anlegget) +
      // fritekstfeltet (objekter utenfor anlegget) ER fasiten —
      // også når begge er tomme (området fjernet med vilje).
      const valgte = [...tr.querySelectorAll(".f-skiftv:checked")]
                   .map(c => c.value);
      const frit = tr.querySelector(".f-omfrit");
      if (frit) for (const x of frit.value.split(/[,\\s]+/)) {
        const v = x.trim();
        if (v && !valgte.includes(v)) valgte.push(v);
      }
      fn.omfatter = valgte;
    } else if (tr.querySelector(".f-skiftv")) {
      fn.skift_sporveksler = [...tr.querySelectorAll(".f-skiftv:checked")]
                           .map(c => c.value);
    } else {
      const lagret = JSON.parse(tr.dataset.skiftv || "[]");
      if (lagret.length) {
        if (isLaas(t)) fn.omfatter = lagret;
        else fn.skift_sporveksler = lagret;
      }
    }
    // Sporplan-topologien (portmodellen) — dekorert rad er fasit,
    // udekoreret faller tilbake på det som ble lastet
    for (const [kl, felt, ds] of [["f-spiss","spiss","spiss"],
                                  ["f-plusstil","pluss_til","plusstil"],
                                  ["f-minustil","minus_til","minustil"],
                                  ["f-spisstil","spiss_til","spisstil"],
                                  ["f-avvikben","avvik_ben","avvikben"],
                                  ["f-liggeri","ligger_i","liggeri"]]) {
      const e2 = tr.querySelector("." + kl);
      const v2 = e2 ? e2.value : tr.dataset[ds];
      if (v2) fn[felt] = v2;
    }
    // Låsegruppenes navn og sperrer-avgrensning — samme fall-tilbake-
    // prinsipp: en udekoreret rad skal aldri slette verdier i stillhet
    const nv = tr.querySelector(".f-navn");
    if (nv) { if (nv.value.trim()) fn.navn = nv.value.trim(); }
    else if (tr.dataset.navn) fn.navn = tr.dataset.navn;
    if (tr.querySelector(".f-sperrer") ||
        (isLaas(t) && tr.querySelector(".f-navn"))) {
      const sp = [...tr.querySelectorAll(".f-sperrer:checked")]
               .map(c => c.value);
      if (sp.length) fn.sperrer = sp;
    } else {
      const lagretSp = JSON.parse(tr.dataset.sperrer || "[]");
      if (lagretSp.length) fn.sperrer = lagretSp;
    }
    out.push(fn);
  }
  return out;
}
// Trygg JSON-lesing av API-svar: servertrøbbel (500/HTML i stedet for
// JSON) skal gi en LESBAR feilmelding i UI-et — aldri en stille krasj
// i r.json() som gjør at «ingenting skjer» ved lagring
async function apiJson(r) {
  try { return await r.json(); }
  catch (e) {
    return {error: `Serverfeil ${r.status} — sjekk ` +
                   `«journalctl -u nsi63-hal» på Pi-en`};
  }
}
async function save() {
  const msg = document.getElementById("msg");
  const r = await fetch("/api/hal", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({functions: collect()})});
  const j = await apiJson(r);
  if (r.ok) { msg.textContent = "Lagret og publisert " + j.version +
                (j.omdopt ? ` · ${j.omdopt} litra omdøpt, ` +
                            `${j.referanser} referanser fulgte med` : ``);
              msg.className = "ok";
              if (j.omdopt) await loadAll();   // orgId-sporene friskes
              pollAck(j.version); }
  else { msg.textContent = j.error; msg.className = "err"; }
}
async function restoreBackup(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (!confirm(`Gjenopprette hele konfigurasjonen fra «${file.name}»?\\n\\n` +
               `Dagens konfig overskrives (last den ned først hvis du er ` +
               `usikker), og den gjenopprettede publiseres til master.`)) return;
  const fd = new FormData();
  fd.append("file", file);
  const msg = document.getElementById("msg");
  const r = await fetch("/api/restore", {method: "POST", body: fd});
  const j = await apiJson(r);
  if (!r.ok) { msg.textContent = j.error;
               msg.className = "err"; return; }
  const oppsummering = `Gjenopprettet ${j.functions} funksjoner` +
    (j.togveier != null ? ` + ${j.togveier} togveier` : "") +
    ` — publisert ` + j.version +
    (j.anlegg_i_backup ? ` · backup fra anlegg ${j.anlegg_i_backup} ` +
      `(anleggs-ID endres kun på ANLEGG-kortet)` : ``);
  toast(oppsummering);
  msg.textContent = oppsummering;
  msg.className = "ok";
  await loadAll();
  pollAck(j.version);
}
async function pollAck(version) {
  const msg = document.getElementById("msg");
  for (let i = 0; i < 10; i++) {
    await new Promise(res => setTimeout(res, 1000));
    const j = await (await fetch("/api/ack")).json();
    if (j.version === version) {
      msg.textContent =
        `Lagret — master kvitterte ${version} (${j.functions} funksjoner)`;
      return;
    }
  }
  msg.textContent += " — venter fortsatt på master-kvittering";
}
async function loadAll() {
  fetch("/api/anlegg").then(r => r.json())
    .then(a => {
      settTittel(a.id);
      STATUS.anlegg = a.id || "";
      oppdaterStatus();
    }).catch(() => {});
  const nodes = await (await fetch("/api/nodes")).json();
  liveNodes = nodes.nodes || [];
  const hal = await (await fetch("/api/hal")).json();
  SIGNALTYPER = hal.signaltyper || {};
  NODER = hal.noder || {};
  STATUS.hal = hal.version;
  STATUS.noder = liveNodes.filter(n => n.online).length;
  // Togveiene hentes også her (ikke bare i Forrigling-fanen): vekselens
  // stasjonsende utledes av dem, og vekselradene tegnes rett under.
  try {
    const fr = await (await fetch("/api/forrigling")).json();
    TOGVEIER = fr.togveier || [];
    STATUS.fr = fr.version || "";
    STATUS.frAntall = TOGVEIER.length;
  } catch (e) { /* forrigling ikke lagret ennå: ende blir «ukjent» */ }
  oppdaterStatus();
  const tb = document.querySelector("#tbl tbody");
  tb.innerHTML = "";
  // Gruppert etter type (forriglingsobjektene først), alfabetisk på
  // litra innenfor gruppen (naturlig tallsortering: A2 før A10)
  const fns = (hal.functions || []).slice()
    .sort((a, b) => (a.id || "").localeCompare(b.id || "", "no",
                                               {numeric: true}));
  GRUPPER.forEach((g, gi) => {
    tb.appendChild(grpHeaderRow(gi));
    fns.filter(f => gruppeIdx(f.type) === gi).forEach(f => addRow(f));
  });
  // ANDRE RUNDE over radene som er avhengige av ANDRE rader.
  // addRow dekorerer inline, og gruppene tegnes i rekkefølge — så da
  // skiftesignalene (gruppe «Signaler») ble dekorert, fantes ikke
  // vekselradene (gruppe «Veksler») ennå. Vekselvelgeren ble tom,
  // collect() fant ingen avkryssinger, og skift_sporveksler ble SLETTET
  // ved neste lagring. Samme gjaldt vekselens utledede ende, som
  // leser linjefeltenes side fra sporfelt-gruppen lenger ned.
  for (const tr of document.querySelectorAll("#tbl tbody tr.fnrow")) {
    const t = tr.querySelector(".f-type").value;
    if (isSkift(t) || isNoenVeksel(t) || isSperre(t)) decorateRow(tr);
  }
  grpOppdater();
}
// ---------- Noder-fanen: full oversikt over noder og porter ----------
let currentView = "noder";   // «System»-fanen er landingssiden

// Statuslinjen oppe til høyre: alle tre lagrede konfigurasjonene
// (anlegg, objekter, forrigling) + nodetelling — alltid synlig,
// uavhengig av fane. Oppdateres av loadAll/frLoad/3s-intervallet.
const STATUS = {anlegg: "", hal: "", fr: "", frAntall: null, noder: 0};
function oppdaterStatus() {
  const d = [];
  if (STATUS.anlegg) d.push(`anlegg ${STATUS.anlegg}`);
  if (STATUS.hal) d.push(`objekter ${STATUS.hal}`);
  if (STATUS.fr) d.push(`forrigling ${STATUS.fr}` +
    (STATUS.frAntall != null ? ` (${STATUS.frAntall} togveier)` : ``));
  d.push(`${STATUS.noder} ${STATUS.noder === 1 ? "node" : "noder"} online`);
  document.getElementById("status").textContent = d.join(" · ");
}
function showView(v, btn) {
  currentView = v;
  for (const name of ["hal", "forrigling", "noder"])
    document.getElementById("view-" + name).style.display =
      v === name ? "" : "none";
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  if (v === "noder") renderNoder();
  if (v === "forrigling") frLoad();
}
// litra-etikett per (mac, i2c-adresse, port) fra HAL-tabellen
// GPIO-porter bundet som INNGANG på en gitt node — speiler masterens
// erInngangsBinding: sensor*/stiller*/kvittering, PLUSS "anlegg" på
// inngangstypene (trykknapp/bryter/inngang leses via anlegg-bindingen)
const INNGANGSTYPER = new Set(["trykknapp", "bryter", "inngang"]);
function erInnBinding(ftype, sted) {
  return sted.startsWith("sensor") || sted.startsWith("stiller") ||
         sted === "kvittering" ||
         (sted === "anlegg" && INNGANGSTYPER.has(ftype));
}
function gpioInnPorter(hal, mac) {
  const inn = new Set();
  for (const f of hal.functions || [])
    for (const b of f.bindinger || []) {
      const bmac = (NODER[b.node] && NODER[b.node].mac) || b.node;
      if (bmac === mac && b.i2c === "gpio" && erInnBinding(f.type, b.sted))
        inn.add(Number(b.port));
    }
  return inn;
}
function portLabels(hal, mac, addr) {
  const lbl = {};
  for (const f of hal.functions || []) {
    for (const b of f.bindinger || []) {
      const bmac = (NODER[b.node] && NODER[b.node].mac) || b.node;
      if (bmac !== mac || b.i2c !== addr) continue;
      const sig = SIGNALTYPER[f.type];
      if (sig && (b.sted === "anlegg" || b.sted === "panel")) {
        for (let k = 0; k < sig.lamper; k++)
          lbl[b.port + k] = `${f.id} (${b.sted}, lampe ${k + 1})`;
      } else {
        lbl[b.port] = `${f.id} (${b.sted})`;
      }
    }
  }
  return lbl;
}
function fmtSek(s) {
  if (s == null) return "?";
  const d = Math.floor(s / 86400), t = Math.floor(s % 86400 / 3600),
        m = Math.floor(s % 3600 / 60);
  if (d) return d + "d " + t + "t";
  if (t) return t + "t " + m + "m";
  return m + "m";
}
async function renderNoder() {
  const [nodes, hal, inputs, master, lt, pi, an, ota] = await Promise.all([
    (await fetch("/api/nodes")).json(),
    (await fetch("/api/hal")).json(),
    (await fetch("/api/inputs")).json(),
    (await fetch("/api/master")).json(),
    (await fetch("/api/lamptest")).json(),
    (await fetch("/api/pi")).json(),
    (await fetch("/api/anlegg")).json(),
    (await fetch("/api/ota")).json(),
  ]);
  SIGNALTYPER = hal.signaltyper || SIGNALTYPER;
  NODER = hal.noder || {};
  const sec = document.getElementById("view-noder");
  let html = "";

  if (master.conflict) {
    html += `<div class="card" style="border-color:var(--warn)">
      <h2><span class="off">⚠ TO MASTERE AKTIVE</span></h2>
      <p>«${master.conflict.self}» og «${master.conflict.other}» publiserer
      samtidig. Skru av den ene umiddelbart — nodene låser seg til én,
      men MQTT-bildet er upålitelig så lenge begge kjører.</p></div>`;
  }

  // Anleggs-ID: skiller to anlegg på samme radiokanal (FREMO-treff)
  {
    const ack = an.ack || {};
    const mFersk = master.status === "online" &&
                   master.sist_hort_s != null && master.sist_hort_s < 35;
    const bekreftet = mFersk && ack.id === an.id;
    let st = "";
    if (an.id && bekreftet)
      st = `<span class="on">master kjører med ${ack.id}</span>`;
    else if (mFersk && an.id)
      st = `<span class="off">master har ikke bekreftet — kjører den
            firmware uten anleggsstøtte?</span>`;
    else if (!mFersk)
      st = `master er offline — bekreftes når den kobler seg til`;
    html += `<div class="card"><h2>ANLEGG ` +
      (an.id ? `<span class="on">${an.id}</span>`
             : `<span class="hint">ikke satt</span>`) + `</h2>
      <div class="bar" style="margin:8px 0 4px;flex-wrap:wrap">
        <input style="width:70px;flex:0 0 auto;text-transform:uppercase"
               id="anlegg-id" maxlength="3" value="${attr(an.id)}"
               placeholder="SKN" title="Anleggs-ID: tre store bokstaver">
        <input type="checkbox" id="anlegg-adopter"
               style="width:auto;flex:0 0 auto;margin:0"
               ${an.adopter ? "checked" : ""}>
        <label for="anlegg-adopter" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="PÅ: uparede noder adopteres ved første kontakt. Skru AV på treff.">
          adopter nye noder</label>
        <input type="number" id="anlegg-hjelp" min="0" max="300"
               style="width:64px;flex:0 0 auto;margin:0 0 0 10px"
               value="${an.hjelpeutlosning_s}">
        <label for="anlegg-hjelp" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Hjelpeutløsningens tidsrelé i sekunder. Etter trinn 2 (stillerne FRA hverandre) blir togveien stående låst til tiden er ute, med blinkende togveislampe. Forbildet har ca. 90 s. 0 = av, altså momentan utløsning — praktisk under idriftsettelse, men sett den tilbake før anlegget tas i bruk.">
          s hjelpeutløsning</label>
        <input type="checkbox" id="anlegg-dekning"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.dekningsstilling ? "checked" : ""}>
        <label for="anlegg-dekning" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Dekningsstilling: når en innkjørtogvei sikres, legges krysningsvekselen i motsatt ende VEKK fra togveiens spor — «pulses, men låses ikke» — som flankebeskyttelse mot utilsiktet materiellbevegelse. Vekselen låses aldri og kan legges om igjen. Hopper stille over hvis vekselen er låst, frigitt lokalt, belagt eller dekket av skifting.">
          dekningsstilling</label>
        <input type="checkbox" id="anlegg-fjern"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.fjernstyrt ? "checked" : ""}>
        <label for="anlegg-fjern" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer"
               title="Er stasjonen fjernstyrt? Foreløpig ren DOKUMENTASJON — ingenting i forriglingen leser flagget. Det avgjør hvilke varianter som er riktige: fjernstyrt anlegg har høyt skiftesignal med bare signal 42 (skiftesignal1) og middelkontrollampe; uten fjernstyring har det begge lamperekkene (skiftesignal2), og togekspeditøren gjør middelkontrollen selv med sistevognskontroll. Selve sistevognskontrollen styres av «linjeblokk» på hvert linjefelt, ikke av dette flagget.">
          fjernstyrt</label>
        <input type="checkbox" id="anlegg-test"
               style="width:auto;flex:0 0 auto;margin:0 0 0 10px"
               ${an.testmodus ? "checked" : ""}>
        <label for="anlegg-test" class="hint"
               style="white-space:nowrap;flex:0 0 auto;cursor:pointer;color:#e0b050"
               title="TESTMODUS: MQTT-kommandoer på nsi63/<klasse>/<litra>/set og nsi63/sporveksel/<id>/set omgår signalstopp, oppstartsperre, vekselfelt-vernet, togvei-låsen og skiftesignalets område. Stillerapparatet er ALDRI omgått, og sikring av togvei kontrolleres alltid. Skru AV før anlegget settes i drift.">
          testmodus</label>
        <button class="mini" style="flex:0 0 auto"
                onclick="saveAnlegg()">Lagre</button>
        <span class="hint" style="flex:1 1 220px">${st}</span>
      </div>
      <p class="hint">Tre store bokstaver — jernbanens interne stasjonskode
      (f.eks. SKN). Skiller to anlegg på samme radiokanal i samme lokale:
      parede noder og master godtar kun sitt eget anlegg. Lagring døper
      samtidig om wifi-nettet til NSI63&lt;ID&gt; og Pi-ens hostname til
      det samme i små bokstaver — <b>AP-et restarter, og du må koble
      denne enheten til det nye nettet</b>. Master og noder finner frem
      selv. Nye (uparede) enheter lærer ID-en ved første kontakt — par
      dem hjemme, og skru AV «adopter nye noder» på treff. Langtrykk
      (10 s) på knappen til node/master glemmer paringen. Tom ID =
      filter av (alt adopteres, nettet heter NSI63).</p></div>`;
  }

  // Backup: hele konfigurasjonen (objekter + forrigling + anleggs-ID)
  html += `<div class="card"><h2>Backup</h2>
    <p class="hint">Én fil med hele konfigurasjonen: objekter,
    forriglingstabell og anleggs-ID. Gjenoppretting overskriver dagens
    konfigurasjon og publiserer til master (anleggs-ID-en i backupen
    vises, men tas aldri i bruk automatisk).</p>
    <div class="bar" style="margin:8px 0 4px">
      <button class="mini" onclick="location.href='/api/backup'">
        Last ned backup</button>
      <button class="mini"
        onclick="document.getElementById('restoreFile').click()">
        Gjenopprett fra backup…</button>
    </div></div>`;

  // Pi-kortet: temperatur, strøm, nett, klienter, tjenester
  {
    const thrNaa = (pi.throttled && pi.throttled.naa) || [];
    const thrHist = (pi.throttled && pi.throttled.historikk) || [];
    const varm = pi.temp != null && pi.temp >= 70;
    html += `<div class="card"><h2>PI <span class="hint">` +
      (pi.modell || "pi") + `</span></h2>`;
    if (thrNaa.length)
      html += `<p><span class="off">⚠ ` + thrNaa.join(", ").toUpperCase() +
        `</span> — sjekk strømforsyningen!</p>`;
    let l1 = [];
    if (pi.temp != null)
      l1.push(`temp <span class="` + (varm ? "off" : "on") + `">` +
              String(pi.temp).replace(".", ",") + `&deg;C</span>`);
    if (pi.last) l1.push(`last ` + pi.last[0].toFixed(2).replace(".", ","));
    if (pi.mem) l1.push(`minne ` + pi.mem.ledig_mb + `/` +
                        pi.mem.total_mb + ` MB ledig`);
    if (pi.disk) l1.push(`disk ` + pi.disk.ledig_gb + `/` +
                         pi.disk.total_gb + ` GB ledig`);
    html += `<p class="hint">` + l1.join(" · ") + `</p>`;
    let ks;
    if (pi.ntp) ks = `<span class="on">NTP ok</span>`;
    else if (pi.klokke_stilt)
      ks = `<span class="on">stilt fra nettleser kl. ` +
           pi.klokke_stilt.naar + `</span>`;
    else ks = `ingen RTC — stilles automatisk fra nettleseren ved behov`;
    html += `<p class="hint">oppetid ` + fmtSek(pi.oppetid_s) +
      ` · klokke ` + (pi.klokke || "?") + ` · ` + ks + `</p>`;
    if (thrHist.length)
      html += `<p class="hint">siden boot: ` + thrHist.join(", ") +
        ` har forekommet</p>`;
    const ipTxt = (pi.ips || []).map(i =>
      i.ifname + ` ` + i.addrs.join(", ") +
      (i.oper && i.oper !== "UP" ? ` (` + i.oper.toLowerCase() + `)` : ""))
      .join(` · `);
    if (ipTxt) html += `<p class="hint">IP: ` + ipTxt + `</p>`;
    const tj = pi.tjenester || {};
    html += `<p class="hint">` + Object.keys(tj).map(n =>
      n + ` <span class="` + (tj[n] === "active" ? "on" : "off") + `">` +
      (tj[n] === "active" ? "ok" : tj[n]) + `</span>`).join(" · ") + `</p>`;
    const kl = pi.klienter || [];
    if (kl.length) {
      html += `<div class="chips"><div class="chip"><table>` +
        `<caption>AP-klienter (` + kl.length + `)</caption>` +
        `<tr><th>Navn</th><th>IP</th><th>MAC</th><th>Signal</th>` +
        `<th>Tilkoblet</th></tr>`;
      for (const c of kl) {
        const erMaster = master.mac &&
          c.mac.replace(/:/g, "") === master.mac;
        html += `<tr><td>` +
          (c.navn || `<span class="fri">?</span>`) +
          (erMaster ? ` <span class="on">master</span>` : ``) +
          `</td><td>` + (c.ip || `–`) + `</td><td>` + c.mac +
          `</td><td>` + (c.signal != null ? c.signal + ` dBm` : `–`) +
          `</td><td>` + fmtSek(c.tid_s) + `</td></tr>`;
      }
      html += `</table></div></div>`;
    } else {
      html += `<p class="hint">ingen wifi-klienter tilkoblet</p>`;
    }
    html += `</div>`;
  }

  // Firmware (OTA): ÉN felles binær for master og noder — rollen
  // velges med knappegest på enheten. Oppdater-knappene ligger på
  // enhetenes egne kort.
  const fwFil = "nsi63-atoms3.bin";
  {
    const stp = f => ota[f] ? (ota[f].stempel || "uten stempel") : null;
    const fs = stp(fwFil);
    const stat = fs ? `firmware ${fs} klar`
                    : `ingen firmware lastet opp ennå`;
    html += `<div class="card"><h2>Firmware (OTA)</h2>
      <p class="hint">Én felles binær for master og noder — rollen
      velges med knappegest på enheten (hold frontknappen 3 s ved
      strømpåslag = master). Bygg med <code>bash bygg-ota.sh</code> og
      last opp <code>.bin</code>-fila den lager. Oppdatering utløses fra enhetens eget kort:
      master oppdaterer seg selv (hele anlegget i sikker tilstand
      ~1 min, selvhelende); noder henter via en kort wifi-oppkobling
      til AP-et (mørk ~1 min — ta én om gangen). MD5-verifisert mot
      passiv partisjon: feiler noe, kjører gammel firmware videre.
      Første OTA-runde krever USB-flash av OTA-støttet firmware.</p>
      <div class="bar" style="margin:8px 0 4px">
        <input type="file" id="ota-fil" accept=".bin" style="display:none"
               onchange="otaLastOpp(this)">
        <button class="mini"
          onclick="document.getElementById('ota-fil').click()">
          Last opp firmware…</button>
        <span class="hint">${stat}</span>
      </div></div>`;
  }

  // Master-kortet
  // Byggestempel-sammenlikning enhet vs. opplastet binær: markerer
  // kortene som gjenstår etter en OTA-runde. Stemplene er ÅÅÅÅMMDDTTMM,
  // så vanlig strengsammenlikning gir riktig kronologi. Uten stempel
  // på en av sidene (manuell opplasting / gammel fw) vises ingenting.
  const fwEldre = (bygget, fn) => {
    const s = ota[fn] && ota[fn].stempel;
    return s && bygget && bygget < s
      ? ` <span class="off">oppdatering tilgjengelig (${s})</span>` : ``;
  };
  {
    // Ferskhet: retained «online» tros bare når masterens 10 s-puls
    // på adminplanet (info/roster) faktisk kommer inn. En master som
    // har vært stille i 35 s+ vises som stille — uansett hva retained
    // sier. (Det var slik foreldet «online» villedet feilsøkingen.)
    const stille = master.sist_hort_s == null || master.sist_hort_s >= 35;
    const st = master.status === "online" && !stille;
    const inf = master.info || {};
    html += `<div class="card"><h2>MASTER ` +
      (master.mac ? `<span class="hint">${master.mac}</span> ` : "") +
      (st ? `<span class="on">online</span>`
          : master.status === "online" && stille
            ? `<span class="off">ingen livstegn på ${master.sist_hort_s ?? "?"} s — antatt frakoblet</span>`
            : `<span class="off">${master.status || "ukjent"}</span>`) +
      (inf.fw !== undefined
        ? ` <span class="hint">fw v${inf.fw}` +
          (inf.bygget ? ` · ${inf.bygget}` : ``) + `</span>` +
          fwEldre(inf.bygget, fwFil)
        : (st ? ` <span class="off">fw ukjent (gammel firmware?)</span>`
              : ``)) +
      `</h2><p class="hint">` +
      (inf.uptime !== undefined
        ? `oppetid ${inf.uptime}s · puls ${inf.pulse} · wifi ${inf.rssi} dBm · ` +
          `${inf.nodes} noder kjent`
        : `ingen info mottatt ennå`) +
      `</p>`;
    for (const m of master.meldinger || [])
      html += `<p><span class="off">⚠ ${m.tekst}</span> <span class="hint">(` +
        fmtSek(Date.now() / 1000 - m.ts) + ` siden)</span></p>`;
    if (ota[fwFil] && st)
      html += `<div class="bar" style="margin:8px 0 4px">
        <button class="mini" onclick="otaStart('master')">Oppdater fw</button>
      </div>`;
    html += `<p class="hint">Bytte av master krever ingen konfigurasjon:
      skru av den gamle, hold frontknappen på en hvilken som helst
      reservenode inne i 3 s mens strømmen kobles til (fiolett lys
      kvitterer) — den nye masteren henter konfigurasjonen selv fra
      brokeren.</p></div>`;
  }

  const rosterFersk = master.sist_hort_s != null && master.sist_hort_s < 35;
  for (const n of nodes.nodes || []) {
    const alias = aliasFor(n.mac);
    html += `<div class="card"><h2>` +
      (alias ? `${alias} <span class="hint">${n.mac}</span> ` : `${n.mac} `) +
      (!rosterFersk
         ? `<span class="off">ukjent — master stille</span>`
         : n.online ? `<span class="on">online</span>`
                    : `<span class="off">offline</span>`) +
      (n.safe ? ` <span class="off">SIKKER TILSTAND</span>` : "") +
      (n.fw ? ` <span class="hint">fw v${n.fw}` +
              (n.bygget ? ` · ${n.bygget}` : ``) + `</span>` +
              fwEldre(n.bygget, fwFil)
            : ` <span class="off">fw ukjent (gammel firmware?)</span>`) +
      `</h2>
      <div class="bar" style="margin:8px 0 4px">
        <input style="max-width:220px;text-transform:uppercase"
               id="alias-${attr(n.mac)}" value="${attr(alias)}"
               placeholder="kallenavn, f.eks. SEKSJON1">
        <button class="mini" onclick="saveAlias('${n.mac}')">Lagre navn</button>
        <button class="mini" onclick="findNode('${n.mac}')">Finn (blink)</button>
        <button class="mini" onclick="forgetNode('${n.mac}')">Fjern node</button>` +
      (ota[fwFil] && n.online ? `
        <button class="mini" onclick="otaStart('${n.mac}')">Oppdater fw</button>`
                            : ``) + `
      </div>
      <div class="chips">`;
    const chips = n.i2c || [];
    if (!chips.length && !(n.fw >= 4))
      html += `<span class="hint">ingen I2C-enheter meldt</span>`;
    for (const addr of chips) {
      const isPca = addr.startsWith("0x4");
      const nPorts = isPca ? 16 : 8;
      const lbl = portLabels(hal, n.mac, addr);
      const val = inputs[`${n.mac}/${addr}`];
      html += `<div class="chip"><table><caption>${addr} ` +
              (isPca ? "PCA9685 (ut)" : "PCF8574 (inn)") + `</caption>` +
              `<tr><th>Port</th><th>Funksjon</th>` +
              (isPca ? "" : "<th>Verdi</th>") + `</tr>`;
      for (let p = 0; p < nPorts; p++) {
        html += `<tr><td>${p}</td><td>` +
                (lbl[p] || `<span class="fri">fri</span>`) + `</td>`;
        if (!isPca) {
          if (val === undefined || val === null) html += `<td>–</td>`;
          else {
            const bit = (val >> p) & 1;
            html += `<td class="bit${bit}">${bit}</td>`;
          }
        }
        html += `</tr>`;
      }
      html += `</table></div>`;
    }
    // GPIO-portene (fw v4+): nodens egne pinner — inn eller ut per
    // port, bestemt av bindingsstedet. Verdi vises for inngangsporter.
    if (n.fw >= 4) {
      const lbl = portLabels(hal, n.mac, "gpio");
      const inn = gpioInnPorter(hal, n.mac);
      const val = inputs[`${n.mac}/0x00`];
      html += `<div class="chip"><table><caption>GPIO (på noden)</caption>` +
              `<tr><th>Port</th><th>Funksjon</th><th>Verdi</th></tr>`;
      for (let p = 0; p < GPIO_PINNER.length; p++) {
        html += `<tr><td>${p} <span class="hint">${GPIO_PINNER[p]}</span></td>` +
                `<td>` + (lbl[p] || `<span class="fri">fri</span>`) + `</td>`;
        if (!inn.has(p)) html += `<td class="hint">${lbl[p] ? "ut" : "–"}</td>`;
        else if (val === undefined || val === null) html += `<td>–</td>`;
        else {
          const bit = (val >> p) & 1;
          html += `<td class="bit${bit}">${bit}</td>`;
        }
        html += `</tr>`;
      }
      html += `</table></div>`;
    }
    html += `</div></div>`;
  }
  // Lampeprøve
  html += `<div class="card"><h2>Lampeprøve</h2>
    <p class="hint">Slukker alle lamper, blinker alle tre ganger i takt,
    og kjører så løpelys (0,5 s per lampe) til Stopp trykkes — lampen
    som lyser i stoppøyeblikket slukkes umiddelbart. Etterpå
    gjenoppretter master signalbildene automatisk.</p>
    <div class="bar" style="margin:8px 0 4px">
      <button class="mini" onclick="lampTest('start')">Start</button>
      <button class="mini" onclick="lampTest('stop')">Stopp</button>
      <span class="hint">` +
    (lt.running ? `pågår: ${lt.i}/${lt.total} — ${lt.progress}`
                : (lt.total ? `sist: ${lt.i}/${lt.total} (${lt.progress})` : "")) +
    `</span></div></div>`;
  // Foreldreløse kallenavn: peker på MAC-er master ikke kjenner
  // (aldri sett, eller glemt). Vises så de kan ryddes bort.
  const kjenteMac = new Set((nodes.nodes || []).map(n => n.mac));
  for (const [alias, v] of Object.entries(NODER)) {
    if (kjenteMac.has(v.mac)) continue;
    html += `<div class="card"><h2>${alias} ` +
      `<span class="hint">${v.mac}</span> ` +
      `<span class="off">aldri sett</span></h2>
      <p class="hint">Kallenavnet peker på en MAC som ikke er registrert
      hos master. Sett samme navn på en ny enhet fra kortet dens, eller
      slett kallenavnet her.</p>
      <div class="bar" style="margin:8px 0 4px">
        <button class="mini" onclick="deleteAlias('${v.mac}')">
          Slett kallenavn</button>
      </div></div>`;
  }

  // LED-tegnforklaring — operatøren skal slippe å huske fargespråket
  const dot = c => `<span style="color:${c};font-size:14px">●</span>`;
  html += `<div class="card"><h2>LED-språk <span class="hint">M5 AtomS3</span></h2>
    <p class="hint">Blink i sekundtakt = pulsen flyter (anleggets EKG);
    fast lys = låst tilstand. Pustende lys = aktiv søking.</p>
    <p class="hint"><b>Master:</b>
      ${dot("#4a90d9")} blink = alt vel &nbsp;
      ${dot("#e05252")} blink = node savnet/sikker tilstand &nbsp;
      ${dot("#e08a3c")} blink = wifi/MQTT nede &nbsp;
      ${dot("#b46be0")} blink = mangler konfig &nbsp;
      ${dot("#e05252")}${dot("#e05252")} dobbelt = TO mastere! &nbsp;
      ${dot("#3cc8c8")} fast = OTA pågår</p>
    <p class="hint"><b>Node:</b>
      ${dot("#5bb974")} blink = normal drift &nbsp;
      ${dot("#e0c23c")} blink = «Finn meg» &nbsp;
      ${dot("#e052e0")}${dot("#e052e0")} dobbelt = I2C-feil &nbsp;
      ${dot("#e05252")} fast = sikker tilstand &nbsp;
      ${dot("#e0c23c")} pustende = søker master &nbsp;
      ${dot("#3cc8c8")} fast = OTA pågår</p>
    <p class="hint"><b>Begge:</b> ${dot("#eeeeee")} fast hvitt under
      holdt knapp (10 s+) = slipp for å nullstille paringen.</p></div>`;

  // Hendelseslogg (svart boks) — alt på MQTT-flaten, én linje per
  // hendelse. Fylles av hentHendelser() etter render.
  html += `<div class="card"><h2>Hendelseslogg
      <span class="hint">svart boks</span></h2>
    <p class="hint">Alle hendelser på anlegget — togveier, signaler,
    sporfelt, betjening, driftsmeldinger — med tidsstempel. Nyeste
    nederst. Filteret matcher tema og innhold (f.eks. «togvei/A-01»,
    «avvist», «sporveksel»). Loggingen er AV som standard — slå den
    på ved feilsøking, innkjøring eller treff (skriver til SD-kortet;
    valget huskes over restart, og loggen beholdes når den slås av).</p>
    <div class="bar" style="margin:8px 0 4px">
      <label class="hint" style="white-space:nowrap">
        <input type="checkbox" id="h-aktiv"
               onchange="hendelserAktiv(this.checked)"> logging på</label>
      <input id="h-filter" placeholder="filter" style="max-width:220px"
             onkeydown="if(event.key==='Enter')hentHendelser()">
      <button class="mini" onclick="hentHendelser()">Oppdater</button>
      <a class="mini" href="/api/hendelser/fil" download
         style="text-decoration:none">Last ned alt</a>
      <span class="hint" id="h-antall"></span>
    </div>
    <div id="h-liste" style="max-height:320px;overflow:auto;
         font-family:monospace;font-size:12px;white-space:pre"></div>
    </div>`;

  sec.innerHTML = html || `<p class="hint">Ingen noder registrert ennå.</p>`;
  hentHendelser();
}
async function hentHendelser() {
  const el = document.getElementById("h-liste");
  if (!el) return;
  const filt = (document.getElementById("h-filter") || {}).value || "";
  const r = await fetch("/api/hendelser?n=300&filter=" +
                        encodeURIComponent(filt));
  const j = await apiJson(r);
  if (!r.ok) { el.textContent = j.error || "feil"; return; }
  const rad = h => {
    const d = new Date(h.ts * 1000);
    const t = d.toTimeString().slice(0, 8) + "." +
              String(d.getMilliseconds()).padStart(3, "0");
    return t + "  " + h.tema.padEnd(28) + "  " +
           (typeof h.data === "string" ? h.data : JSON.stringify(h.data)) +
           (h.r ? "   (retained)" : "");
  };
  el.textContent = (j.hendelser || []).map(rad).join("\\n") ||
                   (j.aktiv ? "(ingen hendelser matcher)"
                            : "(logging er av — slå den på over)");
  el.scrollTop = el.scrollHeight;   // nyeste nederst — vis dem
  const cb = document.getElementById("h-aktiv");
  if (cb) cb.checked = !!j.aktiv;
  const an = document.getElementById("h-antall");
  if (an) an.textContent = (j.hendelser || []).length + " hendelser" +
                           (j.kuttet ? " (av flere — bruk Last ned alt)" : "");
}
async function hendelserAktiv(paa) {
  await fetch("/api/hendelser/aktiv", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({aktiv: paa})});
  hentHendelser();
}
async function deleteAlias(mac) {
  if (!confirm("Slette kallenavnet? Bindinger som bruker det vil vise " +
               "'(ukjent)' til de peker et annet sted.")) return;
  await fetch("/api/node-alias", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac, alias: ""})});
  await loadAll();
  renderNoder();
}
async function otaLastOpp(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/ota/firmware", {method: "POST", body: fd});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  toast("Mottatt: " + j.fil +
        (j.stempel ? " (bygget " + j.stempel + ")" : " (uten stempel)"));
  renderNoder();
}
// Ikke-blokkerende melding nederst i vinduet — erstatter alert() for
// info og feil. confirm() beholdes bare der noe slettes/overskrives,
// og alert() bare ved AP-navnebytte (nettet restarter — meldingen MÅ
// leses før siden mister kontakten).
function toast(tekst, feil) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.onclick = () => { el.style.display = "none"; };
    document.body.appendChild(el);
  }
  el.textContent = tekst;
  el.style.cssText = "position:fixed;left:50%;bottom:24px;" +
    "transform:translateX(-50%);max-width:80%;z-index:99;" +
    "padding:10px 16px;border-radius:8px;cursor:pointer;" +
    "box-shadow:0 4px 16px rgba(0,0,0,.4);display:block;" +
    (feil ? "background:#5a1f1f;color:#ffb3b3;"
          : "background:#1f3a5a;color:#cfe4ff;");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.style.display = "none"; }, 6000);
}
// Masterens siste svar per togvei — vises som stille statuslinje i
// togveikortet (ingen popup). Overlever frRender via denne cachen.
const TVSVAR = {};
function visTvSvar(id, tekst) {
  TVSVAR[id] = tekst;
  const el = document.getElementById("tvsvar-" + id);
  if (el) {
    el.textContent = tekst;
    el.className = /^avvist/.test(tekst) ? "off" : "hint";
  }
}
async function betjenTogvei(id, hva) {
  visTvSvar(id, "…");
  const j = await apiJson(await fetch("/api/togvei-betjen", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id, hva})}));
  // Masterens begrunnelse (fanget fra nsi63/togvei/<id>/info av
  // serveren): «sikret: kjorsignal satt», «avvist: …», «trinn 1:
  // signal i stopp …» osv. — aldri en popup som må kvitteres.
  visTvSvar(id, j.error ? "avvist: " + j.error
    : j.svar ? j.svar
    : "ingen svar fra master — sikring kan pågå (veksler legges om), " +
      "eller masteren er frakoblet");
}
async function otaStart(maal) {
  const hvem = maal === "master"
    ? "master? Hele anlegget går i sikker tilstand ~1 min og henter " +
      "seg inn selv etterpå"
    : "noden " + maal + "? Den er mørk (= stopp) i ~1 min";
  if (!confirm("Starte trådløs firmwareoppdatering av " + hvem + ".")) return;
  const r = await fetch("/api/ota/start", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({maal})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  renderNoder();
}
// Snarvei fra banneret: skru av omgåelsen uten å lete opp Noder-fanen
async function slaAvTestmodus() {
  const an = await (await fetch("/api/anlegg")).json();
  const r = await fetch("/api/anlegg", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: an.id, adopter: an.adopter,
                          fjernstyrt: an.fjernstyrt,
                          dekningsstilling: an.dekningsstilling,
                          hjelpeutlosning_s: an.hjelpeutlosning_s,
                          testmodus: false})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  document.getElementById("testbanner").style.display = "none";
  if (currentView === "noder") renderNoder();
}
async function saveAnlegg() {
  const id = document.getElementById("anlegg-id").value.trim().toUpperCase();
  const adopter = document.getElementById("anlegg-adopter").checked;
  const testmodus = document.getElementById("anlegg-test").checked;
  const fjernstyrt = document.getElementById("anlegg-fjern").checked;
  const dekningsstilling = document.getElementById("anlegg-dekning").checked;
  const hjelpeutlosning_s =
      parseInt(document.getElementById("anlegg-hjelp").value || "90");
  const r = await fetch("/api/anlegg", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id, adopter, testmodus, fjernstyrt,
                          dekningsstilling, hjelpeutlosning_s})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  settTittel(j.id);
  if (j.ap_omdopt)
    alert("AP-et heter nå «" + j.ssid + "» — wifi-nettet du er koblet " +
          "til startet på nytt med nytt navn. Koble denne enheten til " +
          "det nye nettet og last siden på nytt (http://" + j.hostname +
          ".local:8080 eller 10.206.0.1:8080). Master og noder finner " +
          "frem selv.");
  renderNoder();
}
function settTittel(id) {
  const navn = "NSI63" + (id || "");
  document.title = navn + " — sikringsanlegg";
  const h1 = document.getElementById("tittel");
  if (h1 && h1.childNodes.length) h1.childNodes[0].textContent = navn;
}
async function saveAlias(mac) {
  const alias = document.getElementById("alias-" + mac)
                  .value.trim().toUpperCase();
  const r = await fetch("/api/node-alias", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac, alias})});
  const j = await apiJson(r);
  if (!r.ok) { toast(j.error, true); return; }
  await loadAll();          // bindingstabellen bruker nye kallenavn
  renderNoder();
}
// ---------- Forrigling: togvei-editor (modellbasert) ----------
let TOGVEIER = [];
let HALFN = [];   // HAL-funksjoner til nedtrekkene

function frLitraer(types) {
  return HALFN.filter(f => types.includes(f.type)).map(f => f.id);
}
function frTogspor() {
  return HALFN.filter(f => f.type === "sporfelt" && f.rolle === "togspor")
              .map(f => f.id);
}
function frEndeFelt() {   // lovlige rute-ender: linjefelt og togspor
  return HALFN.filter(f => f.type === "sporfelt" &&
    (f.rolle === "linjefelt" || f.rolle === "togspor")).map(f => f.id);
}
// Signalet avledes av endene: én kandidat = etikett, flere = valg
// blant kandidatene, ingen = veiledning (sett rolle/linjefelt på
// hovedsignalet under Objekter)
function frSignalCelle(tv, i) {
  const r = frRetning(tv);
  if (!r) return `<span class="hint">velg fra- og til-felt</span>`;
  const kand = frStartKandidater(tv);
  if (!kand.length)
    return `<span class="off">ingen ${r === "indre" ? "indre " : ""}` +
           `hovedsignal${r === "indre" ? "" : " ved " +
           (r === "innkjor" ? tv.fra : tv.til)} — sett rolle` +
           `${r === "indre" ? "" : "/linjefelt"} under Objekter</span>`;
  if (kand.length === 1)
    return `<span class="hint">signal:</span> <b>${kand[0]}</b>`;
  return `<span class="hint">signal:</span>
    <select style="max-width:150px"
            onchange="TOGVEIER[${i}].start=this.value;frRender()">
      ${kand.map(k => opt(k, k, tv.start)).join("")}</select>`;
}
async function frLoad() {
  const [hal, fr] = await Promise.all([
    (await fetch("/api/hal")).json(),
    (await fetch("/api/forrigling")).json(),
  ]);
  HALFN = hal.functions || [];
  TOGVEIER = fr.togveier || [];
  STATUS.fr = fr.version;
  STATUS.frAntall = TOGVEIER.length;
  oppdaterStatus();
  frRender();
}
function frSel(litraer, sel, allowEmpty) {
  let out = allowEmpty ? opt("", "—", sel) : "";
  for (const l of litraer) out += opt(l, l, sel);
  if (sel && !litraer.includes(sel)) out += opt(sel, sel + " (ukjent)", sel);
  return out;
}
function frBilde(tv) {
  const st = HALFN.find(f => f.id === tv.start &&
    erHoved(f.type));
  if (st && st.type === "hovedsignal2") return "kjor-redusert";  // tolys
  return (tv.sporveksler || []).some(v => v.stilling === "avvik")
    ? "kjor-redusert" : "kjor";
}
// Togvei-ID genereres av rute-endene, som i togveitabellene i
// forbildet: innkjør = <linjefelt><spor> (A01), utkjør =
// <spor><linjefelt> (01A). Retningen leses av startsignalets rolle,
// linjefeltet finnes blant de frie feltene.
function frGenId(tv) {
  frEnder(tv);
  return frRetning(tv) ? tv.fra + tv.til : "";
}
// En togvei går FRA et sporfelt TIL et sporfelt (som i forbildet):
// linjefelt→togspor = innkjør, togspor→linjefelt = utkjør,
// togspor→togspor = indre (større stasjoner). Signal, ID, frie felt
// og utløsningsfelt avledes av endene.
function feltRolle(id) {
  const f = HALFN.find(x => x.type === "sporfelt" && x.id === id);
  return f ? (f.rolle || "") : "";
}
function frRetning(tv) {
  const fr = feltRolle(tv.fra), tl = feltRolle(tv.til);
  if (fr === "linjefelt" && tl === "togspor") return "innkjor";
  if (fr === "togspor" && tl === "linjefelt") return "utkjor";
  if (fr === "togspor" && tl === "togspor" && tv.fra !== tv.til)
    return "indre";
  return "";
}
// Eldre rader (uten fra/til) migreres ved visning: endene regnes ut
// av startsignalets rolle + feltlisten
function frEnder(tv) {
  if (tv.fra && tv.til) return;
  const st = HALFN.find(f => erHoved(f.type) && f.id === tv.start) || {};
  const linje = (tv.frie || []).find(x =>
    feltRolle(x) === "linjefelt") || "";
  if (st.rolle === "innkjor") { tv.fra = linje; tv.til = tv.spor || ""; }
  else if (st.rolle === "utkjor") { tv.fra = tv.spor || ""; tv.til = linje; }
}
// Hovedsignal-kandidater for ruten: rolle + linjefelt-tilhørighet.
// Signaler med linjefelt satt foretrekkes; uten satt tilhørighet
// godtas som reserve (ukoblede eldre konfigurasjoner).
function frStartKandidater(tv) {
  const r = frRetning(tv);
  if (!r) return [];
  if (r === "indre")
    return HALFN.filter(f => erHoved(f.type) && f.rolle === "indre")
                .map(f => f.id);
  const mål = r === "innkjor" ? tv.fra : tv.til;
  const kand = HALFN.filter(f => erHoved(f.type) && f.rolle === r);
  const eksakte = kand.filter(f => f.linjefelt === mål);
  const uten = kand.filter(f => !f.linjefelt);
  return (eksakte.length ? eksakte : uten).map(f => f.id);
}
function frAutoFelt(tv) {
  frEnder(tv);
  const r = frRetning(tv);
  if (!r) return null;
  const vfelt = (tv.sporveksler || []).map(v => v.sporveksel).filter(x =>
    x && HALFN.some(f => f.type === "sporfelt" && f.id === x));
  if (r !== "indre" && !vfelt.length) return null;
  if (r === "innkjor")
    return {frie: [tv.fra, ...vfelt, tv.til], utlos: vfelt[0]};
  return {frie: [...vfelt, tv.til], utlos: vfelt[0] || ""};
}
// Minstekrav for togveier: ett linjefelt, TO togspor og en veksel —
// med bare ett togspor finnes det ingenting å forrigle (en
// endestasjon har ett linjefelt, men fortsatt flere togspor)
function frKrav() {
  const mangler = [];
  if (!HALFN.some(f => f.type === "sporfelt" && f.rolle === "linjefelt"))
    mangler.push("et linjefelt");
  const nSpor = HALFN.filter(f => f.type === "sporfelt" &&
                                  f.rolle === "togspor").length;
  if (nSpor < 2)
    mangler.push(nSpor ? "ett togspor til (minst to)" : "to togspor");
  if (!HALFN.some(f => f.type === "sporveksel"))
    mangler.push("en veksel");
  return mangler;
}
function frRender() {
  // Normalisering per rad: migrer eldre rader til fra/til, avled
  // spor og startsignal av endene, og fyll tomme felt-lister.
  // Manuelle felt-valg røres aldri (auto-knappen overskriver).
  TOGVEIER.forEach(tv => {
    frEnder(tv);
    const r = frRetning(tv);
    if (r) {
      tv.spor = (r === "utkjor") ? tv.fra : tv.til;
      const kand = frStartKandidater(tv);
      if (kand.length && !kand.includes(tv.start)) tv.start = kand[0];
      if (!kand.length) tv.start = tv.start || "";
    }
    if ((tv.frie || []).filter(Boolean).length === 0) {
      const a = frAutoFelt(tv);
      if (a) {
        tv.frie = a.frie;
        if (!tv.utlosningsfelt) tv.utlosningsfelt = a.utlos;
      }
    }
  });
  const hoved = frLitraer(TYPES.filter(erHoved));
  const veksler = frLitraer(["sporveksel"]);   // manuellveksel: se validering
  const felt = frLitraer(["sporfelt"]);
  let html = "";
  TOGVEIER.forEach((tv, i) => {
    const gid = frGenId(tv) || tv.id || "";
    html += `<div class="card">
      <div class="bar" style="margin:0 0 8px">
        <b style="min-width:64px" title="Genereres automatisk av fra+til">${gid || "—"}</b>
        <select style="max-width:110px" title="Feltet togveien går FRA: linjefelt (innkjør) eller togspor (utkjør/indre)"
                onchange="TOGVEIER[${i}].fra=this.value;frRender()">
          ${frSel(frEndeFelt(), tv.fra||"", true).replace('">—<',
            '">fra: —<')}</select>
        <span class="hint">→</span>
        <select style="max-width:110px" title="Feltet togveien går TIL: togspor (innkjør/indre) eller linjefelt (utkjør)"
                onchange="TOGVEIER[${i}].til=this.value;frRender()">
          ${frSel(frEndeFelt(), tv.til||"", true).replace('">—<',
            '">til: —<')}</select>
        ${frSignalCelle(tv, i)}
        <input style="flex:1" value="${tv.notes||""}" placeholder="notat"
               onchange="TOGVEIER[${i}].notes=this.value.trim()">
        <span class="hint">bilde: ${frBilde(tv)}</span>
        <button class="mini" ${gid ? "" : "disabled"} title="Be master sikre togveien: forriglingen kontrollerer felt, fiendtlighet, frigivning og skifting, legger vekslene én om gangen og setter kjørsignal. Masterens svar vises på linjen under."
                onclick="betjenTogvei('${gid}', 'sikre')">Sikre</button>
        <button class="mini" ${gid ? "" : "disabled"} title="Hjelpeutløsning trinn 1: setter togveiens startsignal i stopp — togveien er fortsatt forriglet. Som togveistillerne MOT hverandre. (Ikke det samme som signalstopp-bryteren, som sperrer hele anlegget.)"
                onclick="betjenTogvei('${gid}', 'stopp')">Stopp</button>
        <button class="mini" ${gid ? "" : "disabled"} title="Hjelpeutløsning trinn 2: løser ut togveien. Avvises så lenge startsignalet viser kjørsignal — bruk Stopp først. Under sikring løses den ut direkte. Driftsbetjening: uten stillerapparatets 90 s tidsrelé."
                onclick="betjenTogvei('${gid}', 'hjelpeutlos')">Utløs</button>
        <button class="row-del" onclick="TOGVEIER.splice(${i},1);frRender()">✕</button>
      </div>
      <div class="bar" style="margin:0 0 4px">
        <span id="tvsvar-${gid}" class="${/^avvist/.test(TVSVAR[gid] || "") ? "off" : "hint"}">${TVSVAR[gid] || ""}</span>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Veksler:</span>` +
      (tv.sporveksler||[]).map((v, j) => `
        <select style="max-width:130px" onchange="TOGVEIER[${i}].sporveksler[${j}].sporveksel=this.value;frRender()">
          ${frSel(veksler, v.sporveksel||"", true)}</select>
        <select style="max-width:100px" onchange="TOGVEIER[${i}].sporveksler[${j}].stilling=this.value;frRender()">
          ${opt("normal","normal",v.stilling)}${opt("avvik","avvik",v.stilling)}</select>
        <button class="row-del" onclick="TOGVEIER[${i}].sporveksler.splice(${j},1);frRender()">✕</button>`).join("") +
      `<button class="mini" onclick="(TOGVEIER[${i}].sporveksler=TOGVEIER[${i}].sporveksler||[]).push({sporveksel:'',stilling:'normal'});frRender()">+</button>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Frie sporfelt:</span>
        <button class="mini" title="Avled feltene av endene: linjefelt + vekselfelt + togspor (innkjør) / vekselfelt + linjefelt (utkjør). Overskriver listen."
                onclick="frAutoFyll(${i})">auto</button>` +
      (tv.frie||[]).map((sf, j) =>
        `<span>${sf} <button class="row-del" onclick="TOGVEIER[${i}].frie.splice(${j},1);frRender()">✕</button></span>`).join("") +
      `<select style="max-width:130px" onchange="if(this.value){(TOGVEIER[${i}].frie=TOGVEIER[${i}].frie||[]).push(this.value);frRender()}">
        ${frSel(felt.filter(f=>!(tv.frie||[]).includes(f)), "", true)}</select>
      </div>
      <div class="bar" style="margin:4px 0">
        <span class="hint" style="min-width:90px">Utløsningsfelt:</span>
        <select style="max-width:130px" title="Vekselfeltet — belagt og deretter fritt river togveien"
                onchange="TOGVEIER[${i}].utlosningsfelt=this.value;frSkisse()">
          ${frSel(felt, tv.utlosningsfelt||"", true)}</select>
        <span class="hint">signalet faller ved belegg på ETHVERT felt i
        togveien; utløsningsfeltet belagt→fritt = togveien rives.
        Velg vekselfeltet togveien går over — togspor og linjefelt
        blir stående belagt av toget selv, og togveien ville aldri
        (eller for sent) blitt revet.</span>
      </div>
    </div>`;
  });
  const mangler = frKrav();
  const nyKnapp = document.getElementById("fr-ny");
  const kravEl = document.getElementById("fr-krav");
  if (nyKnapp) nyKnapp.disabled = mangler.length > 0;
  if (kravEl) {
    let k = "";
    if (mangler.length)
      k = `togveier trenger minst ${mangler.join(", ")} — legg til ` +
          `under Objekter først`;
    else if (!HALFN.some(f => erHoved(f.type)))
      k = `tips: legg til hovedsignaler (rolle innkjør/utkjør) under ` +
          `Objekter, så avledes signalet automatisk`;
    kravEl.textContent = k;
  }
  document.getElementById("fr-cards").innerHTML =
    html || (mangler.length
      ? `<p class="hint">Ingen togveier ennå. Definer anleggets objekter
         først: sporfelt (linjefelt og togspor), veksler og
         hovedsignaler — så lages togveiene her, fra felt til felt.</p>`
      : `<p class="hint">Ingen togveier ennå — trykk «+ Ny togvei».</p>`);
  frSkisse();
  frKonflikter();
}
// ---- skjematisk skisse avledet av togveitabellen ----
// Én linje per togspor: venstre ende, innkjør-/utkjørsignaler,
// veksler med stilling (n/a), sporet, og det samme speilet mot høyre
// ende. «···» = togvei mangler. Ren dobbeltsjekk — tegnes på nytt
// ved hver endring og avslører hull og feilkoblinger i tabellen.
function frSkisse() {
  const el = document.getElementById("fr-skisse");
  const advEl = document.getElementById("fr-adv");
  if (!el) return;
  // Typede oppslag: litra er unik per objektklasse
  const sigAv = id => HALFN.find(f => f.id === id &&
    erHoved(f.type)) || {};
  const feltAv = id => HALFN.find(f => f.id === id &&
    f.type === "sporfelt") || {};
  const adv = [];

  const ruter = [];
  TOGVEIER.forEach(tv => {
    const id = tv.id || "(uten id)";
    if (!tv.start) { adv.push(`${id}: mangler startsignal`); return; }
    const rolle = sigAv(tv.start).rolle || "";
    if (rolle === "indre") {
      adv.push(`${id}: indre togvei (togspor til togspor) — vises ` +
               `ikke i skissen ennå`);
      return;
    }
    if (rolle !== "innkjor" && rolle !== "utkjor") {
      adv.push(`${id}: startsignalet ${tv.start} mangler rolle ` +
               `innkjør/utkjør under Objekter`);
      return;
    }
    const linje = (tv.frie || [])
      .find(f => feltAv(f).rolle === "linjefelt") || "";
    if (!linje) adv.push(`${id}: ingen av sporfeltene er linjefelt ` +
                         `(sett rolle under Objekter)`);
    if (!tv.spor) adv.push(`${id}: mangler spor`);
    ruter.push({id, retning: rolle, linje, spor: tv.spor || "",
                start: tv.start,
                veksler: (tv.sporveksler || []).filter(v => v.sporveksel)
                  .map(v => v.sporveksel + (v.stilling === "avvik" ? "a" : "n"))});
  });

  const cmp = (a, b) => a.localeCompare(b, "no", {numeric: true});
  const ender = HALFN.filter(f => f.type === "sporfelt" &&
                                  f.rolle === "linjefelt").map(f => f.id);
  ruter.forEach(r => { if (r.linje && !ender.includes(r.linje))
                         ender.push(r.linje); });
  ender.sort(cmp);
  const spor = HALFN.filter(f => f.type === "sporfelt" &&
                                 f.rolle === "togspor").map(f => f.id);
  ruter.forEach(r => { if (r.spor && !spor.includes(r.spor))
                         spor.push(r.spor); });
  spor.sort(cmp);

  if (!spor.length || !ender.length) {
    el.textContent = "(skissen tegnes når togveier med togspor og " +
                     "linjefelt er definert)";
    document.getElementById("fr-tegn").innerHTML = "";
    advEl.innerHTML = adv.map(a => "⚠ " + a).join("<br>");
    return;
  }
  // Endene plasseres etter linjefeltets «side» (settes i HAL);
  // uten side brukes alfabetisk rekkefølge
  let vEnde = ender.find(e => feltAv(e).side === "v") || null;
  let hEnde = ender.find(e => e !== vEnde && feltAv(e).side === "h") || null;
  if (!vEnde) vEnde = ender.find(e => e !== hEnde);
  if (!hEnde) hEnde = ender.find(e => e !== vEnde) || null;
  const utenfor = ender.filter(e => e !== vEnde && e !== hEnde);
  if (utenfor.length)
    adv.push(`flere enn to linjefelt (${utenfor.join(", ")}) — ` +
             `de vises ikke i skissen`);

  const rFor = (linje, sp, retning) => ruter.filter(r =>
    r.linje === linje && r.spor === sp && r.retning === retning);

  // konfliktsjekk: SAMME komplette vekselsett fra samme ende og
  // retning kan ikke føre til ULIKE spor (enkeltveksler kan gjerne
  // deles — det er kombinasjonen som må være entydig)
  const brukt = {};
  ruter.forEach(r => {
    if (!r.linje || !r.spor) return;
    const k = r.linje + "|" + r.retning + "|" +
              r.veksler.slice().sort().join("+");
    (brukt[k] = brukt[k] || new Set()).add(r.spor);
  });
  for (const [k, s] of Object.entries(brukt)) {
    if (s.size > 1) {
      const [linje, , vlist] = k.split("|");
      adv.push(`vekselstillingene [${vlist || "ingen"}] fra ${linje} ` +
               `fører til FLERE spor (${[...s].join(", ")}) — ` +
               `sjekk stillingene`);
    }
  }

  // mangel-advarsler (per spor og ende)
  const knapp = (linje, sp, retning) =>
    ` <button class="mini" onclick="frOpprett('` +
    `${linje.replace(/'/g, "\\'")}','${sp.replace(/'/g, "\\'")}',` +
    `'${retning}')">opprett</button>`;
  spor.forEach(sp => {
    for (const linje of [vEnde, hEnde]) {
      if (!linje) continue;
      if (!rFor(linje, sp, "innkjor").length)
        adv.push(`${sp}: mangler innkjørtogvei fra ${linje}` +
                 knapp(linje, sp, "innkjor"));
      if (!rFor(linje, sp, "utkjor").length)
        adv.push(`${sp}: mangler utkjørtogvei mot ${linje}` +
                 knapp(linje, sp, "utkjor"));
    }
  });

  // ---- sporplan-tegning ----
  // Signalplassering: innkjør og FELLES utkjør (flere spor) ved enden;
  // utkjørsignal for ETT spor tegnes på sporlinjen.
  const sigEnde = {};   // ende -> {inn:[], ut:[]}
  [vEnde, hEnde].filter(Boolean).forEach(e => sigEnde[e] = {inn: [], ut: []});
  const sigSpor = {};   // spor -> {v:[], h:[]}
  const utPerSig = {};
  ruter.forEach(r => {
    if (!r.linje) return;
    if (r.retning === "innkjor" && sigEnde[r.linje] &&
        !sigEnde[r.linje].inn.includes(r.start))
      sigEnde[r.linje].inn.push(r.start);
    if (r.retning === "utkjor")
      (utPerSig[r.start] = utPerSig[r.start] ||
        {spor: new Set(), linje: r.linje}).spor.add(r.spor);
  });
  for (const [sig, o] of Object.entries(utPerSig)) {
    if (o.spor.size > 1) {
      if (sigEnde[o.linje] && !sigEnde[o.linje].ut.includes(sig))
        sigEnde[o.linje].ut.push(sig);
    } else if (o.linje === vEnde || o.linje === hEnde) {
      const side = o.linje === vEnde ? "v" : "h";
      const sp = [...o.spor][0];
      ((sigSpor[sp] = sigSpor[sp] || {v: [], h: []})[side]).push(sig);
    }
  }
  // veksler per spor og side
  const vxSpor = {};
  ruter.forEach(r => {
    if (!r.spor || !r.linje) return;
    const side = r.linje === vEnde ? "v" : r.linje === hEnde ? "h" : null;
    if (!side) return;
    const o = vxSpor[r.spor] = vxSpor[r.spor] || {v: new Set(), h: new Set()};
    r.veksler.forEach(v => o[side].add(v));
  });
  // hovedspor = færrest avvik (rett gjennomkjøring); resten er grener
  const avvikTall = sp => ruter.filter(r => r.spor === sp)
    .reduce((n, r) => n + r.veksler.filter(v => v.endsWith("a")).length, 0);
  const hovedSpor = spor.slice().sort((a, b) =>
    avvikTall(a) - avvikTall(b) || cmp(a, b))[0];
  const grener = spor.filter(s => s !== hovedSpor);

  // Forsignaler: montert = på vertssignalets mast (vises som +F▷),
  // frittstående = ute på linjen FORAN innkjørsignalet. Hovedsignal
  // ▶/◀, forsignal ▷/◁ (hul pil), i kjøreretningen de gjelder.
  const forsignaler = HALFN.filter(f =>
    sigKlasse(f.type) === "forsignal");
  const sigFinnes = id => !!HALFN.find(f => f.id === id &&
    erHoved(f.type));
  const montertPaa = {}, frittFor = {};
  forsignaler.forEach(fs => {
    if (fs.montert_med) {
      if (!sigFinnes(fs.montert_med))
        adv.push(`forsignal ${fs.id}: montert med «${fs.montert_med}» — ` +
                 `finnes ikke som hovedsignal`);
      else (montertPaa[fs.montert_med] =
              montertPaa[fs.montert_med] || []).push(fs.id);
    } else if (fs.varsler_om) {
      if (!sigFinnes(fs.varsler_om))
        adv.push(`forsignal ${fs.id}: varsler om «${fs.varsler_om}» — ` +
                 `finnes ikke som hovedsignal`);
      else (frittFor[fs.varsler_om] =
              frittFor[fs.varsler_om] || []).push(fs.id);
    }
  });
  const sigTok = (sig, retn) => {   // retn "h" = peker mot høyre
    let t = retn === "h" ? sig + " ▶" : "◀ " + sig;
    (montertPaa[sig] || []).forEach(fs =>
      t += " " + (retn === "h" ? fs + " ▷" : "◁ " + fs));
    return t;
  };
  const fsTok = (fs, retn) => retn === "h" ? fs + " ▷" : "◁ " + fs;
  // varselfelt: korte felt ute på linjen, utenfor forsignalet —
  // koblet til sitt linjefelt (arver siden derfra)
  const varselfelt = HALFN.filter(f => f.type === "sporfelt" &&
                                      f.rolle === "varselfelt");
  varselfelt.forEach(m => {
    if (!m.linjefelt || feltAv(m.linjefelt).rolle !== "linjefelt")
      adv.push(`varselfelt ${m.id}: mangler kobling til linjefelt — ` +
               `varslet vet ikke hvilken side det gjelder`);
  });

  const sporTekst = sp => {
    const o = vxSpor[sp] || {v: new Set(), h: new Set()};
    const sg = sigSpor[sp] || {v: [], h: []};
    const midt = [];
    if (sg.v.length) midt.push(sg.v.map(s => sigTok(s, "v")).join(" "));
    midt.push(sp);
    if (sg.h.length) midt.push(sg.h.map(s => sigTok(s, "h")).join(" "));
    const deler = [];
    if (o.v.size) deler.push([...o.v].sort(cmp).join(","));
    deler.push("── " + midt.join(" ") + " ──");
    if (hEnde && o.h.size) deler.push([...o.h].sort(cmp).join(","));
    return deler.join(" ");
  };
  // Rekkefølgen fra linjen og innover mot togsporene: frittstående
  // forsignal — innkjørsignal — LINJEFELTET (som jo er strekningen
  // innenfor innkjørsignalet, dvs. signalfallfeltet) — utkjørsignal
  // ved feltets indre ende.
  const endeTekst = (ende, side) => {
    const sv = sigEnde[ende] || {inn: [], ut: []};
    const fritt = [];
    sv.inn.forEach(s => (frittFor[s] || []).forEach(fs => fritt.push(fs)));
    const mf = varselfelt.filter(m => m.linjefelt === ende).map(m => m.id);
    const d = [];
    if (side === "v") {
      mf.forEach(m => d.push(m));            // ytterst på linjen
      fritt.forEach(fs => d.push(fsTok(fs, "h")));
      sv.inn.forEach(s => d.push(sigTok(s, "h")));
      d.push(ende);
      sv.ut.forEach(s => d.push(sigTok(s, "v")));
      return "── " + d.join(" ── ") + " ──";
    }
    sv.ut.forEach(s => d.push(sigTok(s, "h")));
    d.push(ende);
    sv.inn.forEach(s => d.push(sigTok(s, "v")));
    fritt.forEach(fs => d.push(fsTok(fs, "v")));
    mf.forEach(m => d.push(m));              // ytterst på linjen
    return "── " + d.join(" ── ") + " ──";
  };
  const senter = (s, w, fyll) => {
    const tot = Math.max(0, w - s.length);
    const l = Math.floor(tot / 2);
    return fyll.repeat(l) + s + fyll.repeat(tot - l);
  };
  const nBr = grener.length;
  const W = Math.max(...spor.map(s => sporTekst(s).length)) + 2;
  const margL = endeTekst(vEnde, "v");
  const margR = hEnde ? endeTekst(hEnde, "h") : " ┤";
  const M = margL.length;
  const linjer = [];
  for (let j = nBr - 1; j >= 0; j--) {   // øverst = ytterste gren
    const stolper = "│".repeat(nBr - 1 - j);
    let rad = " ".repeat(M) + stolper + "┌" +
              senter(sporTekst(grener[j]), W + 2 * j, "─");
    rad += hEnde ? "┐" + stolper : "┤";
    linjer.push(rad);
  }
  let hoved = margL + "┴".repeat(nBr) +
              senter(sporTekst(hovedSpor), W, "─");
  hoved += hEnde ? "┴".repeat(nBr) + margR : margR;
  linjer.push(hoved);

  // Fargekoding: alle kjente tokens (lengst først, én passering så
  // korte litra aldri treffer inne i lengre). Justeringen er alt
  // beregnet på ren tekst — span-ene endrer ikke tegnbredder.
  const tokKart = [];
  HALFN.forEach(f => {
    if (erHoved(f.type)) {
      tokKart.push([f.id + " ▶", "sk-hs"], ["◀ " + f.id, "sk-hs"]);
    } else if (sigKlasse(f.type) === "forsignal") {
      tokKart.push([f.id + " ▷", "sk-fs"], ["◁ " + f.id, "sk-fs"]);
    } else if (f.type === "sporfelt" && f.rolle === "togspor") {
      tokKart.push([f.id, "sk-ts"]);
    } else if (f.type === "sporfelt" && f.rolle === "linjefelt") {
      tokKart.push([f.id, "sk-lf"]);
    } else if (f.type === "sporfelt" && f.rolle === "varselfelt") {
      tokKart.push([f.id, "sk-mf"]);
    } else if (isNoenVeksel(f.type)) {
      tokKart.push([f.id + "n", "sk-vx"], [f.id + "a", "sk-vx"]);
    }
  });
  tokKart.sort((a, b) => b[0].length - a[0].length);
  const kls = {};
  tokKart.forEach(([t, c]) => { if (!(t in kls)) kls[t] = c; });
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;");
  if (tokKart.length) {
    const rx = new RegExp(tokKart.map(([t]) =>
      t.replace(/[.*?^$()|[\\]{}\\\\]/g, "\\\\$&")).join("|"), "g");
    el.innerHTML = esc(linjer.join("\\n")).replace(rx, m =>
      '<span class="' + kls[m] + '">' + m + "</span>");
  } else {
    el.textContent = linjer.join("\\n");
  }
  document.getElementById("fr-tegn").innerHTML =
    '<span class="sk-hs">hovedsignal</span> · ' +
    '<span class="sk-fs">forsignal</span> · ' +
    '<span class="sk-ts">togspor</span> · ' +
    '<span class="sk-lf">linjefelt</span> · ' +
    '<span class="sk-mf">varselfelt</span> · ' +
    '<span class="sk-vx">sporveksel</span>';
  const unike = [...new Set(adv)];
  advEl.innerHTML = unike.length
    ? unike.map(a => "⚠ " + a).join("<br>")
    : `<span class="on">✓ alle togspor har togveier i begge retninger</span>`;
}

function frKonflikter() {
  const out = [];
  for (let a = 0; a < TOGVEIER.length; a++) {
    for (let b = a + 1; b < TOGVEIER.length; b++) {
      const A = TOGVEIER[a], B = TOGVEIER[b], grunner = [];
      const feltA = new Set(A.frie || []);
      for (const sf of B.frie || [])
        if (feltA.has(sf)) grunner.push("felles sporfelt " + sf);
      for (const va of A.sporveksler || [])
        for (const vb of B.sporveksler || [])
          if (va.sporveksel && va.sporveksel === vb.sporveksel &&
              va.stilling !== vb.stilling)
            grunner.push(`${va.sporveksel} i ulik stilling`);
      if (A.start && A.start === B.start) grunner.push("samme startsignal");
      if (grunner.length)
        out.push(`<b>${A.id||"?"} × ${B.id||"?"}</b>: ${grunner.join(", ")}`);
    }
  }
  document.getElementById("fr-konflikter").innerHTML = out.length
    ? `<div class="card"><h2>Fiendtlige togveier (utledet)</h2>
       <p class="hint">${out.join("<br>")}</p></div>`
    : (TOGVEIER.length > 1
       ? `<p class="hint">Ingen konflikter utledet av tabellen.</p>` : "");
}
function frAdd() {
  const mangler = frKrav();
  if (mangler.length) {
    toast("Togveier trenger minst " + mangler.join(", ") +
          " — legg til under Objekter først.", true);
    return;
  }
  TOGVEIER.push({id:"", start:"", spor:"",
                 veksler:[], frie:[], utlosningsfelt:"", notes:""});
  frRender();
}
function frOpprett(linje, sp, retning) {
  const fra = retning === "innkjor" ? linje : sp;
  const til = retning === "innkjor" ? sp : linje;
  const mot = TOGVEIER.find(tv => tv.fra === til && tv.til === fra);
  TOGVEIER.push({id: "", start: "", spor: "", fra: fra, til: til,
                 frie: [], utlosningsfelt: "", notes: "",
                 sporveksler: (mot && mot.sporveksler || []).map(v =>
                   ({sporveksel: v.sporveksel, stilling: v.stilling}))});
  frRender();   // signal, ID, frie og utløsning avledes av endene
}
function frAutoFyll(i) {
  const a = frAutoFelt(TOGVEIER[i]);
  if (!a) {
    toast("Velg startsignal, spor og minst én veksel først — feltene " +
          "avledes av endene.", true);
    return;
  }
  TOGVEIER[i].frie = a.frie;
  TOGVEIER[i].utlosningsfelt = a.utlos;
  frRender();
}
async function frSave() {
  const msg = document.getElementById("fr-msg");
  // Betjeningen er stiller-avledet — gamle knappefelter ryddes bort
  TOGVEIER.forEach(tv => { delete tv.startknapp; delete tv.sluttknapp;
                           delete tv.signalfall; });
  // ID-ene genereres av rute-endene; ufullstendige rader beholder
  // evt. gammel ID til endene er valgt
  for (const tv of TOGVEIER) {
    frEnder(tv);
    if ((tv.fra || tv.til) && !frRetning(tv)) {
      msg.textContent = `Togvei ${tv.id || tv.fra + "→" + tv.til}: ` +
        `endene må være linjefelt→togspor (innkjør), ` +
        `togspor→linjefelt (utkjør) eller togspor→togspor (indre)`;
      msg.className = "err";
      return;
    }
    if (frRetning(tv) && !tv.start) {
      msg.textContent = `Togvei ${frGenId(tv)}: mangler hovedsignal — ` +
        `sett rolle/linjefelt på signalet under Objekter`;
      msg.className = "err";
      return;
    }
  }
  const sett = new Set();
  for (const tv of TOGVEIER) {
    const g = frGenId(tv);
    if (g) tv.id = g;
    if (tv.id) {
      if (sett.has(tv.id)) {
        msg.textContent = `To togveier får samme ID (${tv.id}) — samme ` +
          `retning, linjefelt og spor. Slett duplikatet.`;
        msg.className = "err";
        return;
      }
      sett.add(tv.id);
    }
  }
  frRender();
  const r = await fetch("/api/forrigling", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({togveier: TOGVEIER})});
  const j = await apiJson(r);
  if (!r.ok) { msg.textContent = j.error; msg.className = "err"; return; }
  msg.textContent = "Lagret og publisert " + j.version;
  msg.className = "ok";
  for (let i = 0; i < 10; i++) {
    await new Promise(res => setTimeout(res, 1000));
    const a = await (await fetch("/api/forrigling-ack")).json();
    if (a.version === j.version) {
      msg.textContent =
        `Lagret — master kvitterte ${j.version} (${a.togveier} togveier)`;
      return;
    }
  }
  msg.textContent += " — venter fortsatt på master-kvittering";
}

async function lampTest(action) {
  await fetch("/api/lamptest", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action})});
  setTimeout(renderNoder, 300);
}
async function findNode(mac) {
  await fetch("/api/find", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac})});
}
async function forgetNode(mac) {
  const alias = aliasFor(mac);
  if (!confirm(`Fjerne node ${alias || mac}?\\n\\nRetained-temaer slettes og ` +
               `noden forsvinner fra oversikten. En node som fortsatt er i ` +
               `drift vil melde seg inn igjen av seg selv.`)) return;
  await fetch("/api/forget", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({mac})});
  setTimeout(renderNoder, 1500);
}

// Stille klokkeinnmelding: denne enheten har (antagelig) riktig tid.
// Pi-en justerer seg bare ved stort avvik uten NTP — se /api/klokke.
async function klokkeSjekk() {
  try {
    await fetch("/api/klokke", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({epoch_ms: Date.now()})});
  } catch (e) { /* Pi-en svarer ikke — pytt */ }
}

loadAll();
renderNoder();   // System-fanen er synlig fra start
klokkeSjekk();
setInterval(klokkeSjekk, 300000);
setInterval(async () => {
  const nodes = await (await fetch("/api/nodes")).json();
  liveNodes = nodes.nodes || [];
  STATUS.noder = liveNodes.filter(n => n.online).length;
  oppdaterStatus();
  // Lampeprøve-banner på ALLE faner: prøven eier lampene i inntil
  // 10 min — det skal være umulig å glemme at den står på
  try {
    const lt = await (await fetch("/api/lamptest")).json();
    const b = document.getElementById("lpbanner");
    if (lt.running) {
      const igjen = lt.start_ts
        ? Math.max(0, 600 - Math.round(Date.now() / 1000 - lt.start_ts)) : null;
      document.getElementById("lpbanner-txt").textContent =
        (lt.progress || "") +
        (igjen != null ? ` · sikkerhetsstopp om ${Math.floor(igjen / 60)}:` +
          String(igjen % 60).padStart(2, "0") : "");
      b.style.display = "";
    } else {
      b.style.display = "none";
    }
  } catch (e) {}
  // Testmodus-banner på ALLE faner: en sikkerhetsomgåelse som står
  // på skal være umulig å overse, uansett hvilken fane man er på
  try {
    // Master er fasiten: den kan kjøre testmodus fra sitt eget flash
    // uten at Pi-ens anlegg.json vet om det. Lokal konfig er reserve
    // for tilfellet master ikke har meldt seg ennå.
    const m = await (await fetch("/api/master")).json();
    let paa = m.testmodus === "paa";
    if (m.testmodus == null) {
      const an = await (await fetch("/api/anlegg")).json();
      paa = !!an.testmodus;
    }
    document.getElementById("testbanner").style.display = paa ? "" : "none";
  } catch (e) {}
  if (currentView === "noder") {
    // Ikke tegn på nytt mens brukeren skriver i et felt på fanen
    const ae = document.activeElement;
    if (ae && ae.tagName === "INPUT" && ae.closest("#view-noder")) return;
    renderNoder();
  }
}, 3000);
</script></body></html>"""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


# Alt er definert — nå kan nettverkstråden trygt kalle on_connect,
# som re-hevder konfigen (se hevd_konfig).
mq.connect_async(MQTT_HOST, 1883, 60)
mq.loop_start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

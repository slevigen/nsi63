"""MQTT-basert kontraktstest for forriglingsmotoren.

Kjører mot en EKTE master over anleggets MQTT-broker — ingen mocking,
ingen refaktorering av firmware: suiten bruker nøyaktig samme flate
som HAL-UI-et og et fremtidig digitalt stillerapparat vil bruke
(togvei/<id>/set, sporveksel/<litra>/set, sporfelt/<litra>/sim,
signalstopp/sim, …). Den er dermed også API-KONTRAKTEN for panelet.

Bruk (Mac-en på NSI63-nettet, eller på Pi-en):

    pip install pytest paho-mqtt
    cd nsi63-pi/mqtt-test
    pytest -v                        # broker på 10.206.0.1
    NSI63_HOST=127.0.0.1 pytest -v   # kjørt på selve Pi-en

Forutsetninger: Pi + master i drift på benken (IKKE på et anlegg i
trafikk — suiten stiller og river togveier og simulerer belegg),
testmodus AV, og konfig lastet (suiten leser sin topologi fra
../hal-ui/hal.json og forrigling.json, overstyr mappen med
NSI63_KONFIG). Suiten rydder anlegget før hver test og etter siste.
"""
import json
import os
import threading
import time
from pathlib import Path

import pytest

try:
    import paho.mqtt.client as mqtt
except ImportError:
    pytest.exit("paho-mqtt mangler:  pip install paho-mqtt", 1)

ROT = "nsi63/"
HOST = os.environ.get("NSI63_HOST", "10.206.0.1")
KONFIG = Path(os.environ.get(
    "NSI63_KONFIG", Path(__file__).resolve().parent.parent / "hal-ui"))

SIKRING_S = 20     # sikring inkl. sekvensiell vekselomlegging
KORT_S = 5         # enkeltsvar (info-meldinger, tilstandsskift)


# ---------- topologi fra konfigfilene ----------

class Topo:
    def __init__(self):
        # En fersk installasjon har ingen konfig ennå — anlegget bygges
        # i HAL-UI. Da har suiten ingen topologi å teste mot, og skal
        # si det, ikke velte med FileNotFoundError.
        for navn in ("hal.json", "forrigling.json"):
            if not (KONFIG / navn).exists():
                pytest.skip(f"fant ingen {navn} i {KONFIG} — sett opp "
                            f"anlegget i HAL-UI først, eller pek "
                            f"NSI63_KONFIG mot en ferdig konfigmappe "
                            f"(f.eks. hal-ui/eksempler/grindvoll)")
        hal = json.loads((KONFIG / "hal.json").read_text())
        fr = json.loads((KONFIG / "forrigling.json").read_text())
        # NB: litra er unik PER OBJEKTKLASSE, ikke globalt — hovedsignal
        # A og sporfelt A (linjefeltet) sameksisterer. Typede oppslag,
        # aldri én felles id-tabell.
        alle = hal["functions"]
        self.felt = {f["id"]: f for f in alle
                     if f.get("type") == "sporfelt"}
        self.laaser = [f for f in alle if f.get("type") == "samlelaas"]
        self.rigler = [f for f in alle if f.get("type") == "rigel"]
        self.sperrer_obj = [f for f in alle if f.get("type") == "sporsperre"]
        hoved = {f["id"]: f for f in alle
                 if str(f.get("type", "")).startswith("hovedsignal")}
        self.hoved = hoved
        self.forsignaler = [f for f in alle
                            if str(f.get("type", "")).startswith("forsignal")]
        self.skiftesignaler = [
            f for f in alle
            if str(f.get("type", "")).startswith("skiftesignal")]
        self.togveier = []
        for tv in fr.get("togveier", []):
            start = hoved.get(tv.get("start"))
            linje = next((x for x in tv.get("frie", [])
                          if self.felt.get(x, {}).get("rolle")
                          == "linjefelt"), None)
            self.togveier.append({
                "id": tv["id"], "start": tv.get("start"),
                "retning": (start or {}).get("rolle"),   # innkjor/utkjor
                "spor": tv.get("spor"), "frie": tv.get("frie", []),
                "utlos": tv.get("utlosningsfelt"),
                "sporveksler": tv.get("sporveksler", []),
                # Låsegruppene togveien krever sperret. Håndstilte
                # veksler står ikke i «sporveksler» — de kan ikke
                # kommanderes — så det er HER de kommer inn.
                "laaser": tv.get("laaser", []),
                "linjefelt": linje,
                "uten_linjeblokk": bool(
                    linje and self.felt[linje].get("linjeblokk") is False),
            })
        if not self.togveier:
            pytest.exit("forrigling.json har ingen togveier — suiten "
                        "trenger et konfigurert anlegg", 1)

    def innkjor(self):
        tv = next((t for t in self.togveier if t["retning"] == "innkjor"
                   and t["sporveksler"]), None)
        return tv or pytest.skip("ingen innkjørtogvei med veksler i konfig")

    def sistevogn_tv(self):
        tv = next((t for t in self.togveier if t["retning"] == "innkjor"
                   and t["uten_linjeblokk"] and t["utlos"]), None)
        return tv or pytest.skip("ingen innkjørtogvei uten linjeblokk")

    def fiendtlig_par(self):
        for a in self.togveier:
            for b in self.togveier:
                if a["id"] != b["id"] and set(a["frie"]) & set(b["frie"]):
                    return a, b
        pytest.skip("fant ikke fiendtlig togveipar i konfig")

    def samlelaas(self):
        """En samlelås, helst med objekter i virkeområdet."""
        l = next((x for x in self.laaser if x.get("omfatter")),
                 self.laaser[0] if self.laaser else None)
        return l or pytest.skip("ingen samlelaas i konfig")

    def _laas_togvei(self, gruppe, hva):
        """(lås, togvei) der togveien KREVER låsen sperret.

        Relasjonen står i TOGVEIEN, ikke i låsen: hver togvei lister
        låsegruppene den trenger garantert («laaser»). Det er slik en
        håndstilt veksel kommer inn i forriglingen — anlegget kan ikke
        kaste den, men låsen som holder den garanterer stillingen, og
        DEN kan anlegget kreve.
        """
        for l in gruppe:
            for tv in self.togveier:
                if l["id"] in (tv.get("laaser") or []):
                    return l, tv
        pytest.skip(f"ingen {hva} som kreves av noen togvei i konfig "
                    f"(sett «Krever låst» på en togvei i Forrigling)")

    def samlelaas_togvei(self):
        return self._laas_togvei(self.laaser, "samlelaas")

    def rigel(self):
        """En rigel, helst med objekter i virkeområdet."""
        l = next((x for x in self.rigler if x.get("omfatter")),
                 self.rigler[0] if self.rigler else None)
        return l or pytest.skip("ingen rigel i konfig")

    def rigel_togvei(self):
        return self._laas_togvei(self.rigler, "rigel")

    def er_sporsperre(self, litra):
        return any(s["id"] == litra for s in self.sperrer_obj)

    def skift_med_veksel(self):
        """(skiftesignal-litra, veksel-litra) der vekselen i skifte-
        området er sentralstilt (i togveier, ikke låst av samlelås/
        rigel) — så omlegging fra panelet er lov mens skiftingen
        pågår."""
        laast = set()
        for f in self.laaser + self.rigler:
            laast |= {str(o) for o in (f.get("omfatter") or [])}
        tv_veksler = {v["sporveksel"] for t in self.togveier
                      for v in t["sporveksler"]}
        for sk in self.skiftesignaler:
            for v in sk.get("skift_sporveksler") or []:
                if str(v) in tv_veksler and str(v) not in laast:
                    return sk["id"], str(v)
        pytest.skip("ingen skiftesignal med sentralstilt veksel")

    def forsignal_gating(self):
        """(forsignal, innkjørtogvei, utkjør ANNET spor, utkjør SAMME
        spor) for et montert forsignal som varsler om et FELLES
        utkjørsignal — sporgating-kontrakten. Utkjøringen fra det
        andre sporet må være forenlig med innkjøringen (disjunkte
        frie-felt og veksler), ellers kan de ikke stå samtidig."""
        for fs in self.forsignaler:
            vert = self.hoved.get(fs.get("montert_med") or "")
            u = self.hoved.get(fs.get("varsler_om") or "")
            if not vert or vert.get("rolle") != "innkjor":
                continue
            if not u or u.get("rolle") != "utkjor":
                continue
            tv_i = next((t for t in self.togveier
                         if t["retning"] == "innkjor"
                         and t["start"] == vert["id"]), None)
            if not tv_i:
                continue
            uts = [t for t in self.togveier if t["start"] == u["id"]]
            ut_samme = next((t for t in uts
                             if t["spor"] == tv_i["spor"]), None)
            v_i = {v["sporveksel"] for v in tv_i["sporveksler"]}
            ut_annen = next(
                (t for t in uts if t["spor"] != tv_i["spor"]
                 and not (set(t["frie"]) & set(tv_i["frie"]))
                 and not ({v["sporveksel"]
                           for v in t["sporveksler"]} & v_i)),
                None)
            if ut_samme and ut_annen:
                return fs, tv_i, ut_annen, ut_samme
        pytest.skip("ingen montert forsignal mot felles utkjørsignal")

    def stiller_tv(self):
        """Innkjørtogvei der stillerdytt kan brukes: linjefeltet har
        side (v/h) og sporet er et togspor med stillere i tabellen."""
        tv = next((t for t in self.togveier
                   if t["retning"] == "innkjor" and t["linjefelt"]
                   and self.felt[t["linjefelt"]].get("side") in ("v", "h")
                   and self.felt.get(t["spor"], {}).get("rolle")
                   == "togspor"), None)
        return tv or pytest.skip("ingen innkjørtogvei med linjefelt-side")


# ---------- anleggs-klienten ----------

class Anlegg:
    def __init__(self):
        self._cv = threading.Condition()
        self.tilstand = {}          # tema (uten rot) -> siste payload
        self.logg = []              # (ts, tema, payload) — også transiente
        try:
            self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.mq = mqtt.Client()
        self.mq.on_message = self._melding
        try:
            self.mq.connect(HOST, 1883, keepalive=15)
        except OSError as e:
            pytest.skip(f"ingen MQTT-broker på {HOST}: {e}")
        self.mq.subscribe(ROT + "#")
        self.mq.loop_start()
        time.sleep(2.0)             # la retained tilstand strømme inn
        if self.tilstand.get("master/status") != "online":
            pytest.skip("master er ikke online på brokeren — "
                        "suiten krever levende anlegg")

    def _melding(self, client, userdata, msg):
        tema = msg.topic[len(ROT):]
        pl = msg.payload.decode("utf-8", "replace")
        with self._cv:
            self.tilstand[tema] = pl
            self.logg.append((time.time(), tema, pl))
            del self.logg[:-500]
            self._cv.notify_all()

    def pub(self, tema, payload):
        self.mq.publish(ROT + tema, payload)

    def naa(self):
        return time.time()

    def vent(self, tema, godtatt, timeout=KORT_S):
        """Vent til siste payload på tema er blant de godtatte."""
        if isinstance(godtatt, str):
            godtatt = (godtatt,)
        frist = time.time() + timeout
        with self._cv:
            while time.time() < frist:
                if self.tilstand.get(tema) in godtatt:
                    return self.tilstand[tema]
                self._cv.wait(0.2)
        pytest.fail(f"{tema} ble aldri {godtatt} (er: "
                    f"{self.tilstand.get(tema)!r}) innen {timeout} s")

    def vent_ny(self, tema, delstreng, etter, timeout=KORT_S):
        """Vent på en melding på tema, publisert ETTER tidspunktet
        `etter`, som inneholder delstrengen. For transiente
        info-meldinger der bare-siste-payload ikke er nok."""
        frist = time.time() + timeout
        with self._cv:
            while time.time() < frist:
                for ts, t, pl in reversed(self.logg):
                    if ts >= etter and t == tema and delstreng in pl:
                        return pl
                self._cv.wait(0.2)
        pytest.fail(f"ingen melding på {tema} med «{delstreng}» "
                    f"innen {timeout} s")

    def rydd(self, topo):
        """Nullstill anlegget: simene av, alle togveier løses ut."""
        self.pub("signalstopp/sim", "auto")
        self.pub("frigivning/v/sim", "auto")
        self.pub("frigivning/h/sim", "auto")
        for l in topo.laaser:                    # tilbake til sperret
            self.pub(f"samlelaas/{l['id']}/sim", "auto")
            self.pub(f"samlelaas/{l['id']}/set", "sperr")
        # Riglene: objektene tilbake i normalstilling, så sperring.
        # Tilbaketakingen har 10 s etterløp — vent bare når rigelen
        # faktisk sto frigitt (ellers koster hver test 10 s uansett).
        rigel_vent = []
        for r in topo.rigler:
            st = self.tilstand.get(f"rigel/{r['id']}/state")
            if st is None or st == "sperret":
                continue
            for obj in r.get("omfatter") or []:
                if topo.er_sporsperre(obj):
                    self.pub(f"sporsperre/{obj}/set", "paalagt")
                else:
                    self.pub(f"sporveksel/{obj}/set", "normal")
            self.pub(f"rigel/{r['id']}/set", "sperr")
            rigel_vent.append(r["id"])
        for rid in rigel_vent:
            self.vent(f"rigel/{rid}/state", "sperret", timeout=15)
        self.pub("jord/sim", "trykk")       # ufarlig når sperren ikke står
        # «fri» FØR «av»: et felt uten sensorer beholder siste tilstand
        # når simuleringen slippes (ingen sensor kan friskmelde det) —
        # uten fri-steget ble et testbelagt felt stående belagt og
        # avviste alle senere sikringer. Med sensorer tar de over ved
        # «av» som før.
        for fid in topo.felt:
            self.pub(f"sporfelt/{fid}/sim", "fri")
        for fid in topo.felt:
            self.pub(f"sporfelt/{fid}/sim", "av")
        time.sleep(0.5)
        for tv in topo.togveier:
            self.pub(f"togvei/{tv['id']}/set", "kvitter")   # ev. klar-utlos
            self.pub(f"togvei/{tv['id']}/set", "stopp")     # trinn 1
        time.sleep(0.5)
        for tv in topo.togveier:
            self.pub(f"togvei/{tv['id']}/set", "hjelpeutlos")  # trinn 2
        for tv in topo.togveier:
            self.vent(f"togvei/{tv['id']}/state", "ledig", timeout=10)


@pytest.fixture(scope="session")
def topo():
    return Topo()


@pytest.fixture(scope="session")
def anlegg(topo):
    a = Anlegg()
    yield a
    a.rydd(topo)                    # forlat benken ryddig
    a.mq.loop_stop()
    a.mq.disconnect()


@pytest.fixture(autouse=True)
def rent_anlegg(anlegg, topo):
    anlegg.rydd(topo)
    yield

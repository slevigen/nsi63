"""Felles oppsett for de maskinvarefrie testene av HAL-UI (app.py).

Hver test får sin EGEN kopi av app.py i en midlertidig mappe. App-en
finner alle filene sine relativt til seg selv (hal.json,
forrigling.json, anlegg.json, ui/, panelfilene, hendelsesloggen), så en
kopi gjør at testene aldri rører repoets konfig, og at hver test
starter fra en kjent tilstand.

MQTT byttes ut med en falsk klient FØR importen: app.py oppretter
klienten og kaller connect_async/loop_start på modulnivå. Den falske
klienten husker hva som publiseres, så testene kan sjekke det masteren
og panelet ville fått retained.

Dette er IKKE det samme som ../../mqtt-test/, som kjører mot en ekte
master. Disse testene trenger verken broker eller maskinvare.

    pytest nsi63-pi/hal-ui/tests
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import paho.mqtt.client as paho
import pytest

HAL_UI = Path(__file__).resolve().parent.parent
EKSEMPLER = HAL_UI / "eksempler"
KONFIGFILER = ("hal.json", "forrigling.json", "anlegg.json", "instruks.md")
# Alt app.py serverer fra sin egen mappe, utenom konfigen
KODEFILER = ("app.py", "panel.html", "mqtt.min.js")


def uten_notes(d):
    """migrate() fjerner «notes» med vilje (teksten tok plass i masterens
    16 kB-buffer). Grindvoll-eksempelet har dem som forklaring til den
    som leser filen, så sammenlikninger må se bort fra dem."""
    if isinstance(d, dict):
        return {k: uten_notes(v) for k, v in d.items() if k != "notes"}
    if isinstance(d, list):
        return [uten_notes(v) for v in d]
    return d


class FalskMqtt:
    """Nok av paho-klienten til at app.py kan importeres og kjøres."""

    def __init__(self, *a, **kw):
        self.publisert = []          # (tema, nyttelast, retain)
        self.retained = {}           # tema -> siste retained nyttelast
        self.on_connect = None
        self.on_message = None

    def publish(self, tema, nyttelast=None, qos=0, retain=False, **kw):
        if isinstance(nyttelast, bytes):
            nyttelast = nyttelast.decode("utf-8")
        self.publisert.append((tema, nyttelast, retain))
        if retain:
            self.retained[tema] = nyttelast

        class Info:
            rc = 0
        return Info()

    def subscribe(self, *a, **kw):
        return (0, 1)

    def connect_async(self, *a, **kw):
        pass

    def loop_start(self):
        pass

    def retained_json(self, tema):
        return json.loads(self.retained[tema])


class Hal:
    """En kjørende app-kopi: modul, Flask-klient og falsk MQTT."""

    def __init__(self, modul, mappe):
        self.app = modul
        self.mappe = mappe
        self.klient = modul.app.test_client()
        self.mq = modul.mq

    def fil(self, navn, uten_notater=False):
        d = json.loads((self.mappe / navn).read_text(encoding="utf-8"))
        return uten_notes(d) if uten_notater else d


def _lag(tmp_path, monkeypatch, konfig_fra):
    # Egen mappe per app-kopi: en test kan bruke to (f.eks. fersk og
    # sokna), og de deler tmp_path.
    mappe = tmp_path / ("nsi63-hal-" + uuid.uuid4().hex[:8])
    mappe.mkdir()
    for navn in KODEFILER:
        if (HAL_UI / navn).exists():
            shutil.copy(HAL_UI / navn, mappe / navn)
    for font in list(HAL_UI.glob("*.ttf")) + list(HAL_UI.glob("*.otf")) \
            + list(HAL_UI.glob("*-OFL.txt")) + list(HAL_UI.glob("icon*")):
        shutil.copy(font, mappe / font.name)
    shutil.copytree(HAL_UI / "ui", mappe / "ui")
    if konfig_fra is not None:
        for navn in KONFIGFILER:
            if (konfig_fra / navn).exists():
                shutil.copy(konfig_fra / navn, mappe / navn)

    monkeypatch.setattr(paho, "Client", FalskMqtt)
    navn = "nsi63_hal_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(navn, mappe / "app.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[navn] = modul
    spec.loader.exec_module(modul)

    # Lagring av anleggs-ID-en døper om AP-et og hostname via
    # systemctl/hostnamectl. Det skal aldri skje fra en test.
    kall = []

    def falsk_run(args, *a, **kw):
        kall.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(modul.subprocess, "run", falsk_run)
    # hostapd-konfigen ligger i testmappen (finnes ikke før testen lager
    # den), så en testkjøring på en ekte Pi aldri døper om AP-et
    monkeypatch.setattr(modul, "HOSTAPD_CONF", mappe / "hostapd.conf")
    # Omstartene etter svaret kjøres i en Timer-tråd. I testene fanges
    # jobbene i stedet, så de verken kjører etter at falsk_run er tatt
    # bort igjen eller gjør testene tidsavhengige: testen kjører dem selv.
    bakgrunn = []
    ekte_etter_svaret = modul._etter_svaret
    monkeypatch.setattr(modul, "_etter_svaret", bakgrunn.append)

    h = Hal(modul, mappe)
    h.subprocess_kall = kall
    h.bakgrunn = bakgrunn
    h.ekte_etter_svaret = ekte_etter_svaret
    yield h
    sys.modules.pop(navn, None)


def _krev(mappe):
    if not (mappe / "hal.json").exists():
        pytest.skip(f"{mappe.name}: konfigen finnes ikke i dette treet")
    return mappe


@pytest.fixture
def fersk(tmp_path, monkeypatch):
    """Som etter install.sh på en Pi uten konfig: ingen konfigfiler."""
    yield from _lag(tmp_path, monkeypatch, None)


@pytest.fixture
def sokna(tmp_path, monkeypatch):
    """Repoets egen anleggskonfig (fjernes i det offentlige treet)."""
    yield from _lag(tmp_path, monkeypatch, _krev(HAL_UI))


@pytest.fixture
def grindvoll(tmp_path, monkeypatch):
    """Det offentlige eksempelet i eksempler/grindvoll/."""
    yield from _lag(tmp_path, monkeypatch, _krev(EKSEMPLER / "grindvoll"))


@pytest.fixture(params=["sokna", "grindvoll"])
def anlegg(request):
    """Kjører testen én gang per kjent anleggskonfig."""
    return request.getfixturevalue(request.param)

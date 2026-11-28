"""Felles fasitdata for validerings- og avledningsregler.

Kjører 'server_og_klient'-delen av fasit_regler.json mot app.py (samme
fil kjøres i vitest mot frontendens regler.ts), pluss struktursjekk av
'klient_og_master'-delen og runde-validering av begge eksemplene
(eksempler/sokna og eksempler/grindvoll).
"""

import json
from pathlib import Path

import pytest

FASIT_FIL = Path(__file__).resolve().parent / "fasit_regler.json"
EKSEMPLER = Path(__file__).resolve().parent.parent / "eksempler"
FASIT = json.loads(FASIT_FIL.read_text(encoding="utf-8"))
SOK = FASIT["server_og_klient"]


def test_maks_litra_stemmer(fersk):
    assert fersk.app.MAX_LITRA == SOK["maks_litra"]


@pytest.mark.parametrize("rad", SOK["litra_tegn"],
                         ids=lambda r: r["litra"])
def test_litra_tegn_fasit(fersk, rad):
    assert fersk.app.litra_ugyldig(rad["litra"]) == rad["ulovlig"]


@pytest.mark.parametrize("rad", SOK["navnerom"], ids=lambda r: r["type"])
def test_navnerom_fasit(fersk, rad):
    st = fersk.app.SIGNALTYPER_DEFAULT
    assert fersk.app.litra_ns(rad["type"], st) == rad["ns"]


@pytest.mark.parametrize("case", SOK["port_konflikter"],
                         ids=lambda c: c["navn"])
def test_port_konflikter_fasit(fersk, case):
    feil = fersk.app._port_konflikter(
        case["functions"], fersk.app.SIGNALTYPER_DEFAULT, case["noder"])
    if case["forvent_feil"]:
        assert feil, f"{case['navn']}: forventet portfeil, fikk ingen"
        if case.get("hint"):
            assert any(case["hint"] in f for f in feil), feil
    else:
        assert feil == [], f"{case['navn']}: uventet feil: {feil}"


@pytest.mark.parametrize("case", SOK["togvei_id"],
                         ids=lambda c: c["forventet"])
def test_togvei_id_fasit(fersk, case):
    got = fersk.app._gen_togvei_id(
        case["tv"], SOK["togvei_id_objekter"], fersk.app.SIGNALTYPER_DEFAULT)
    assert got == case["forventet"]


def test_klient_og_master_fasit_har_gyldig_struktur():
    km = FASIT["klient_og_master"]
    assert km["fiendtlige"] and km["signalbilde"] and km["auto_felt"]
    for c in km["fiendtlige"]:
        assert isinstance(c["fiendtlig"], bool)
    for c in km["signalbilde"]:
        assert c["bilde"] in ("kjor", "kjor-redusert")
    for c in km["auto_felt"]:
        assert isinstance(c["frie"], list) and isinstance(c["utlos"], str)


@pytest.mark.parametrize("navn", ["sokna", "grindvoll"])
def test_eksempelkonfigene_er_gyldige_mot_app(fersk, navn):
    """Begge eksemplene under eksempler/ (tilgjengelige i både privat og
    offentlig tre) skal passere alle valideringer uten feil."""
    mappe = EKSEMPLER / navn
    assert (mappe / "hal.json").is_file()
    assert (mappe / "forrigling.json").is_file()
    hal = fersk.app.migrate(
        json.loads((mappe / "hal.json").read_text(encoding="utf-8")))
    fr = fersk.app.migrate_forrigling(
        json.loads((mappe / "forrigling.json").read_text(encoding="utf-8")),
        hal["functions"])
    st = hal["signaltyper"]
    assert fersk.app._port_konflikter(hal["functions"], st, hal["noder"]) == []
    assert fersk.app._topologi_feil(hal["functions"]) == []
    assert fersk.app._kapasitet_feil(hal["functions"], st) == []
    assert fersk.app._togvei_feil(fr["togveier"], hal["functions"], st) is None

"""Stillerapparatets betjening (/set) og klokken på MQTT.

Panelet (/panel) betjener Sign.stp, Jord og Lok-frigivningen over
/set. Det er en BRYTER TIL, ikke en sim: den kombineres med de fysiske
bryterne ved ELLER, og en sim (benken) overstyrer fortsatt begge.
"""
import json
import time

import pytest


def _frig(anlegg):
    return json.loads(anlegg.tilstand.get("master/frigivning") or "{}")


def _vent_frig(anlegg, felt, verdi, timeout=5):
    frist = time.time() + timeout
    while time.time() < frist:
        if _frig(anlegg).get(felt) == verdi:
            return
        time.sleep(0.1)
    pytest.fail(f"master/frigivning.{felt} ble aldri {verdi} "
                f"(er {_frig(anlegg)})")


# ---------- signalstopp ----------

def test_signalstopp_set_paa_og_av(anlegg, topo):
    tv = topo.innkjor()
    anlegg.pub("signalstopp/set", "paa")
    anlegg.vent("master/signalstopp", "paa")
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    anlegg.pub("signalstopp/set", "av")
    anlegg.vent("master/signalstopp", "av")


def test_sim_overstyrer_panelets_signalstopp(anlegg, topo):
    """Benkens sim lyver om ALLE bryterne, også panelet."""
    anlegg.pub("signalstopp/set", "paa")
    anlegg.vent("master/signalstopp", "paa")
    anlegg.pub("signalstopp/sim", "av")
    anlegg.vent("master/signalstopp", "av")
    anlegg.pub("signalstopp/sim", "auto")       # panelet står fortsatt på
    anlegg.vent("master/signalstopp", "paa")
    anlegg.pub("signalstopp/set", "av")
    anlegg.vent("master/signalstopp", "av")


def test_ukjent_signalstopp_payload_ignoreres(anlegg, topo):
    anlegg.pub("signalstopp/set", "kanskje")
    time.sleep(1)
    assert anlegg.tilstand.get("master/signalstopp") == "av"


# ---------- Lok-frigivning ----------

@pytest.mark.parametrize("ende, felt", [("v", "stiller_v"),
                                         ("h", "stiller_h")])
def test_frigivning_set_paa_og_av(anlegg, topo, ende, felt):
    anlegg.pub(f"frigivning/{ende}/set", "paa")
    _vent_frig(anlegg, felt, 1)
    anlegg.pub(f"frigivning/{ende}/set", "av")
    _vent_frig(anlegg, felt, 0)


def test_nektet_frigivning_tar_panelets_stiller_tilbake(anlegg, topo):
    """Nektes frigivningen (veksel i enden låst av togvei), skal panelets
    stiller fjære tilbake — og IKKE gi frigivning av seg selv når
    togveien senere løses ut."""
    tv = topo.innkjor()
    # En frigivning som nettopp er tatt tilbake står ved lag i 10 s
    # etterløp, og sperrer sikring av togveier i den enden så lenge
    _vent_frig(anlegg, "venstre", 0, timeout=15)
    _vent_frig(anlegg, "hoyre", 0, timeout=15)
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    t0 = anlegg.naa()
    for e in ("v", "h"):
        anlegg.pub(f"frigivning/{e}/set", "paa")
    anlegg.vent_ny("master/melding", "frigivning avvist", t0)
    time.sleep(1)
    nektet = [e for e in ("v", "h") if _frig(anlegg)[f"stiller_{e}"] == 0]
    assert nektet, "ingen ende ble nektet, men togveien låser en veksel"

    anlegg.pub(f"togvei/{tv['id']}/set", "stopp")
    time.sleep(0.5)
    anlegg.pub(f"togvei/{tv['id']}/set", "hjelpeutlos")
    anlegg.vent(f"togvei/{tv['id']}/state", "ledig", timeout=10)
    time.sleep(1.5)
    for e in nektet:
        assert _frig(anlegg)[f"stiller_{e}"] == 0, \
            f"ende {e}: frigivningen kom av seg selv etter utløsning"


def test_ugyldig_ende_ignoreres(anlegg, topo):
    for e in ("x", "vh", ""):
        anlegg.pub(f"frigivning/{e}/set", "paa")
    time.sleep(1)
    f = _frig(anlegg)
    assert f.get("stiller_v") == 0 and f.get("stiller_h") == 0


# ---------- jord ----------
# jord/set kaller samme jordKvitter() som jord/sim, og oppstartsperren
# den kvitterer står bare rett etter en omstart av masteren. rydd()
# kvitterer den før hver test, så en test her ville alltid blitt
# hoppet over. Prøves for hånd: start masteren på nytt, trykk Jord på
# panelet, se master/jord gå fra «sperret» til «ok».


# ---------- klokken ----------

def test_klokke_publiseres_retained(anlegg, topo):
    assert anlegg.tilstand.get("master/klokke/state") in \
        ("av", "stott", "ringer")


def test_klokke_stott_ved_avvisning(anlegg, topo):
    a, b = topo.fiendtlig_par()
    anlegg.pub(f"togvei/{a['id']}/set", "sikre")
    anlegg.vent(f"togvei/{a['id']}/state", "aktiv", timeout=20)
    anlegg.vent("master/klokke/state", "av", timeout=40)   # vekselklokken
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{b['id']}/set", "sikre")
    anlegg.vent_ny("master/klokke/state", "stott", t0)
    anlegg.vent("master/klokke/state", "av", timeout=3)


def test_klokke_ringer_under_signalstopp(anlegg, topo):
    anlegg.pub("signalstopp/set", "paa")
    anlegg.vent("master/klokke/state", "ringer")
    anlegg.pub("signalstopp/set", "av")
    anlegg.vent("master/klokke/state", "av")

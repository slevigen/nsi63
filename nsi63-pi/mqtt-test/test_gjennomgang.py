"""Gjennomgangsdrift mot ekte master.

Krever et anlegg med varselfelt (linjefelt-ref) og hovedtogspor i
togveitabellen — som Sokna. Panelets bryter (gjennomgang/set) brukes,
så det trengs ingen fysisk bryter i konfigen.
"""
import time

import pytest

KJOR = ("kjor", "kjor-redusert")


def _hovedspor(topo):
    """Innkjør- og utkjørtogvei over hovedsporet fra ett varselfelt."""
    for vf_id, vf in topo.felt.items():
        if vf.get("rolle") != "varselfelt" or not vf.get("linjefelt"):
            continue
        lf = vf["linjefelt"]
        inn = next((t for t in topo.togveier
                    if t["retning"] == "innkjor" and t["linjefelt"] == lf
                    and all(v["stilling"] == "normal"
                            for v in t["sporveksler"])), None)
        ut = next((t for t in topo.togveier
                   if t["retning"] == "utkjor" and t["linjefelt"]
                   and t["linjefelt"] != lf
                   and all(v["stilling"] == "normal"
                           for v in t["sporveksler"])), None)
        if inn and ut:
            return vf_id, inn, ut
    pytest.skip("fant ikke varselfelt med hovedspor-togveier i konfigen")


def _halser_normal(anlegg, topo):
    veksler = {v["sporveksel"] for t in topo.togveier
               for v in t["sporveksler"]}
    for v in veksler:
        anlegg.pub(f"sporveksel/{v}/set", "normal")
    for v in veksler:
        anlegg.vent(f"sporveksel/{v}/state", "normal", timeout=10)


def _paa(anlegg, topo):
    _halser_normal(anlegg, topo)
    anlegg.pub("gjennomgang/set", "paa")
    anlegg.vent("master/gjennomgang", "aktiv", timeout=10)


def test_av_venter_aktiv(anlegg, topo):
    anlegg.vent("master/gjennomgang", "av")
    _paa(anlegg, topo)
    anlegg.pub("gjennomgang/set", "av")
    anlegg.vent("master/gjennomgang", "av")


def test_aktiv_avviser_vekselomlegging(anlegg, topo):
    _paa(anlegg, topo)
    v = next(v["sporveksel"] for t in topo.togveier for v in t["sporveksler"])
    t0 = anlegg.naa()
    anlegg.pub(f"sporveksel/{v}/set", "avvik")
    anlegg.vent_ny(f"sporveksel/{v}/info", "gjennomgang", t0)
    time.sleep(2)
    assert anlegg.tilstand[f"sporveksel/{v}/state"] == "normal"


def test_tog_paa_varselfeltet_faar_signal_gjennom(anlegg, topo):
    vf, inn, ut = _hovedspor(topo)
    _paa(anlegg, topo)
    anlegg.pub(f"sporfelt/{vf}/sim", "belagt")
    anlegg.vent(f"togvei/{inn['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"togvei/{ut['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{inn['start']}/state", KJOR)
    anlegg.vent(f"hovedsignal/{ut['start']}/state", KJOR)
    # Ingen ringing: det er ingen txp å varsle
    assert anlegg.tilstand.get(f"varselfelt/{vf}/state") != "melding"

"""Kontraktstester for forriglingsmotoren — se conftest.py for bruk.

Hver test er skrevet mot MQTT-flatens KONTRAKT, ikke mot Sokna
spesielt: topologien (togveier, felt, veksler) leses fra anleggets
egne konfigfiler, så suiten følger med når anlegget endres — og kan
kjøres uendret mot et hvilket som helst NSI63-anlegg på benken.
"""
import time

import pytest

STOPP = ("stopp", "stopp-blink")
KJOR = ("kjor", "kjor-redusert")


def test_sikring_gir_kjorsignal(anlegg, topo):
    tv = topo.innkjor()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", KJOR)


def test_hjelpeutlosning_i_to_trinn(anlegg, topo):
    tv = topo.innkjor()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    # Utløs rett på aktiv togvei med kjørsignal skal AVVISES (trinn 1
    # mangler) — selve sikkerhetsregelen fra stillerapparatet
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "hjelpeutlos")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "aktiv"
    # Trinn 1: signal i stopp, fortsatt forriglet
    t1 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "stopp")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "trinn 1", t1)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", STOPP)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "aktiv"
    # Trinn 2: utløsning
    anlegg.pub(f"togvei/{tv['id']}/set", "hjelpeutlos")
    anlegg.vent(f"togvei/{tv['id']}/state", "ledig")


def test_belagt_felt_avviser_sikring(anlegg, topo):
    tv = topo.innkjor()
    felt = tv["spor"] or tv["frie"][0]
    anlegg.pub(f"sporfelt/{felt}/sim", "belagt")
    anlegg.vent(f"sporfelt/{felt}/state", "belagt")
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "ledig"


def test_fiendtlig_togvei_avvises(anlegg, topo):
    a, b = topo.fiendtlig_par()
    anlegg.pub(f"togvei/{a['id']}/set", "sikre")
    anlegg.vent(f"togvei/{a['id']}/state", ("aktiv", "sikring"), timeout=20)
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{b['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{b['id']}/info", "avvist", t0)
    assert anlegg.tilstand.get(f"togvei/{b['id']}/state") in ("ledig", None)


def test_signalfall_ved_belegg(anlegg, topo):
    tv = topo.innkjor()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", KJOR)
    # Tog inn i togveien: første frie felt belegges -> signalet FELLES,
    # men togveien er fortsatt forriglet
    anlegg.pub(f"sporfelt/{tv['frie'][0]}/sim", "belagt")
    anlegg.vent(f"hovedsignal/{tv['start']}/state", STOPP)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "aktiv"


def test_sistevognskontroll(anlegg, topo):
    tv = topo.sistevogn_tv()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    # Toget kjører inn: utløsningsfeltet belagt, så fritt igjen —
    # uten linjeblokk skal togveien VENTE på kvittering, ikke rives
    anlegg.pub(f"sporfelt/{tv['utlos']}/sim", "belagt")
    anlegg.vent(f"sporfelt/{tv['utlos']}/state", "belagt")
    anlegg.pub(f"sporfelt/{tv['utlos']}/sim", "fri")
    anlegg.vent(f"togvei/{tv['id']}/state", "klar-utlos")
    # Txp ser sluttsignalet og kvitterer
    anlegg.pub(f"togvei/{tv['id']}/set", "kvitter")
    anlegg.vent(f"togvei/{tv['id']}/state", "ledig")


def test_veksel_laast_av_togvei(anlegg, topo):
    tv = topo.innkjor()
    vk = tv["sporveksler"][0]
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    motsatt = "avvik" if vk["stilling"] == "normal" else "normal"
    t0 = anlegg.naa()
    anlegg.pub(f"sporveksel/{vk['sporveksel']}/set", motsatt)
    anlegg.vent_ny(f"sporveksel/{vk['sporveksel']}/info", "avvist", t0)


def test_signalstopp_sperrer_sikring(anlegg, topo):
    tv = topo.innkjor()
    anlegg.pub("signalstopp/sim", "paa")
    anlegg.vent("master/signalstopp", "paa")
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    anlegg.pub("signalstopp/sim", "auto")
    anlegg.vent("master/signalstopp", "av")


# ---------- samlelås (SLAAS-RIGEL.md §2.1) — hoppes over uten låser ----------
# Nøkkelkontakten simuleres til «inne» først, så testene er
# deterministiske også på en benk med (eller uten) fysisk kontakt.

def test_samlelaas_frigi_og_sperr(anlegg, topo):
    l = topo.samlelaas()
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")
    anlegg.pub(f"samlelaas/{l['id']}/set", "frigi")
    anlegg.vent(f"samlelaas/{l['id']}/state", "frigitt")
    anlegg.pub(f"samlelaas/{l['id']}/set", "sperr")
    anlegg.vent(f"samlelaas/{l['id']}/state", "sperret")
    anlegg.pub(f"samlelaas/{l['id']}/sim", "auto")


def test_samlelaas_frigitt_sperrer_sikring(anlegg, topo):
    l, tv = topo.samlelaas_togvei()
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")
    anlegg.pub(f"samlelaas/{l['id']}/set", "frigi")
    anlegg.vent(f"samlelaas/{l['id']}/state", "frigitt")
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    assert anlegg.tilstand.get(f"togvei/{tv['id']}/state") in ("ledig", None)


def test_samlelaas_frigivning_avvist_av_togvei(anlegg, topo):
    l, tv = topo.samlelaas_togvei()
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", ("aktiv", "sikring"), timeout=20)
    t0 = anlegg.naa()
    anlegg.pub(f"samlelaas/{l['id']}/set", "frigi")
    anlegg.vent_ny(f"samlelaas/{l['id']}/info", "frigivning avvist", t0)
    assert anlegg.tilstand[f"samlelaas/{l['id']}/state"] == "sperret"


def test_samlelaas_avviser_omlegging(anlegg, topo):
    l = topo.samlelaas()
    vk = (l.get("omfatter") or [None])[0]
    if not vk:
        pytest.skip("samlelåsen omfatter ingen veksler")
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")
    anlegg.vent(f"samlelaas/{l['id']}/state", "sperret")
    t0 = anlegg.naa()
    anlegg.pub(f"sporveksel/{vk}/set", "avvik")
    anlegg.vent_ny(f"sporveksel/{vk}/info", "laast av samlelaas", t0)


def test_samlelaas_nodutlosning(anlegg, topo):
    """Nøkkelen tas ut UTEN frigivning mens en togvei over
    virkeområdet er aktiv: kjørsignalet skal felles STRAKS."""
    l, tv = topo.samlelaas_togvei()
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", KJOR)
    t0 = anlegg.naa()
    anlegg.pub(f"samlelaas/{l['id']}/sim", "ute")
    anlegg.vent_ny("master/melding", "NOEDUTLOSNING", t0)
    anlegg.vent(f"samlelaas/{l['id']}/state", "noekkel-ute")
    anlegg.vent(f"hovedsignal/{tv['start']}/state", STOPP)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "aktiv"
    anlegg.pub(f"samlelaas/{l['id']}/sim", "inne")   # rydd tar resten
    anlegg.vent(f"samlelaas/{l['id']}/state", "sperret")


# ---------- rigel (SLAAS-RIGEL.md §2.2) — hoppes over uten rigler ----------

def _obj_kommando(topo, litra, normal):
    """(tema, payload) som legger objektet i normal-/avvikstilling."""
    if topo.er_sporsperre(litra):
        return (f"sporsperre/{litra}/set", "paalagt" if normal else "avlagt")
    return (f"sporveksel/{litra}/set", "normal" if normal else "avvik")


def _obj_state(topo, litra, normal):
    if topo.er_sporsperre(litra):
        return (f"sporsperre/{litra}/state", "paalagt" if normal else "avlagt")
    return (f"sporveksel/{litra}/state", "normal" if normal else "avvik")


def test_rigel_sperret_avviser_omlegging(anlegg, topo):
    l = topo.rigel()
    obj = (l.get("omfatter") or [None])[0]
    if not obj:
        pytest.skip("rigelen omfatter ingen objekter")
    anlegg.vent(f"rigel/{l['id']}/state", "sperret", timeout=15)
    t0 = anlegg.naa()
    tema, pl = _obj_kommando(topo, obj, normal=False)
    anlegg.pub(tema, pl)
    anlegg.vent_ny(tema.replace("/set", "/info"), "laast av rigel", t0)


def test_rigel_frigi_omlegging_og_sperr(anlegg, topo):
    """Full sekvens: frigi -> objektet kan legges om -> tilbake i
    normal -> sperr gir 10 s etterloep -> sperret."""
    l = topo.rigel()
    obj = (l.get("omfatter") or [None])[0]
    if not obj:
        pytest.skip("rigelen omfatter ingen objekter")
    anlegg.pub(f"rigel/{l['id']}/set", "frigi")
    anlegg.vent(f"rigel/{l['id']}/state", "frigitt")
    tema, pl = _obj_kommando(topo, obj, normal=False)
    anlegg.pub(tema, pl)
    anlegg.vent(*_obj_state(topo, obj, normal=False), timeout=10)
    tema, pl = _obj_kommando(topo, obj, normal=True)
    anlegg.pub(tema, pl)
    anlegg.vent(*_obj_state(topo, obj, normal=True), timeout=10)
    anlegg.pub(f"rigel/{l['id']}/set", "sperr")
    anlegg.vent(f"rigel/{l['id']}/state", "etterlop")
    anlegg.vent(f"rigel/{l['id']}/state", "sperret", timeout=15)


def test_rigel_frigitt_sperrer_sikring(anlegg, topo):
    l, tv = topo.rigel_togvei()
    anlegg.pub(f"rigel/{l['id']}/set", "frigi")
    anlegg.vent(f"rigel/{l['id']}/state", "frigitt")
    t0 = anlegg.naa()
    anlegg.pub(f"togvei/{tv['id']}/set", "sikre")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "avvist", t0)
    assert anlegg.tilstand.get(f"togvei/{tv['id']}/state") in ("ledig", None)


# ---------- stillerdytt-paring (STILLERAPPARAT.md milepæl 5) ----------
# Panelet lener seg på nøyaktig denne mekanikken: to dytt (linjefelt
# + togspor) innen 2 sekunder er én betjening, og retningene er
# geometriske — «venstre ende + dytt mot høyre = inn i stasjonen».

def _dytt_inn(side):
    """Dyttretningen som betyr INN mot stasjonen for gitt ende."""
    return "h" if side == "v" else "v"


def test_stillerdytt_sikrer_togvei(anlegg, topo):
    tv = topo.stiller_tv()
    side = topo.felt[tv["linjefelt"]]["side"]
    r = _dytt_inn(side)
    anlegg.pub(f"stiller/{tv['linjefelt']}/lagt", r)
    anlegg.pub(f"stiller/{tv['spor']}/lagt", r)
    anlegg.vent(f"togvei/{tv['id']}/state", ("sikring", "aktiv"),
                timeout=10)
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", KJOR)


def test_stillerdytt_vindu_paa_to_sekunder(anlegg, topo):
    """To dytt MER enn 2 s fra hverandre er to enslige dytt — ingen
    betjening. (Nr. 2 blir liggende som nytt førstedytt; la også det
    løpe ut så det ikke parer seg med neste test.)"""
    tv = topo.stiller_tv()
    r = _dytt_inn(topo.felt[tv["linjefelt"]]["side"])
    anlegg.pub(f"stiller/{tv['linjefelt']}/lagt", r)
    time.sleep(2.5)
    anlegg.pub(f"stiller/{tv['spor']}/lagt", r)
    time.sleep(2.5)
    assert anlegg.tilstand.get(f"togvei/{tv['id']}/state") in ("ledig",
                                                               None)


def test_stillerdytt_hjelpeutlosning(anlegg, topo):
    """Instruksens VIII fra stillerne: MOT hverandre = trinn 1
    (signal i stopp, fortsatt forriglet); FRA hverandre = trinn 2
    (tidsreléet startes — 90 s på Sokna; utløpet ventes ikke ut)."""
    tv = topo.stiller_tv()
    side = topo.felt[tv["linjefelt"]]["side"]
    r = _dytt_inn(side)
    anlegg.pub(f"stiller/{tv['linjefelt']}/lagt", r)
    anlegg.pub(f"stiller/{tv['spor']}/lagt", r)
    anlegg.vent(f"togvei/{tv['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{tv['start']}/state", KJOR)
    # MOT hverandre: L-stilleren inn, sporstilleren ut
    mot = {"h": ("v", "h"), "v": ("h", "v")}[side]
    t0 = anlegg.naa()
    anlegg.pub(f"stiller/{tv['linjefelt']}/lagt", mot[0])
    anlegg.pub(f"stiller/{tv['spor']}/lagt", mot[1])
    anlegg.vent(f"hovedsignal/{tv['start']}/state", STOPP)
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "trinn 1", t0)
    assert anlegg.tilstand[f"togvei/{tv['id']}/state"] == "aktiv"
    # FRA hverandre: tidsreléet kobles inn, togveilampen blinker
    t1 = anlegg.naa()
    anlegg.pub(f"stiller/{tv['linjefelt']}/lagt", mot[1])
    anlegg.pub(f"stiller/{tv['spor']}/lagt", mot[0])
    anlegg.vent(f"togvei/{tv['id']}/state", "hjelpeutlosning")
    anlegg.vent_ny(f"togvei/{tv['id']}/info", "trinn 2", t1)


def test_forsignal_sporgating_ved_felles_utkjor(anlegg, topo):
    """Med FELLES utkjørsignal bærer bildet sporinformasjon (kjør =
    hovedtogsporet, kjør-redusert = avvikssporet). Forsignalet på
    innkjørmasten skal vise forvent-stopp for tog med togvei inn i et
    spor UTEN aktiv utkjøring — selv om utkjørsignalet viser kjør for
    nabosporet."""
    fs, tv_i, ut_annen, _ = topo.forsignal_gating()
    # nabosporets utkjøring først: det felles utkjørsignalet får kjør
    anlegg.pub(f"togvei/{ut_annen['id']}/set", "sikre")
    anlegg.vent(f"togvei/{ut_annen['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"hovedsignal/{ut_annen['start']}/state", KJOR)
    # innkjør til spor uten utkjøring: forsignalet skal IKKE speile
    # utkjørsignalets kjørbilde
    anlegg.pub(f"togvei/{tv_i['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv_i['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"forsignal/{fs['id']}/state", "forvent-stopp")


def test_forsignal_folger_utkjor_for_eget_spor(anlegg, topo):
    """Motstykket: har togets EGET spor aktiv utkjøring fra det felles
    utkjørsignalet, følger forsignalet utkjørsignalets bilde."""
    fs, tv_i, _, ut_samme = topo.forsignal_gating()
    anlegg.pub(f"togvei/{tv_i['id']}/set", "sikre")
    anlegg.vent(f"togvei/{tv_i['id']}/state", "aktiv", timeout=20)
    # innkjør alene: ingen utkjøring for sporet -> forvent-stopp
    anlegg.vent(f"forsignal/{fs['id']}/state", "forvent-stopp")
    anlegg.pub(f"togvei/{ut_samme['id']}/set", "sikre")
    anlegg.vent(f"togvei/{ut_samme['id']}/state", "aktiv", timeout=20)
    anlegg.vent(f"forsignal/{fs['id']}/state",
                ("forvent-kjor", "forvent-kjor-redusert"))


def test_skiftesignal_automatisk_forbudt_under_omlegging(anlegg, topo):
    """Høyt skiftesignal (forbildet): normalstillingen er SLUKKET.
    Slås det på vises skifting-tillatt (42). Legges en veksel i
    området om, viser signalet automatisk skifting-forbudt (41) så
    lenge vekselen er i bevegelse — og tillatt igjen når stillingen
    er bekreftet."""
    sk, veksel = topo.skift_med_veksel()
    anlegg.pub(f"skiftesignal/{sk}/set", "slukket")
    anlegg.vent(f"skiftesignal/{sk}/state", "slukket")
    anlegg.pub(f"skiftesignal/{sk}/set", "skifting-tillatt")
    anlegg.vent(f"skiftesignal/{sk}/state", "skifting-tillatt")
    naa = anlegg.tilstand.get(f"sporveksel/{veksel}/state") or "normal"
    maal = "avvik" if naa == "normal" else "normal"
    anlegg.pub(f"sporveksel/{veksel}/set", maal)
    anlegg.vent(f"skiftesignal/{sk}/state", "skifting-forbudt",
                timeout=10)
    anlegg.vent(f"sporveksel/{veksel}/state", maal, timeout=20)
    anlegg.vent(f"skiftesignal/{sk}/state", "skifting-tillatt",
                timeout=10)
    # rydd: vekselen tilbake og signalet slukket (normalstilling)
    anlegg.pub(f"sporveksel/{veksel}/set", naa)
    anlegg.vent(f"sporveksel/{veksel}/state", naa, timeout=20)
    anlegg.pub(f"skiftesignal/{sk}/set", "slukket")
    anlegg.vent(f"skiftesignal/{sk}/state", "slukket")

"""Oppstart, sider og det app-en hevder retained mot brokeren."""

import json


def test_sidene_svarer_med_alle_filer(anlegg):
    """Adminflaten, panelet og panelets MQTT-klient serveres.

    En fersk Pi svarte 404 på /panel fordi install.sh ikke kopierte
    panelfilene. Her sjekkes app-siden: finnes filene, serveres de.
    """
    k = anlegg.klient
    for sti in ("/", "/ui/app.js", "/panel", "/panel/mqtt.js"):
        r = k.get(sti)
        assert r.status_code == 200, f"{sti}: {r.status_code}"


def test_panel_uten_fil_sier_ifra(fersk):
    (fersk.mappe / "panel.html").unlink()
    r = fersk.klient.get("/panel")
    assert r.status_code == 404
    assert "panel.html" in r.get_json()["error"]


def test_fersk_pi_har_tom_konfig(fersk):
    hal = fersk.klient.get("/api/hal").get_json()
    assert hal["functions"] == []
    assert fersk.klient.get("/api/forrigling").get_json()["togveier"] == []
    assert fersk.klient.get("/api/anlegg").get_json()["id"] == ""


def test_hevd_konfig_publiserer_alle_tre_retained(anlegg):
    """Panelet tegner ingenting før config/hal OG config/forrigling er
    retained. Med konfigfilene på plass skal oppstarten hevde alle tre."""
    anlegg.app.hevd_konfig()
    r = anlegg.mq.retained
    for tema in ("config/hal", "config/forrigling", "config/anlegg"):
        assert "nsi63/" + tema in r, f"{tema} ble ikke publisert retained"
    assert anlegg.mq.retained_json("nsi63/config/hal")["functions"]
    assert anlegg.mq.retained_json("nsi63/config/forrigling")["togveier"]


def test_hevd_konfig_fersk_publiserer_ikke_tom_hal(fersk):
    """En tom HAL skal ikke overskrive en master som har konfig i eget
    flash. Bare anlegget (tom ID) hevdes."""
    fersk.app.hevd_konfig()
    assert "nsi63/config/hal" not in fersk.mq.retained
    assert "nsi63/config/forrigling" not in fersk.mq.retained
    assert json.loads(fersk.mq.retained["nsi63/config/anlegg"])["id"] == ""


def test_konfigfilene_er_i_nyeste_skjema(anlegg):
    """migrate() skal ikke ha noe å gjøre på konfigen som ligger i treet.
    Gjør den det, er filene i repoet utdatert i forhold til koden.
    (Notatfeltene i eksempelet er bevisst — se uten_notes.)"""
    a = anlegg.app
    hal = anlegg.fil("hal.json", uten_notater=True)
    assert a.migrate(json.loads(json.dumps(hal)))["functions"] == \
        hal["functions"]
    fr = anlegg.fil("forrigling.json")
    assert a.migrate_forrigling(json.loads(json.dumps(fr)),
                                hal["functions"])["togveier"] == \
        fr["togveier"]


def test_versjon_vises_bare_med_stempel(fersk):
    """deploy-pi.sh legger igjen versjon.json; uten den er versjonen
    ukjent, aldri gjettet."""
    assert fersk.klient.get("/api/pi").get_json()["hal_ui"] is None
    (fersk.mappe / "versjon.json").write_text(json.dumps(
        {"commit": "a" * 40, "kort": "aaaaaaa", "gren": "main",
         "ukommittert": False, "tid": "2026-11-27T10:00:00+00:00",
         "annet": "tas ikke med"}))
    fersk.app._pi_cache["data"] = None
    v = fersk.klient.get("/api/pi").get_json()["hal_ui"]
    assert v["kort"] == "aaaaaaa" and v["ukommittert"] is False
    assert "annet" not in v


def test_gjennomgangsdrift_fra_master_vises_i_api(fersk):
    class Msg:
        topic = "nsi63/master/gjennomgang"
        payload = b"venter"
        retain = True
    fersk.app.on_message(None, None, Msg())
    assert fersk.klient.get("/api/master").get_json()["gjennomgang"] == "venter"

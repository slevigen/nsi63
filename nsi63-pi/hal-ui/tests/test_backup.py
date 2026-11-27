"""Backup-påminnelsen og de automatiske kopiene."""

import copy
import io
import json
from datetime import timedelta


def _status(h):
    return h.klient.get("/api/backup-status").get_json()


def _lagre_uendret(h):
    fns = copy.deepcopy(h.klient.get("/api/hal").get_json()["functions"])
    r = h.klient.post("/api/hal", json={"functions": fns})
    assert r.status_code == 200, r.get_json()


# ---------- påminnelsen ----------

def test_fersk_pi_paaminner_ikke(fersk):
    """Ingenting å miste: ingen påminnelse."""
    st = _status(fersk)
    assert st["endret"] is False and st["sist"] is None


def test_aldri_lastet_ned_paaminner(anlegg):
    st = _status(anlegg)
    assert st["endret"] is True and st["sist"] is None


def test_nedlasting_nullstiller_og_lagring_vekker(anlegg):
    anlegg.klient.get("/api/backup")
    st = _status(anlegg)
    assert st["endret"] is False and st["sist"]

    _lagre_uendret(anlegg)            # ny versjon, selv uten endring
    st = _status(anlegg)
    assert st["endret"] is True and st["hva"] == ["hal"]


def test_anlegget_teller_med(sokna):
    """Anlegget har ikke versjonsstempel — det sammenliknes på innhold."""
    sokna.klient.get("/api/backup")
    an = sokna.klient.get("/api/anlegg").get_json()
    r = sokna.klient.post("/api/anlegg", json={
        "id": an["id"], "navn": "ANNET NAVN", "tider": an["tider"]})
    assert r.status_code == 200, r.get_json()
    assert _status(sokna)["hva"] == ["anlegg"]


def test_gjenoppretting_regnes_som_backup(fersk, sokna):
    """Den som gjenoppretter, har nettopp hatt konfigen som fil."""
    backup = sokna.klient.get("/api/backup").data
    r = fersk.klient.post(
        "/api/restore", data={"file": (io.BytesIO(backup), "b.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert _status(fersk)["endret"] is False


def test_gammel_kopi_nullstiller_ikke(anlegg):
    _lagre_uendret(anlegg)
    navn = _status(anlegg)["auto"][0]
    assert anlegg.klient.get(f"/api/backup-auto/{navn}").status_code == 200
    assert _status(anlegg)["endret"] is True


# ---------- de automatiske kopiene ----------

def test_forste_lagring_tar_vare_paa_utgangspunktet(anlegg):
    """Tilstanden FØR den aller første lagringen skal kunne hentes."""
    for_lagring = anlegg.fil("hal.json")["version"]
    _lagre_uendret(anlegg)
    auto = _status(anlegg)["auto"]
    assert len(auto) == 2
    utg = [n for n in auto if n.endswith("-utgangspunkt.json")]
    assert len(utg) == 1
    kopi = json.loads((anlegg.mappe / "backup-auto" / utg[0]).read_text())
    assert kopi["hal"]["version"] == for_lagring


def test_kopien_er_en_gyldig_backup(fersk, sokna):
    _lagre_uendret(sokna)
    nyeste = _status(sokna)["auto"][0]
    data = sokna.klient.get(f"/api/backup-auto/{nyeste}").data
    r = fersk.klient.post(
        "/api/restore", data={"file": (io.BytesIO(data), "b.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()


def test_bare_de_siste_beholdes(anlegg, monkeypatch):
    a = anlegg.app
    ekte = a.datetime
    start = ekte(2026, 1, 1, 12, 0, 0)
    teller = iter(range(1000))

    class Klokke(ekte):
        """Ett nytt sekund per kall: i samme sekund overskriver kopiene
        hverandre (med vilje), og da ville taket aldri blitt nådd."""
        @classmethod
        def now(cls, tz=None):
            return (start + timedelta(seconds=next(teller))).replace(
                tzinfo=tz)

    monkeypatch.setattr(a, "datetime", Klokke)
    for _ in range(a.BACKUP_AUTO_ANTALL + 5):
        _lagre_uendret(anlegg)
    auto = _status(anlegg)["auto"]
    assert len(auto) == a.BACKUP_AUTO_ANTALL
    assert auto == sorted(auto, reverse=True)       # nyeste først


def test_gjenoppretting_gir_en_hel_kopi(fersk, sokna):
    """hal og forrigling skrives hver for seg; kopien i samme sekund
    skal ende som HELE den gjenopprettede konfigen, ikke en blanding."""
    backup = json.loads(sokna.klient.get("/api/backup").data)
    r = fersk.klient.post(
        "/api/restore",
        data={"file": (io.BytesIO(json.dumps(backup).encode()), "b.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    nyeste = _status(fersk)["auto"][0]
    kopi = json.loads((fersk.mappe / "backup-auto" / nyeste).read_text())
    assert kopi["forrigling"]["togveier"] == fersk.fil(
        "forrigling.json")["togveier"]
    assert kopi["hal"]["functions"] == fersk.fil("hal.json")["functions"]


def test_kopi_med_ukjent_navn_avvises(anlegg):
    for navn in ("../hal.json", "hal.json", "nsi63-auto-x.json"):
        assert anlegg.klient.get(
            f"/api/backup-auto/{navn}").status_code == 404

"""OTA-køen: alle utdaterte noder, én om gangen."""

import io
import time

import pytest

NY = "202611271130"
GML = "202608261126"


class Synkron:
    """threading.Thread som kjører målet med en gang i start()."""
    def __init__(self, target=None, daemon=None, **kw):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def ota(fersk, monkeypatch):
    """Pi med opplastet firmware, levende master og tre utdaterte noder.

    sov(s) er køens klokke. Den spiller nodene: en node som har fått
    «ota» melder seg tilbake med nytt stempel etter `bruker[mac]`
    søvnsekunder — eller aldri, hvis verdien er None."""
    a = fersk.app
    a.OTA_DIR.mkdir()
    (a.OTA_DIR / "nsi63-atoms3.bin").write_bytes(b"\xe9" + bytes(300_000))
    (a.OTA_DIR / "nsi63-atoms3.bin.stempel").write_text(NY)
    a.cache["master_hort_ts"] = time.monotonic()
    a.cache["nodes"] = {"nodes": [
        {"mac": "cc0000000003", "online": 1, "bygget": GML},
        {"mac": "aa0000000001", "online": 1, "bygget": GML},
        {"mac": "bb0000000002", "online": 1, "bygget": GML},
    ]}
    monkeypatch.setattr(a.threading, "Thread", Synkron)
    fersk.bruker = {}                      # mac -> sekunder til ferdig
    fersk.sovn = []

    def sov(sek):
        fersk.sovn.append(sek)
        cmd = [t.split("/")[2] for t, pl, _ in fersk.mq.publisert
               if t.endswith("/cmd") and pl == "ota"]
        if not cmd:
            return
        mac = cmd[-1]
        n = a._node(mac)
        trenger = fersk.bruker.get(mac, 5)
        n.setdefault("_igjen", trenger)
        if n["_igjen"] is None:
            n["online"] = 0                # kom aldri tilbake
            return
        n["_igjen"] -= 1
        n["online"] = 0 if n["_igjen"] > 0 else 1
        if n["_igjen"] <= 0:
            n["bygget"] = NY

    monkeypatch.setattr(a, "_ota_ko_sov", sov)
    # Køtilstanden er modulglobal; hver test starter blankt
    a.ota_ko.update(kjorer=False, stopp=False, venter=[], ferdig=[],
                    feilet=[], avbrutt=[], aktiv=None)
    return fersk


def _start(h):
    return h.klient.post("/api/ota/ko")


def _status(h):
    return h.klient.get("/api/ota/ko").get_json()


def _ota_cmd(h):
    return [t.split("/")[2] for t, pl, _ in h.mq.publisert
            if t.endswith("/cmd") and pl == "ota"]


# ---------- utvalget ----------

def test_utvalg_er_utdaterte_online_noder_sortert(ota):
    ota.app.cache["nodes"]["nodes"] += [
        {"mac": "dd0000000004", "online": 0, "bygget": GML},   # offline
        {"mac": "ee0000000005", "online": 1, "bygget": NY},    # oppdatert
        {"mac": "ff0000000006", "online": 1},                  # uten stempel
    ]
    macs = [k["mac"] for k in _status(ota)["kandidater"]]
    assert macs == ["aa0000000001", "bb0000000002", "cc0000000003"]


def test_utvalg_sorteres_paa_kallenavn(ota):
    hal = ota.app.load_hal()
    hal["noder"] = {"AAA": {"mac": "cc0000000003"}}
    ota.app.save_hal(noder=hal["noder"])
    k = _status(ota)["kandidater"]
    assert [x["mac"] for x in k][0] == "aa0000000001"   # «aa0…» < «aaa»
    assert {x["mac"]: x["alias"] for x in k}["cc0000000003"] == "AAA"


def test_utvalg_ignorerer_navnlos_driver_node_som_alias(ota):
    """Når et kallenavn fjernes blir driver-lista liggende under MAC-en selv
    (hal['noder'][mac] = {'mac': mac, 'driver': [...]}). Det skal ikke vises
    som et kallenavn i OTA-køen."""
    mac = "aa0000000001"
    ota.app.save_hal(noder={mac: {"mac": mac, "driver": ["0x40"]}})
    k = {x["mac"]: x["alias"] for x in _status(ota)["kandidater"]}
    assert k[mac] == ""


# ---------- kjøringen ----------

def test_en_om_gangen_til_alle_er_oppdatert(ota):
    r = _start(ota)
    assert r.status_code == 200 and r.get_json()["antall"] == 3
    st = _status(ota)
    assert not st["kjorer"] and not st["venter"] and not st["feilet"]
    assert [n["mac"] for n in st["ferdig"]] == \
        ["aa0000000001", "bb0000000002", "cc0000000003"]
    assert _ota_cmd(ota) == ["aa0000000001", "bb0000000002",
                             "cc0000000003"]
    # Pause mellom nodene, ikke etter den siste
    assert ota.sovn.count(ota.app.OTA_KO_PAUSE_S) == 2


def test_neste_venter_til_forrige_melder_nytt_stempel(ota):
    """Kommandoen til neste node sendes først når forrige er tilbake."""
    ota.bruker["aa0000000001"] = 20
    sendt_ved = {}
    ekte = ota.app._ota_ko_sov

    def sov(sek):
        ekte(sek)
        for mac in _ota_cmd(ota):
            sendt_ved.setdefault(mac, len(ota.sovn))
    ota.app._ota_ko_sov = sov
    _start(ota)
    assert sendt_ved["bb0000000002"] > 20
    assert [n["sekunder"] for n in _status(ota)["ferdig"]][0] == 20


def test_timeout_logges_og_koen_gaar_videre(ota):
    ota.bruker["bb0000000002"] = None      # kommer aldri tilbake
    _start(ota)
    st = _status(ota)
    assert [n["mac"] for n in st["ferdig"]] == ["aa0000000001",
                                                "cc0000000003"]
    assert len(st["feilet"]) == 1
    f = st["feilet"][0]
    assert f["mac"] == "bb0000000002"
    assert f["sekunder"] == ota.app.OTA_KO_FRIST_S
    assert "offline" in f["grunn"]


def test_gammel_firmware_etter_ota_er_feil(ota):
    """MD5-feil o.l.: noden kommer tilbake, men med gammelt stempel."""
    ekte = ota.app._ota_ko_sov

    def sov(sek):
        ekte(sek)
        n = ota.app._node("aa0000000001")
        if n["bygget"] == NY:
            n["bygget"] = GML
    ota.app._ota_ko_sov = sov
    _start(ota)
    f = _status(ota)["feilet"]
    assert f and f[0]["mac"] == "aa0000000001"
    assert GML in f[0]["grunn"]


def test_stopp_lar_paagaende_fullfore(ota):
    ekte = ota.app._ota_ko_sov

    def sov(sek):
        ekte(sek)
        if len(ota.sovn) == 2:             # midt i den første noden
            assert ota.klient.post("/api/ota/ko/stopp").status_code == 200
    ota.app._ota_ko_sov = sov
    _start(ota)
    st = _status(ota)
    assert [n["mac"] for n in st["ferdig"]] == ["aa0000000001"]
    assert [n["mac"] for n in st["avbrutt"]] == ["bb0000000002",
                                                 "cc0000000003"]
    assert _ota_cmd(ota) == ["aa0000000001"]
    assert not st["kjorer"]


def test_stopp_uten_ko(ota):
    assert ota.klient.post("/api/ota/ko/stopp").status_code == 400


# ---------- startvernene ----------

def test_stille_master_avvises(ota):
    ota.app.cache["master_hort_ts"] = time.monotonic() - 40
    r = _start(ota)
    assert r.status_code == 400 and "master" in r.get_json()["error"]
    assert not _ota_cmd(ota)


def test_uten_firmware_avvises(ota):
    (ota.app.OTA_DIR / "nsi63-atoms3.bin").unlink()
    r = _start(ota)
    assert r.status_code == 400 and "firmware" in r.get_json()["error"]


def test_ustemplet_firmware_avvises(ota):
    (ota.app.OTA_DIR / "nsi63-atoms3.bin.stempel").unlink()
    r = _start(ota)
    assert r.status_code == 400 and "stempel" in r.get_json()["error"]


def test_ingen_utdaterte_noder(ota):
    for n in ota.app.cache["nodes"]["nodes"]:
        n["bygget"] = NY
    st = _status(ota)
    assert st["kandidater"] == []
    assert st["fw_finnes"] and st["fw_stempel"] == NY   # UI-et forklarer
    r = _start(ota)
    assert r.status_code == 400 and "ingen" in r.get_json()["error"]


def test_lampeprove_hindrer_koen(ota):
    ota.app.lamptest["running"] = True
    try:
        r = _start(ota)
        assert r.status_code == 400
        assert "lampeprøve" in r.get_json()["error"]
    finally:
        ota.app.lamptest["running"] = False


def test_koen_hindrer_lampeprove_og_enkelt_ota(ota):
    ota.app.ota_ko["kjorer"] = True
    try:
        r = ota.klient.post("/api/lamptest", json={"action": "start"})
        assert r.status_code == 400 and "OTA" in r.get_json()["error"]
        r = ota.klient.post("/api/ota/start", json={"maal": "aa0000000001"})
        assert r.status_code == 400 and "OTA" in r.get_json()["error"]
        assert _start(ota).status_code == 400          # ikke to køer
        r = ota.klient.post(
            "/api/ota/firmware",
            data={"file": (io.BytesIO(b"\xe9" + bytes(300_000)),
                           "nsi63-atoms3-202612010000.bin")},
            content_type="multipart/form-data")
        assert r.status_code == 400 and "OTA" in r.get_json()["error"]
        assert (ota.app.OTA_DIR / "nsi63-atoms3.bin.stempel").read_text() == NY
    finally:
        ota.app.ota_ko["kjorer"] = False

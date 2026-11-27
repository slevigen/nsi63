"""Lagring, validering og gjenoppretting gjennom API-et."""

import copy
import io
import json

import pytest

SPORFELT_REFS_TOGVEI = ("spor", "fra", "til", "utlosningsfelt")
SPORFELT_REFS_HAL = ("pluss_til", "minus_til", "spiss_til", "ligger_i",
                     "linjefelt")


def _lagre_hal(h, functions):
    return h.klient.post("/api/hal", json={"functions": functions})


def _feil(r):
    return (r.get_json() or {}).get("error", "")


# ---------- uendret lagring ----------

def test_hal_rundtur_er_uendret(anlegg):
    """Det UI-et henter, skal kunne lagres tilbake uten endring."""
    hal = anlegg.klient.get("/api/hal").get_json()
    r = _lagre_hal(anlegg, copy.deepcopy(hal["functions"]))
    assert r.status_code == 200, _feil(r)
    assert anlegg.fil("hal.json")["functions"] == hal["functions"]
    pub = anlegg.mq.retained_json("nsi63/config/hal")
    assert pub["functions"] == hal["functions"]
    assert pub["version"] == anlegg.fil("hal.json")["version"]


def test_forrigling_rundtur_er_uendret(anlegg):
    fr = anlegg.klient.get("/api/forrigling").get_json()
    r = anlegg.klient.post("/api/forrigling",
                           json={"togveier": copy.deepcopy(fr["togveier"])})
    assert r.status_code == 200, _feil(r)
    assert anlegg.fil("forrigling.json")["togveier"] == fr["togveier"]
    assert anlegg.mq.retained_json(
        "nsi63/config/forrigling")["togveier"] == fr["togveier"]


# ---------- avvisning ----------

def _forste(h, typ=None):
    fns = copy.deepcopy(h.klient.get("/api/hal").get_json()["functions"])
    if typ:
        return fns, next(f for f in fns if f.get("type") == typ)
    return fns, fns[0]


@pytest.mark.parametrize("litra, hint", [
    ("A/B", "ulovlig"),           # bryter MQTT-temaet
    ("A+", "ulovlig"),
    ("X" * 24, "avkorter"),       # masterens char[24]
    ("", "litra"),
])
def test_ugyldig_litra_avvises(anlegg, litra, hint):
    fns, f = _forste(anlegg)
    f["id"] = litra
    r = _lagre_hal(anlegg, fns)
    assert r.status_code == 400
    assert hint in _feil(r)
    assert not anlegg.mq.publisert, "avvist lagring ble publisert"


def test_duplikat_litra_avvises(anlegg):
    fns, f = _forste(anlegg)
    fns.append(copy.deepcopy(f))
    r = _lagre_hal(anlegg, fns)
    assert r.status_code == 400
    assert "Duplikat" in _feil(r)


def test_for_mange_funksjoner_avvises(anlegg):
    a = anlegg.app
    fns, _ = _forste(anlegg)
    while len(fns) <= a.MAX_FUNKSJONER:
        fns.append({"id": f"Q{len(fns)}", "type": "sporfelt",
                    "bindinger": []})
    r = _lagre_hal(anlegg, fns)
    assert r.status_code == 400
    assert "Kapasitet" in _feil(r)


def test_ukjent_node_avvises(anlegg):
    fns, f = _forste(anlegg)
    f["bindinger"] = [{"sted": "anlegg", "node": "finnes-ikke",
                       "i2c": "0x40", "port": 0}]
    r = _lagre_hal(anlegg, fns)
    assert r.status_code == 400
    assert "ukjent node" in _feil(r)


def test_togvei_mot_ukjent_felt_avvises(anlegg):
    # «spor» kan være fritekst (eldre konfig), men «frie» må være kjente
    # sporfelt — det er dem forriglingen faktisk sjekker
    fr = anlegg.klient.get("/api/forrigling").get_json()
    tv = copy.deepcopy(fr["togveier"])
    tv[0]["frie"] = tv[0].get("frie", []) + ["FINNES-IKKE"]
    r = anlegg.klient.post("/api/forrigling", json={"togveier": tv})
    assert r.status_code == 400
    assert anlegg.fil("forrigling.json")["togveier"] == fr["togveier"]


# ---------- litra-omdøping ----------

def test_omdoping_av_sporfelt_skriver_om_alle_referanser(anlegg):
    """257029e: alle referanser følger med når en litra byttes."""
    fns, _ = _forste(anlegg)
    fr = anlegg.fil("forrigling.json")
    brukt = {tv.get(k) for tv in fr["togveier"] for k in SPORFELT_REFS_TOGVEI}
    felt = next(f for f in fns
                if f.get("type") == "sporfelt" and f["id"] in brukt)
    gammel, ny = felt["id"], "QQ9"
    felt["gammel_id"], felt["id"] = gammel, ny

    r = _lagre_hal(anlegg, fns)
    assert r.status_code == 200, _feil(r)

    for tv in anlegg.fil("forrigling.json")["togveier"]:
        for k in SPORFELT_REFS_TOGVEI:
            assert tv.get(k) != gammel, f"togvei {tv.get('id')}.{k}"
        assert gammel not in tv.get("frie", [])
    for f in anlegg.fil("hal.json")["functions"]:
        for k in SPORFELT_REFS_HAL:
            assert f.get(k) != gammel, f"{f['id']}.{k}"
        assert "gammel_id" not in f
    alle = json.dumps(anlegg.fil("forrigling.json"))
    assert ny in alle


# ---------- backup og gjenoppretting ----------

def _gjenopprett(h, data):
    return h.klient.post(
        "/api/restore",
        data={"file": (io.BytesIO(json.dumps(data).encode()), "b.json")},
        content_type="multipart/form-data")


def test_backup_kan_gjenopprettes(anlegg):
    """En backup UI-et selv har laget, skal alltid kunne leses inn."""
    hal = anlegg.fil("hal.json", uten_notater=True)
    fr = anlegg.fil("forrigling.json", uten_notater=True)
    backup = json.loads(anlegg.klient.get("/api/backup").data)
    assert backup["type"] == "nsi63-backup"

    (anlegg.mappe / "hal.json").unlink()
    (anlegg.mappe / "forrigling.json").unlink()
    r = _gjenopprett(anlegg, backup)
    assert r.status_code == 200, _feil(r)
    assert anlegg.fil("hal.json", True)["functions"] == hal["functions"]
    assert anlegg.fil("forrigling.json", True)["togveier"] == \
        fr["togveier"]
    # Panelet trenger begge retained etter en gjenoppretting
    assert "nsi63/config/hal" in anlegg.mq.retained
    assert "nsi63/config/forrigling" in anlegg.mq.retained


def test_backup_doper_ikke_om_anlegget(fersk, sokna):
    """ID-en i backupen meldes tilbake, men brukes aldri automatisk."""
    backup = json.loads(sokna.klient.get("/api/backup").data)
    r = _gjenopprett(fersk, backup)
    assert r.status_code == 200, _feil(r)
    assert r.get_json()["anlegg_i_backup"] == backup["anlegg"]["id"]
    assert fersk.klient.get("/api/anlegg").get_json()["id"] == ""
    assert not fersk.subprocess_kall


def test_ren_hal_fil_kan_gjenopprettes(fersk, grindvoll):
    """Eldre backuper var bare HAL, uten forrigling."""
    r = _gjenopprett(fersk, grindvoll.fil("hal.json"))
    assert r.status_code == 200, _feil(r)
    assert r.get_json()["togveier"] is None


@pytest.mark.parametrize("innhold, hint", [
    (b"ikke json", "JSON"),
    (b"[]", "format"),
    (b'{"hal": {"functions": [{"type": "sporfelt"}]}}', "litra"),
    (b'{"hal": {"functions": []}, "forrigling": {}}', "togveier"),
])
def test_ugyldig_backup_avvises(fersk, innhold, hint):
    r = fersk.klient.post(
        "/api/restore", data={"file": (io.BytesIO(innhold), "b.json")},
        content_type="multipart/form-data")
    assert r.status_code == 400
    assert hint in _feil(r)
    assert not (fersk.mappe / "hal.json").exists()


def test_backup_med_brutt_togvei_avvises(fersk, sokna):
    """43e2332: gjenoppretting validerer som vanlig lagring."""
    backup = json.loads(sokna.klient.get("/api/backup").data)
    backup["forrigling"]["togveier"][0]["frie"].append("FINNES-IKKE")
    r = _gjenopprett(fersk, backup)
    assert r.status_code == 400
    assert not (fersk.mappe / "hal.json").exists()


# ---------- anlegget ----------

def test_anleggs_id_doper_om_ap_og_hostname(fersk):
    # Nøytral ID: publiser.sh sperrer vårt eget vertsnavn i det
    # offentlige treet
    r = fersk.klient.post("/api/anlegg", json={"id": "grv"})
    assert r.status_code == 200, _feil(r)
    ut = r.get_json()
    assert (ut["id"], ut["ssid"], ut["hostname"]) == \
        ("GRV", "NSI63GRV", "nsi63grv")
    assert fersk.fil("anlegg.json")["id"] == "GRV"
    assert fersk.mq.retained_json("nsi63/config/anlegg")["id"] == "GRV"


@pytest.mark.parametrize("aid", ["SK", "SKNX", "S1N", "ØRG"])
def test_ugyldig_anleggs_id_avvises(fersk, aid):
    r = fersk.klient.post("/api/anlegg", json={"id": aid})
    assert r.status_code == 400
    assert not (fersk.mappe / "anlegg.json").exists()
    assert not fersk.subprocess_kall


# ---------- sim-knappene på panelet ----------

def test_sim_knappene_er_skjult_som_standard(fersk):
    assert fersk.klient.get("/api/anlegg").get_json()["vis_sim"] is False


def test_sim_knappene_kan_slaas_paa_og_baeres_gjennom(fersk):
    r = fersk.klient.post("/api/anlegg", json={"id": "", "vis_sim": True})
    assert r.status_code == 200, _feil(r)
    assert fersk.fil("anlegg.json")["vis_sim"] is True
    # Retained til panelet, som skjuler/viser seksjonene etter feltet
    assert fersk.mq.retained_json("nsi63/config/anlegg")["vis_sim"] is True
    # Et lagre-kall som ikke nevner feltet (eldre fane, testmodus-
    # snarveien) skal ikke slå det av
    r = fersk.klient.post("/api/anlegg", json={"id": "", "testmodus": False})
    assert r.status_code == 200, _feil(r)
    assert fersk.fil("anlegg.json")["vis_sim"] is True


# ---------- konfigbufferet ----------

def _info(h, **felt):
    h.app.cache["master_info"] = dict(felt)


def test_konfig_publiseres_kompakt(anlegg):
    """Det som publiseres er kompakt — og valideringen måler akkurat det."""
    anlegg.app.hevd_konfig()
    pl = anlegg.mq.retained["nsi63/config/hal"]
    assert ", " not in pl[:200] and '": ' not in pl[:200]
    hal = anlegg.app.load_hal()
    assert len(pl.encode()) == len(anlegg.app.konfig_json(hal).encode())


def test_validering_folger_masterens_buffer(anlegg):
    """En master med mindre buffer (eldre firmware: 16 kB) skal avvise
    det en 24 kB-master tar imot — HAL-UI måler mot det masteren melder."""
    a = anlegg.app
    hal = a.load_hal()
    n = len(a.konfig_json(hal).encode())
    _info(anlegg, buf=n + 512 - 1)            # akkurat for lite
    assert a._for_stor(hal, "HAL") is not None
    _info(anlegg, buf=n + 512)                # akkurat nok
    assert a._for_stor(hal, "HAL") is None


def test_validering_uten_masterinfo_bruker_standard(anlegg):
    a = anlegg.app
    a.cache["master_info"] = None
    assert a._master_buffer() == a.MASTER_MQTT_BUFFER
    _info(anlegg, buf=10 ** 6)                # aldri mer enn standarden
    assert a._master_buffer() == a.MASTER_MQTT_BUFFER


def test_for_stor_konfig_avvises_ved_lagring(fersk):
    a = fersk.app
    _info(fersk, buf=4096)
    fns = [{"id": f"F{i}", "type": "sporfelt", "bindinger": []}
           for i in range(80)]
    r = fersk.klient.post("/api/hal", json={"functions": fns})
    assert r.status_code == 400 and "byte" in r.get_json()["error"]


def test_feilet_masterbuffer_gir_ikke_negativ_grense(anlegg):
    """setBufferSize() som feilet ved oppstart: PubSubClient faller til 256."""
    _info(anlegg, buf=256)
    feil = anlegg.app._for_stor(anlegg.app.load_hal(), "HAL")
    assert feil and "maks 0" in feil


def test_manuellveksel_med_sensorer_og_lamper(fersk):
    """manuellveksel kan binde drivutgang, stillingssensor, kontrollampe og lokal betjening."""
    mac = "aa1122334455"
    fns = [{
        "id": "V1",
        "type": "manuellveksel",
        "bindinger": [
            {"sted": "ut-normal",     "node": mac, "i2c": "0x40", "port": 0},
            {"sted": "ut-avvik",      "node": mac, "i2c": "0x40", "port": 1},
            {"sted": "panel-normal",  "node": mac, "i2c": "0x40", "port": 2},
            {"sted": "panel-avvik",   "node": mac, "i2c": "0x40", "port": 3},
            {"sted": "sensor-normal", "node": mac, "i2c": "0x20", "port": 0},
            {"sted": "sensor-avvik",  "node": mac, "i2c": "0x20", "port": 1},
            {"sted": "lokal-normal",  "node": mac, "i2c": "0x20", "port": 2},
            {"sted": "lokal-avvik",   "node": mac, "i2c": "0x20", "port": 3},
        ],
    }]
    r = _lagre_hal(fersk, fns)
    assert r.status_code == 200, _feil(r)
    lamper = {besk for _, _, _, besk, _ in fersk.app.lamp_list(fersk.app.load_hal())}
    assert "V1 (panel-normal)" in lamper and "V1 (panel-avvik)" in lamper
